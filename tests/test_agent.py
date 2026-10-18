"""Agent behaviour that doesn't need the model: messages are written straight into the saved state."""
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from aura import agent, config, threads
from aura.agent import _wanted_tools


def put(aura, *messages):
    aura.graph.update_state(aura.config, {"messages": list(messages)}, as_node="model")


def test_tool_selection_by_message():
    core = {"web_search", "get_weather", "memory"}
    assert _wanted_tools([HumanMessage("hey")]) == core
    assert _wanted_tools([HumanMessage("add buy milk to my list")]) == core | {"tasks"}
    assert "reminders" in _wanted_tools([HumanMessage("remind me in 20 minutes to stretch")])
    assert "generate_image" in _wanted_tools([HumanMessage("draw a fox")])
    picked = _wanted_tools([HumanMessage("save a letter in a new folder in Downloads")])
    assert {"save_document", "files"} <= picked


def test_follow_ups_keep_recently_used_tools():
    # "cancel it" has no keyword of its own; the reminder tool used a turn ago must stay available.
    history = [
        HumanMessage("remind me in 30 minutes to stretch"),
        AIMessage("", tool_calls=[{"name": "reminders", "args": {"action": "set"}, "id": "c1"}]),
        ToolMessage("Reminder #1 set", tool_call_id="c1"),
        AIMessage("Done."),
        HumanMessage("cancel it"),
    ]
    assert "reminders" in _wanted_tools(history)


def test_history_hides_summaries_and_includes_images(aura_agent):
    image = config.DATA_DIR / "images" / "fox.jpg"
    image.parent.mkdir()
    image.write_bytes(b"jpg")
    put(aura_agent,
        HumanMessage("Here is a summary of the conversation to date: ...", additional_kwargs={"lc_source": "summarization"}),
        HumanMessage("draw a fox"),
        AIMessage("", tool_calls=[{"name": "generate_image", "args": {}, "id": "c1"}]),
        ToolMessage("Generated", tool_call_id="c1", name="generate_image", artifact={"image": str(image)}),
        AIMessage("Here's your fox."))
    assert aura_agent.history() == [("user", "draw a fox"), ("image", str(image)), ("assistant", "Here's your fox.")]


def test_old_images_recovered_from_result_text(aura_agent):
    # Images made before results carried an artifact only have the path in the text.
    image = config.DATA_DIR / "images" / "cat.jpg"
    image.parent.mkdir()
    image.write_bytes(b"jpg")
    put(aura_agent, HumanMessage("draw a cat"),
        AIMessage("", tool_calls=[{"name": "generate_image", "args": {}, "id": "c1"}]),
        ToolMessage(f"Generated with Pollinations (free) and opened {image}.", tool_call_id="c1", name="generate_image"))
    assert ("image", str(image)) in aura_agent.history()


def test_repair_answers_dangling_tool_calls_and_keeps_partial_text(aura_agent):
    # After Stop mid-tool, every tool call needs a result or Groq rejects the next request.
    put(aura_agent, HumanMessage("weather?"),
        AIMessage("", tool_calls=[{"name": "get_weather", "args": {"city": "Lahore"}, "id": "c1"}]))
    aura_agent._repair(partial_text="It's sunny")
    msgs = aura_agent.graph.get_state(aura_agent.config).values["messages"]
    assert isinstance(msgs[-2], ToolMessage) and msgs[-2].tool_call_id == "c1"
    assert isinstance(msgs[-1], AIMessage) and msgs[-1].content.startswith("It's sunny")


def test_new_chat_and_open_thread_persist_choice():
    aura = agent.Aura()  # not a fixed thread: remembers the open chat in state.json
    first = aura.thread_id
    aura.new_chat()
    assert aura.thread_id != first
    assert json.loads(agent.STATE_FILE.read_text())["thread_id"] == aura.thread_id
    aura.open_thread(first)
    assert agent.Aura().thread_id == first


def test_threads_index_title_rename_search_delete(aura_agent):
    put(aura_agent, HumanMessage("hey"), AIMessage("Hi!"), HumanMessage("what can you do for me?"),
        AIMessage("I can check the weather, manage tasks..."))
    threads.touch(aura_agent.graph, aura_agent.thread_id)
    listed = threads.list_threads(aura_agent.graph)
    assert listed[0]["title"] == "what can you do for me?"  # skips the "hey" opener
    assert threads.search(aura_agent.graph, "weather")[0]["snippet"]
    threads.rename(aura_agent.thread_id, "First chat")
    threads.touch(aura_agent.graph, aura_agent.thread_id)  # a later turn keeps the custom title
    assert threads.list_threads(aura_agent.graph)[0]["title"] == "First chat"
    threads.delete(aura_agent.checkpointer, aura_agent.thread_id)
    assert threads.list_threads(aura_agent.graph) == []


def test_typographic_lookalikes_are_made_plain(aura_agent):
    # A copied "Coffee‑5G" (non-breaking hyphen) wifi password wouldn't work when pasted.
    from aura.agent import _plain
    assert _plain("Coffee‑5G at 27 °C") == "Coffee-5G at 27 °C"
    put(aura_agent, HumanMessage("wifi?"), AIMessage("It's Coffee‑5G"))
    assert aura_agent.history()[-1] == ("assistant", "It's Coffee-5G")


def test_research_answer_is_shown_as_the_reply(aura_agent):
    # research is return_direct: its cited answer is the reply itself, so history must show it.
    put(aura_agent, HumanMessage("python vs rust?"),
        AIMessage("", tool_calls=[{"name": "research", "args": {"question": "python vs rust"}, "id": "r1"}]),
        ToolMessage("Rust is faster [1].\n\n**Sources**\n1. [A](https://a.com)", tool_call_id="r1", name="research"))
    assert aura_agent.history()[-1] == ("assistant", "Rust is faster [1].\n\n**Sources**\n1. [A](https://a.com)")
