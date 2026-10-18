from datetime import date, timedelta

from aura import config, memory
from aura.learner import MemoryOps


def test_facts_add_dedupe_edit_delete():
    key = memory.add_fact("Studies CS at FAST.")
    assert memory.add_fact("studies cs at fast") is None  # same fact, different case/punctuation
    assert memory.edit_fact(key, "Studies CS at FAST, Islamabad")
    assert [f["text"] for f in memory.facts()] == ["Studies CS at FAST, Islamabad"]
    assert memory.delete_fact(key) and memory.facts() == []


def test_day_notes_dedupe_and_cap():
    for i in range(10):
        memory.add_day_note(f"Note number {i}")
    assert not memory.add_day_note("Note number 9")
    assert len(memory.days(1)[0]["notes"]) == 8  # keeps the latest 8


def test_prompt_block_has_facts_and_recent_days_only():
    memory.add_fact("Prefers short answers")
    memory.add_day_note("Worked on AURA")
    memory.add_day_note("Ancient history", date.today() - timedelta(days=30))
    block = memory.prompt_block()
    assert config.USERNAME in block and "Prefers short answers" in block and "Worked on AURA" in block
    assert "Ancient history" not in block  # older than a week: only reachable via recall


def test_empty_memory_adds_nothing_to_prompt():
    assert memory.prompt_block() == ""


def test_search_and_forget_everything():
    memory.add_fact("Networks exam on Tue 21 Oct 2026")
    memory.add_day_note("Nervous about the exam")
    assert any("exam" in hit for hit in memory.search("when is my exam"))
    memory.forget_everything()
    assert memory.facts() == [] and memory.days() == []


def test_learning_toggle_persists():
    assert memory.learning_enabled()
    memory.set_learning(False)
    assert not memory.learning_enabled()


def test_learner_accepts_wrapped_strings():
    # Regression: the model sometimes returned {"description": "..."} instead of plain strings.
    ops = MemoryOps.model_validate({"add": [{"description": "Prefers short answers"}, "Lives in Lahore"],
                                    "update": [], "delete": [], "day_note": None})
    assert ops.add == ["Prefers short answers", "Lives in Lahore"]
