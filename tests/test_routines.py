from datetime import date, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from aura import agent, checkins, config, lists, routines, settings, tools

MON = date(2026, 10, 19)  # a Monday
FRI = MON + timedelta(days=4)


@pytest.fixture(autouse=True)
def defaults(monkeypatch):
    monkeypatch.setattr(config, "FOLLOWUPS", True)
    monkeypatch.setattr(config, "ROUTINE_REMINDER", 15)


def at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())


def test_parse_days():
    assert routines.parse_days("every day except friday") == [0, 1, 2, 3, 5, 6]
    assert routines.parse_days("mon-fri") == [0, 1, 2, 3, 4]
    assert routines.parse_days("Monday to Thursday, Saturday") == [0, 1, 2, 3, 5]
    assert routines.parse_days("weekdays") == [0, 1, 2, 3, 4]
    assert routines.parse_days("sat & sun") == [5, 6]
    assert routines.parse_days("fri-mon") == [0, 4, 5, 6]  # wraps around the weekend
    assert routines.parse_days("daily but not sundays") == [0, 1, 2, 3, 4, 5]
    with pytest.raises(ValueError):
        routines.parse_days("someday")


def test_parse_time_and_labels():
    assert routines.parse_time("4:30pm") == "16:30"
    assert routines.parse_time("7:30 am") == "07:30"
    assert routines.parse_time("12am") == "00:00"
    assert routines.parse_time("13") == "13:00"
    with pytest.raises(ValueError):
        routines.parse_time("25:00")
    assert routines.days_label([0, 1, 2, 3, 5, 6]) == "every day except Fri"
    assert routines.days_label([0, 1, 2, 3, 4]) == "Mon–Fri"


def test_adding_the_same_routine_updates_it():
    routines.add("Gym", "every day except fri", "4:30pm")
    r = routines.add("gym", "every day except fri", "17:00")
    assert r["existing"] and len(routines.routines()) == 1 and routines.routines()[0]["start"] == "17:00"


def test_today_follows_the_weekly_schedule():
    routines.add("School", "mon-fri", "7:30", "13:30")
    routines.add("Gym", "every day except friday", "16:30")
    assert [(r["text"], r["status"]) for r in routines.today(at(MON, "10:00"))] == [
        ("School", "now"), ("Gym", "upcoming")]
    assert [r["text"] for r in routines.today(at(FRI, "10:00"))] == ["School"]  # no gym on Friday
    assert routines.today(at(MON + timedelta(days=6), "10:00"))[0]["text"] == "Gym"  # Sunday: no school


def test_reminder_fires_once_inside_the_lead_time():
    routines.add("Gym", "daily", "16:30")
    assert routines.due_reminders(at(MON, "16:10")) == []         # too early
    fired = routines.due_reminders(at(MON, "16:16"))
    assert [r["text"] for r in fired] == ["Gym"]
    assert routines.reminder_text(fired[0], at(MON, "16:16")) == "Gym in 14 min (16:30)"
    assert routines.due_reminders(at(MON, "16:20")) == []         # once a day
    assert routines.due_reminders(at(MON + timedelta(days=1), "16:20"))  # and again tomorrow


def test_reminder_lead_is_a_setting(monkeypatch):
    routines.add("Gym", "daily", "16:30")
    monkeypatch.setattr(config, "ROUTINE_REMINDER", 30)
    assert routines.due_reminders(at(MON, "16:05"))
    monkeypatch.setattr(config, "ROUTINE_REMINDER", 0)  # off
    assert routines.due_reminders(at(MON + timedelta(days=1), "16:25")) == []


def test_late_start_and_skipped_days_get_no_reminder():
    gym = routines.add("Gym", "daily", "16:30")
    assert routines.due_reminders(at(MON, "16:45")) == []  # AURA wasn't running in time: don't fire late
    routines.set_status(gym["id"], "skipped", MON + timedelta(days=1))
    assert routines.due_reminders(at(MON + timedelta(days=1), "16:20")) == []


