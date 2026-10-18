"""The research graph with fake search, page reading and models: plan -> search -> read -> write."""
from aura import research


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def with_structured_output(self, schema, **kw):
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.reply


def test_research_pipeline(monkeypatch):
    planner = FakeLLM(research.Queries(queries=["python vs rust speed", "python vs rust learning curve"]))
    writer = FakeLLM(type("Msg", (), {"content": "Rust is faster [1], Python is easier to learn [3]."})())
    monkeypatch.setattr(research, "_llm", lambda model, max_tokens: planner if max_tokens == 300 else writer)
    hits = {
        "python vs rust speed": [{"title": "A", "href": "https://a.com/1", "body": "a1"},
                                 {"title": "A2", "href": "https://a.com/2", "body": "a2"},
                                 {"title": "A3", "href": "https://a.com/3", "body": "a3"}],   # 3rd from a.com is skipped
        "python vs rust learning curve": [{"title": "B", "href": "https://b.org/x", "body": "b"},
                                          {"title": "A", "href": "https://a.com/1", "body": "dup"}],  # duplicate URL
    }
    statuses = []
    graph = research.build(statuses.append, search=lambda q: hits[q], read=lambda url: f"page text of {url}")
    out = graph.invoke({"question": "Python or Rust for a beginner?"})

    assert [s["url"] for s in out["sources"]] == ["https://a.com/1", "https://a.com/2", "https://b.org/x"]
    assert "[1] A (https://a.com/1)\npage text of https://a.com/1" in writer.prompts[0]
    assert out["answer"].startswith("Rust is faster [1]")
    assert "**Sources**\n1. [A](https://a.com/1)\n2. [A2](https://a.com/2)\n3. [B](https://b.org/x)" in out["answer"]
    assert statuses[0] == "researching · planning searches" and "reading 3 sources" in statuses[2]


def test_unreadable_pages_fall_back_to_snippets_and_no_sources_is_handled(monkeypatch):
    planner = FakeLLM(research.Queries(queries=["q"]))
    writer = FakeLLM(type("Msg", (), {"content": "From the snippet [1]."})())
    monkeypatch.setattr(research, "_llm", lambda model, max_tokens: planner if max_tokens == 300 else writer)

    def broken(url):
        raise TimeoutError

    out = research.build(search=lambda q: [{"title": "T", "href": "https://t.com", "body": "snippet text"}],
                         read=broken).invoke({"question": "x"})
    assert out["sources"][0]["text"] == "snippet text"

    empty = research.build(search=lambda q: [], read=broken).invoke({"question": "x"})
    assert "couldn't find usable sources" in empty["answer"]
