from datetime import date, datetime, timedelta

from app.db import Goal, Settings, Topic
from app.planner import schedule
from app.rag import chunk

NOW = datetime(2026, 11, 2, 9, 0)


def _plan(daily=120, days=10):
    goals = [Goal(id=1, title="A", deadline=NOW.date() + timedelta(days=days)),
             Goal(id=2, title="B", deadline=NOW.date() + timedelta(days=days // 2))]
    topics = [Topic(id=i, goal_id=1 if i < 3 else 2, position=i, name=f"T{i}", est_hours=1.5) for i in range(5)]
    return goals, schedule(goals, topics, {}, Settings(daily_minutes=daily, session_minutes=45), NOW)


def test_no_overlaps_cap_and_deadlines():
    goals, (blocks, warnings) = _plan()
    assert not warnings
    blocks.sort(key=lambda b: b["start"])
    for a, b in zip(blocks, blocks[1:]):
        assert a["end"] <= b["start"]
    per_day = {}
    for b in blocks:
        per_day[b["start"].date()] = per_day.get(b["start"].date(), 0) + (b["end"] - b["start"]).seconds // 60
    assert max(per_day.values()) <= 120
    deadline = {g.id: g.deadline for g in goals}
    assert all(b["start"].date() < deadline[b["goal_id"]] for b in blocks)


def test_reviews_come_after_learning():
    _, (blocks, _) = _plan()
    learned = {}
    for b in sorted(blocks, key=lambda b: b["start"]):
        if b["kind"] == "learn":
            learned[b["topic_id"]] = b["start"].date()
        else:
            assert b["start"].date() > learned[b["topic_id"]]


def test_warns_when_time_runs_out():
    _, (_, warnings) = _plan(daily=30, days=2)
    assert warnings


def test_chunk_keeps_heading():
    chunks = chunk([{"heading": "Intro", "page": 1, "text": "word " * 450}])
    assert len(chunks) == 3 and all(c["heading"] == "Intro" for c in chunks)


def test_offline_topics_follow_notes_structure(monkeypatch):
    from app import planner

    chunks = [{"text": "word " * 60, "filename": "n.md", "heading": h, "page": 0} for h in ("A", "A", "B")]
    chunks += [{"text": "word " * 200, "filename": "p.pdf", "heading": "", "page": p} for p in (1, 1, 2, 3, 4, 5, 6, 7, 8)]
    monkeypatch.setattr(planner.rag, "goal_chunks", lambda goal_id: chunks)
    topics = planner.offline_topics(1)
    names = [t["name"] for t in topics]
    assert names[:2] == ["A", "B"]
    # ~1500-word page runs that never overlap
    assert names[2:] == ["p.pdf pp. 1–7", "p.pdf p. 8"]


def test_learning_is_spread_across_days():
    goal = Goal(id=1, title="A", deadline=NOW.date() + timedelta(days=4))
    topics = [Topic(id=i, goal_id=1, position=i, name=f"T{i}", est_hours=1.0) for i in range(3)]
    blocks, warnings = schedule([goal], topics, {}, Settings(daily_minutes=240, session_minutes=45), NOW)
    learn_days = {b["start"].date() for b in blocks if b["kind"] == "learn"}
    assert not warnings
    assert len(learn_days) == 3  # 3h over 3 days, not all on day one
    assert NOW.date() + timedelta(days=3) not in learn_days  # day before deadline is for review


def test_schedule_works_around_pinned_sessions():
    goal = Goal(id=1, title="A", deadline=NOW.date() + timedelta(days=3))
    topics = [Topic(id=1, goal_id=1, position=0, name="T", est_hours=2.0)]
    pinned = (datetime.combine(NOW.date(), datetime.min.time()).replace(hour=18, minute=30),
              datetime.combine(NOW.date(), datetime.min.time()).replace(hour=19, minute=15))
    blocks, _ = schedule([goal], topics, {}, Settings(daily_minutes=180, session_minutes=45), NOW, [pinned])
    for b in blocks:
        assert b["end"] <= pinned[0] or b["start"] >= pinned[1]


def test_quest_due_before_usual_start_is_studied_right_away():
    now = datetime(2026, 11, 2, 1, 30)
    urgent = Goal(id=1, title="Paper", deadline=now.date(), due_time="04:00")
    later = Goal(id=2, title="Exam", deadline=now.date() + timedelta(days=5))
    topics = [Topic(id=1, goal_id=1, position=0, name="Read", est_hours=2.0),
              Topic(id=2, goal_id=2, position=0, name="Ch1", est_hours=1.0)]
    settings = Settings(daily_minutes=240, session_minutes=45, day_start="18:12")
    blocks, warnings = schedule([urgent, later], topics, {}, settings, now)
    paper = [b for b in blocks if b["goal_id"] == 1]
    assert not warnings
    assert paper and all(now <= b["start"] and b["end"] <= datetime(2026, 11, 2, 4, 0) for b in paper)
    first_exam = min(b["start"] for b in blocks if b["goal_id"] == 2)
    assert first_exam >= max(b["end"] for b in paper)  # the urgent quest goes first
    later_days = [b for b in blocks if b["start"].date() > now.date()]
    assert all(b["start"].time() >= datetime.strptime("18:12", "%H:%M").time() for b in later_days)