def test_asks_once_after_it_ends_unless_already_answered():
    routines.add("School", "mon-fri", "7:30", "13:30")
    gym = routines.add("Gym", "daily", "16:30")  # no end time: counts as an hour
    assert [r["text"] for r in routines.to_ask_about(at(MON, "13:50"))] == ["School"]
    assert routines.to_ask_about(at(MON, "17:40")) == []               # gym not over + 15 min yet
    assert [r["text"] for r in routines.to_ask_about(at(MON, "17:45"))] == ["Gym"]
    assert routines.to_ask_about(at(MON, "18:00")) == []               # asked already
    routines.set_status(gym["id"], "done", MON + timedelta(days=1))    # told AURA before it asked
    assert [r["text"] for r in routines.to_ask_about(at(MON + timedelta(days=1), "18:00"))] == ["School"]
    assert routines.to_ask_about(at(MON + timedelta(days=2), "23:10")) == []  # too late at night


def test_follow_ups_respect_the_check_ins_switch(monkeypatch):
    routines.add("Gym", "daily", "16:30")
    monkeypatch.setattr(config, "FOLLOWUPS", False)
    assert routines.to_ask_about(at(MON, "18:00")) == []


def test_streak_counts_done_days_and_skips_rest_days():
    gym = routines.add("Gym", "every day except fri", "16:30")
    for i in range(7):  # Mon..Sun; Friday isn't a gym day
        day = MON + timedelta(days=i)
        status = {2: "skipped", 4: None}.get(i, "done")
        if status:
            routines.set_status(gym["id"], status, day)
    assert routines.streak(routines.find("gym"), MON + timedelta(days=6)) == 5
    routines.set_status(gym["id"], "missed", MON + timedelta(days=7))
    assert routines.streak(routines.find("gym"), MON + timedelta(days=7)) == 0


def test_overdue_tasks_are_asked_about_once():
    lists.add_task("Submit OS assignment", (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"))
    lists.add_task("Pay bill", (date.today() - timedelta(days=10)).isoformat())  # too old to ask about
    lists.add_task("Later", (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"))
    assert [t["text"] for t in lists.to_ask_about()] == ["Submit OS assignment"]
    assert lists.to_ask_about() == []


def test_followup_message():
    gym = {"text": "Gym", "start": "16:30"}
    task = {"text": "Submit OS assignment", "due_label": "today 15:00"}
    assert checkins.followup_message([gym], []) == "You had gym at 16:30. How did it go, did you make it?"
    assert "Submit OS assignment" in checkins.followup_message([], [task])
    both = checkins.followup_message([gym], [task])
    assert "- Gym (at 16:30)" in both and "- Submit OS assignment (due today 15:00)" in both
    assert checkins.followup_message([], []) is None


def test_tool_add_log_and_delete():
    out = tools.routines.invoke({"action": "add", "routine": "Gym", "days": "every day except friday",
                                 "start": "16:30"})
    assert "every day except Fri 16:30" in out and "15 min before" in out
    assert "Not added" in tools.routines.invoke({"action": "add", "routine": "X", "days": "soon", "start": "9"})
    assert "Logged Gym as done" in tools.routines.invoke({"action": "done", "routine": "the gym"})
    assert "skipped" in tools.routines.invoke({"action": "skip", "routine": "gym", "date": MON.isoformat()})
    assert "Gym: every day except Fri" in tools.routines.invoke({"action": "list"})
    assert "Deleted" in tools.routines.invoke({"action": "delete", "routine": "gym"})
    assert routines.routines() == []


def test_prompt_block_lists_the_week_and_today():
    routines.add("School", "mon-fri", "7:30", "13:30")
    block = routines.prompt_block(at(MON, "10:00"))
    assert "School Mon–Fri 07:30–13:30" in block and "Today: School 07:30–13:30 (now)" in block


def test_reply_to_a_follow_up_gets_the_routine_tools():
    msgs = [AIMessage("You had gym at 16:30. How did it go?", additional_kwargs={checkins.FOLLOWUP: True}),
            HumanMessage("yeah it was great")]
    assert {"routines", "tasks"} <= agent._wanted_tools(msgs)
    assert "routines" in agent._wanted_tools([HumanMessage("I go to gym every day except friday")])


def test_reminder_setting(monkeypatch):
    monkeypatch.setattr(settings, "_write", lambda k, v: None)
    assert settings.apply("routine_reminder", "30")[0] == "Routine reminders 30 min before."
    assert settings.apply("routine_reminder", "0")[0] == "Routine reminders off."
    with pytest.raises(ValueError):
        settings.apply("routine_reminder", "7")


def test_snapshot_includes_routines():
    routines.add("Gym", "daily", "16:30")
    snap = lists.snapshot()
    assert snap["routines"][0]["days_label"] == "every day" and snap["today"][0]["text"] == "Gym"
