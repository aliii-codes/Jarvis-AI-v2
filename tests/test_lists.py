from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pytest

from aura import lists, reminders


def test_parse_due_formats():
    assert lists.parse_due("2026-10-23") == "2026-10-23"
    assert lists.parse_due("2026-10-23 17:00") == "2026-10-23T17:00"
    assert lists.parse_due("2026-10-23T17:00") == "2026-10-23T17:00"
    assert lists.parse_due("") is None
    with pytest.raises(ValueError):
        lists.parse_due("next friday")


def test_task_with_time_creates_reminder_and_done_cancels_it():
    when = (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    task = lists.add_task("Submit OS assignment", when)
    assert task["reminder_id"] and len(reminders.pending()) == 1
    lists.set_done(task["id"])
    assert reminders.pending() == []
    assert lists.tasks() == []


def test_parallel_duplicate_adds_keep_one_task_and_one_reminder():
    # Regression: the model fired add_task three times in parallel for one request.
    when = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d 17:00")
    calls = [("Submit OS assignment", ""), ("Submit my OS assignment", when), ("Submit OS assignment", when)]
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(lambda c: lists.add_task(*c), calls))
    open_tasks = lists.tasks()
    assert len(open_tasks) == 1 and open_tasks[0]["due"] == when.replace(" ", "T")
    assert len(reminders.pending()) == 1


def test_short_words_keep_tasks_distinct():
    # Regression: "OS" and "DB" were ignored as short words, merging different tasks.
    lists.add_task("Submit OS assignment")
    lists.add_task("Submit DB assignment")
    assert len(lists.tasks()) == 2
    assert lists.find_task("done with the DB assignment")["text"] == "Submit DB assignment"
    assert lists.find_task("finished OS assignment")["text"] == "Submit OS assignment"


def test_overdue_and_due_today_need_attention():
    lists.add_task("Pay electricity bill", (date.today() - timedelta(days=2)).isoformat())
    lists.add_task("Gym", date.today().isoformat())
    lists.add_task("Someday")
    attention = {t["text"]: t["overdue"] for t in lists.attention()}
    assert attention == {"Pay electricity bill": True, "Gym": False}


def test_rescheduling_moves_the_reminder():
    t = lists.add_task("Call mum", (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"))
    later = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 10:00")
    lists.edit_task(t["id"], due=later)
    pending = reminders.pending()
    assert len(pending) == 1 and pending[0][2] == datetime.fromisoformat(later)


def test_notes_search_and_delete():
    lists.add_note("Cafe wifi password: Coffee-5G")
    lists.add_note("Book recs from Sara: Piranesi")
    assert lists.search_notes("wifi")[0]["text"].startswith("Cafe wifi")
    assert lists.search_notes("")  # empty query returns latest notes
    note = lists.search_notes("Sara")[0]
    assert lists.delete_note(note["id"])
    assert [n["text"] for n in lists.notes()] == ["Cafe wifi password: Coffee-5G"]
