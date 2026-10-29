"""Turns a goal's material into topics (AI + RAG) and topics into a schedule (plain Python)."""

import math
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, delete, select

from app import llm, rag
from app.db import Goal, Settings, StudySession, Topic

REVIEW_AFTER_DAYS = (1, 3, 7)  # spaced repetition
REVIEW_MINUTES = 20
MAX_BLOCKS_PER_TOPIC_PER_DAY = 2
# Offline mode only (no LLM to judge effort):
WORDS_PER_STUDY_HOUR = 1500  # careful reading + note-making
MIN_TOPIC_WORDS = 40  # near-empty sections are merged into the previous topic
PAGES_TOPIC_WORDS = 1500  # PDFs without headings: group pages into ~1h topics

TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                    "est_hours": {"type": "number"},
                },
                "required": ["name", "summary", "difficulty", "est_hours"],
            },
        }
    },
    "required": ["topics"],
}


async def extract_topics(session: Session, goal: Goal) -> bool:
    """Builds the goal's topics. Uses the AI when available, otherwise the notes' own structure.
    Returns True if the AI was used."""
    try:
        items, used = await _ai_topics(goal), True
    except llm.LLMError:
        items, used = offline_topics(goal.id), False
    session.exec(delete(Topic).where(Topic.goal_id == goal.id))
    session.add_all(Topic(goal_id=goal.id, position=i, **item) for i, item in enumerate(items))
    session.commit()
    return used


async def _ai_topics(goal: Goal) -> list[dict]:
    data = await llm.ask(
        "You plan study schedules. Use only the student's material; do not invent topics.",
        f"Goal: {goal.title}\n\nSTUDENT'S MATERIAL\n{rag.goal_text(goal.id)}\n\n"
        "Split this material into the topics a student must learn, in learning order. For each give a "
        "one-sentence summary, a difficulty from 1 to 5, and realistic study hours (est_hours) based on how much "
        "material covers it and how hard it is.",
        TOPIC_SCHEMA,
    )
    items = []
    for t in data["topics"]:
        # RAG: attach the passages of the student's notes that cover this topic.
        hits = rag.search(f"{t['name']}: {t['summary']}", goal.id, k=3)
        items.append({"name": t["name"], "summary": t["summary"], "difficulty": t["difficulty"],
                      "est_hours": max(0.5, float(t["est_hours"])), "sources": [_source(h) for h in hits]})
    return items


def offline_topics(goal_id: int) -> list[dict]:
    """No LLM: the notes' own sections become topics (headings, or runs of PDF pages),
    and study time is estimated from how much text each one has."""
    groups: list[dict] = []
    for c in rag.goal_chunks(goal_id):
        g = groups[-1] if groups else None
        words = len(c["text"].split())
        same_file = g is not None and g["chunks"][0]["filename"] == c["filename"]
        if same_file and (
            (c["heading"] and (c["heading"] == g["heading"] or g["words"] < MIN_TOPIC_WORDS))
            or (not c["heading"] and (c["page"] == g["chunks"][-1]["page"] or g["words"] < PAGES_TOPIC_WORDS))
        ):
            g["chunks"].append(c)
            g["words"] += words
        else:
            groups.append({"heading": c["heading"], "chunks": [c], "words": words})

    items = []
    for g in groups:
        first, last = g["chunks"][0], g["chunks"][-1]
        if g["heading"]:
            name = g["heading"]
        elif first["page"]:
            pages = f"p. {first['page']}" if first["page"] == last["page"] else f"pp. {first['page']}–{last['page']}"
            name = f"{first['filename']} {pages}"
        else:
            name = first["filename"]
        items.append({
            "name": name,
            "summary": first["text"].split(". ")[0][:200],
            "difficulty": 3,
            "est_hours": max(0.5, round(g["words"] / WORDS_PER_STUDY_HOUR * 2) / 2),
            "sources": [_source(c) for c in g["chunks"][:3]],
        })
    return items


def _source(chunk: dict) -> dict:
    return {"filename": chunk["filename"], "heading": chunk["heading"], "page": chunk["page"], "snippet": chunk["text"][:300]}


def due_at(g: Goal) -> datetime:
    """When a quest is due. Without a due time, studying stops when the deadline day starts (exam day)."""
    return datetime.combine(g.deadline, time.fromisoformat(g.due_time) if g.due_time else time(0, 0))


