from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from aura import checkins, config, memory


class FakeLLM:
    """Stands in for the small model: returns a fixed CheckIn and records the prompts it saw."""

    def __init__(self, message):
        self.message, self.prompts = message, []

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return checkins.CheckIn(message=self.message, about="exam")


@pytest.fixture(autouse=True)
def followups_on(monkeypatch):
    monkeypatch.setattr(config, "FOLLOWUPS", True)


def test_due_once_a_day_in_daytime_only(monkeypatch):
    assert checkins.due(datetime(2026, 10, 18, 10, 0))
    assert not checkins.due(datetime(2026, 10, 18, 6, 0))   # too early
    assert not checkins.due(datetime(2026, 10, 18, 23, 0))  # too late
    monkeypatch.setattr(config, "FOLLOWUPS", False)
    assert not checkins.due(datetime(2026, 10, 18, 10, 0))  # switched off in Settings


def test_nothing_known_means_no_model_call():
    llm = FakeLLM("How did the exam go?")
    assert checkins.generate(llm) is None and llm.prompts == []
    assert not checkins.due(datetime.now().replace(hour=12))  # today was still considered


def test_check_in_is_generated_recorded_and_not_repeated():
    memory.add_fact("Networks exam on Sat 17 Oct 2026")
    llm = FakeLLM("How did the networks exam go?")
    assert checkins.generate(llm) == "How did the networks exam go?"
    assert "Networks exam" in llm.prompts[0]
    assert not checkins.due(datetime.now().replace(hour=12))  # once a day
    # A later day's prompt includes it under "Recent check-ins" so the model doesn't repeat it.
    state = checkins._state()
    state["last_checked"] = "2000-01-01"
    checkins._save(state)
    llm2 = FakeLLM(None)
    assert checkins.generate(llm2) is None  # "nothing today" is a normal answer
    assert "How did the networks exam go?" in llm2.prompts[0]


def test_deliver_starts_todays_chat_or_appends(aura_agent):
    # An empty chat (no activity today) gets a fresh thread; a chat active today gets it appended.
    first_thread = aura_agent.thread_id
    assert checkins.deliver(aura_agent, "Feeling any better today?") is True
    assert aura_agent.thread_id != first_thread
    assert aura_agent.history() == [("checkin", "Feeling any better today?")]
    aura_agent.graph.update_state(aura_agent.config, {"messages": [HumanMessage("yes, thanks!"), AIMessage("Glad!")]},
                                  as_node="model")
    assert checkins.deliver(aura_agent, "Good luck with the trip!") is False
    assert aura_agent.history()[-1] == ("checkin", "Good luck with the trip!")