def schedule(goals: list[Goal], topics: list[Topic], done_minutes: dict[int, int], settings: Settings,
             now: datetime, busy: list[tuple[datetime, datetime]] = ()) -> tuple[list[dict], list[str]]:
    """Packs learn blocks and spaced reviews into free time before each quest is due,
    working around `busy` slots (sessions the student pinned to a time)."""
    due = {g.id: due_at(g) for g in goals}
    queues: dict[int, list[int]] = {}  # topic_id -> remaining learn block lengths
    for t in topics:
        left = max(0, round(t.est_hours * 60) - done_minutes.get(t.id, 0))
        n = math.ceil(left / settings.session_minutes)
        queues[t.id] = [min(settings.session_minutes, left - i * settings.session_minutes) for i in range(n)]
    by_goal = {g.id: sorted((t for t in topics if t.goal_id == g.id), key=lambda t: t.position) for g in goals}
    goal_of = {t.id: t.goal_id for t in topics}
    reviews: list[tuple[date, int]] = []  # (due day, topic_id)
    blocks: list[dict] = []

    rounded_now = (now + timedelta(minutes=4)).replace(second=0, microsecond=0)
    rounded_now -= timedelta(minutes=rounded_now.minute % 5)
    day = now.date()
    last_day = (max(due.values()) - timedelta(minutes=1)).date()
    while day <= last_day:
        normal_start = datetime.combine(day, time.fromisoformat(settings.day_start))
        day_end = datetime.combine(day, time(23, 30))
        urgent: set[int] = set()
        if day == now.date():
            # Today's plan starts now (the usual start time only applies to future days).
            # Quests due before that usual start time go first.
            urgent = {g.id for g in goals if now < due[g.id] <= normal_start}
            cursor = rounded_now
        else:
            cursor = normal_start
        # Late in the day there's less time left: shrink the budget (breaks included).
        minutes_left = (day_end - cursor).total_seconds() / 60
        budget = int(min(settings.daily_minutes, minutes_left * settings.session_minutes / (settings.session_minutes + 10)))
        busy_today = sorted(b for b in busy if b[0].date() == day)
        budget -= sum(int((e - s).total_seconds() // 60) for s, e in busy_today)  # pinned sessions use up the day
        per_topic: dict[int, int] = {}
        # Spread learning evenly instead of cramming it into the first days: each quest gets its remaining
        # learning divided by the days left, keeping the last day before it's due for review.
        quota, learned = {}, {}
        for g in goals:
            remaining = sum(sum(queues[t.id]) for t in by_goal[g.id])
            days = (due[g.id].date() - day).days - (0 if g.due_time else 1)
            quota[g.id], learned[g.id] = math.ceil(remaining / max(1, days)), 0

        while budget >= 15:
            # Skip past any pinned session this block would overlap (blocks are at most session_minutes long).
            longest = max(settings.session_minutes, REVIEW_MINUTES)
            moved = True
            while moved:
                moved = False
                for b_start, b_end in busy_today:
                    if cursor < b_end and cursor + timedelta(minutes=longest) > b_start:
                        cursor, moved = b_end + timedelta(minutes=10), True
            if cursor + timedelta(minutes=longest) > day_end:
                break

            pool = [g for g in goals if not urgent or g.id in urgent]
            fits = lambda gid, m: cursor + timedelta(minutes=m) <= due[gid]  # noqa: E731
            pick = None
            due_reviews = [r for r in reviews if r[0] <= day and r[1] not in per_topic
                           and goal_of[r[1]] in {g.id for g in pool} and fits(goal_of[r[1]], REVIEW_MINUTES)]
            if due_reviews and REVIEW_MINUTES <= budget:
                reviews.remove(due_reviews[0])
                pick = ("review", due_reviews[0][1], REVIEW_MINUTES)
            else:
                # Next unfinished topic of each quest, the one due soonest first.
                for g in sorted(pool, key=lambda g: due[g.id]):
                    if learned[g.id] >= quota[g.id]:
                        continue
                    t = next((t for t in by_goal[g.id] if queues[t.id]), None)
                    # Spacing limit per topic, except when the quest is due today and there's no later day.
                    if (t and (per_topic.get(t.id, 0) < MAX_BLOCKS_PER_TOPIC_PER_DAY or due[g.id].date() == day)
                            and queues[t.id][0] <= budget and fits(g.id, queues[t.id][0])):
                        pick = ("learn", t.id, queues[t.id].pop(0))
                        if not queues[t.id]:  # topic finished: schedule its reviews
                            reviews += [(day + timedelta(days=d), t.id) for d in REVIEW_AFTER_DAYS]
                        break
            if not pick:
                if urgent:  # urgent work placed (or out of time): carry on with the other quests
                    urgent = set()
                    continue
                break
            kind, tid, minutes = pick
            blocks.append({"kind": kind, "topic_id": tid, "goal_id": goal_of[tid],
                           "start": cursor, "end": cursor + timedelta(minutes=minutes)})
            cursor += timedelta(minutes=minutes + 10)  # 10 min break
            budget -= minutes
            per_topic[tid] = per_topic.get(tid, 0) + 1
            if kind == "learn":
                learned[goal_of[tid]] += minutes
        day += timedelta(days=1)

    warnings = []
    for g in goals:
        left = sum(sum(queues[t.id]) for t in by_goal[g.id])
        when = f"at {due[g.id]:%H:%M}" if g.due_time else f"on {g.deadline:%a %d %b}"
        if left and due[g.id] - now < timedelta(hours=24):
            warnings.append(f"{g.title}: {left / 60:.1f}h of study doesn't fit before it's due {when}. "
                            "Tick off topics you can skip, or move the deadline later.")
        elif left:
            warnings.append(f"{g.title}: {left / 60:.1f}h of study doesn't fit before it's due. "
                            "Ask the assistant for more study time per day.")
    return blocks, warnings


def _goal_of(topic_id: int, topics: list[Topic]) -> int:
    return next(t.goal_id for t in topics if t.id == topic_id)


def rebuild_plan(session: Session, settings: Settings) -> None:
    """Keeps finished sessions and upcoming ones the student pinned to a time,
    and reschedules everything else from now around them."""
    now = datetime.now()
    goals = [g for g in session.exec(select(Goal)).all() if due_at(g) > now]
    # Topics ticked off in Quests need no more sessions.
    topics = session.exec(select(Topic).where(Topic.goal_id.in_([g.id for g in goals]), Topic.done == False)).all()  # noqa: E712
    kept = [s for s in session.exec(select(StudySession)).all() if s.done or (s.pinned and s.start >= now)]
    done_minutes: dict[int, int] = {}
    for s in kept:
        if s.kind == "learn":
            done_minutes[s.topic_id] = done_minutes.get(s.topic_id, 0) + int((s.end - s.start).total_seconds() // 60)
    busy = [(s.start, s.end) for s in kept if s.end > now]

    session.exec(delete(StudySession).where(StudySession.id.not_in([s.id for s in kept])))
    blocks, warnings = schedule(goals, topics, done_minutes, settings, now, busy) if goals and topics else ([], [])
    session.add_all(StudySession(**b) for b in blocks)
    settings.warnings = warnings
    session.add(settings)
    session.commit()


def move_session(session: Session, s: StudySession, start: datetime) -> None:
    """Puts a session at a time the student chose (pinned, so rebuilds keep it)."""
    start = start.replace(tzinfo=None, second=0, microsecond=0)
    end = start + (s.end - s.start)
    goal = session.get(Goal, s.goal_id)
    if start < datetime.now():
        raise ValueError("Pick a time in the future.")
    if end > due_at(goal):
        raise ValueError(f"That runs past when the quest is due ({due_at(goal):%d %b %H:%M}).")
    # Only sessions the student fixed (done or set by them) can block a move; auto-placed ones
    # get rescheduled around it when the plan rebuilds.
    clash = session.exec(select(StudySession).where(
        StudySession.id != s.id, StudySession.start < end, StudySession.end > start,
        (StudySession.done == True) | (StudySession.pinned == True))).first()  # noqa: E712
    if clash:
        raise ValueError(f"That overlaps another session ({clash.start:%a %d %b, %H:%M}–{clash.end:%H:%M}).")
    s.start, s.end, s.pinned = start, end, True
    session.add(s)
    session.commit()


async def answer(question: str, goal_id: int | None) -> dict:
    hits = rag.search(question, goal_id, k=5)
    if not hits:
        return {"answer": "No study material uploaded yet.", "sources": []}
    sources = "\n\n".join(f"[{i}] ({h['filename']} {h['heading']})\n{h['text']}" for i, h in enumerate(hits, 1))
    try:
        text = await llm.ask(
            "You are a study assistant. Answer only from the numbered sources and cite them like [1]. "
            "If the sources don't cover the question, say so.",
            f"SOURCES\n{sources}\n\nQUESTION\n{question}",
        )
    except llm.LLMError:  # offline: show the best-matching passages instead of a written answer
        hits = hits[:3]
        text = "Offline mode: here are the most relevant passages from your notes.\n\n" + "\n\n".join(
            f"[{i}] {h['text'][:400]}…" for i, h in enumerate(hits, 1))
    return {"answer": text, "sources": [{**h, "text": h["text"][:300]} for h in hits]}
