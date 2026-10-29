"""Home-screen assistant: an AI agent with a small set of tools that change the student's quests and plan."""

from datetime import date, datetime

from sqlmodel import Session, delete, select

from app import llm, planner, rag
from app.config import UPLOAD_DIR
from app.db import Document, Goal, StudySession, Topic, engine, get_settings

SYSTEM = """You are Atlas, the assistant inside Syllabuddy, a study planner. You change the student's quests,
topics, sessions and study time using your tools, then reply in 1-3 short, friendly sentences saying what you did.

Rules:
- Use the ids from the SNAPSHOT. Never invent ids.
- If something you need is missing or ambiguous (e.g. no deadline for a new quest), ask one short question instead of guessing.
- Creating a quest: if the student lists topics, use them. Otherwise propose sensible topics for the subject, with
  realistic study hours. Mention they can also create a quest from their own notes with "+ New quest".
- Only delete a quest when the student clearly asks to.
- Times are the student's local time. Dates are YYYY-MM-DD, times HH:MM (24h).
- A quest can be due at a specific time (due_time), even later today. Quests due before the usual study start
  time are scheduled right away automatically, so don't change the study start time for them.
- The plan is rebuilt automatically after your changes; don't schedule sessions one by one."""


def snapshot(session: Session) -> str:
    now = datetime.now()
    s = get_settings(session)
    lines = [f"Now: {now:%A %Y-%m-%d %H:%M}",
             f"Study time: {s.daily_minutes} min/day, sessions of {s.session_minutes} min, starting {s.day_start}"]
    for g in session.exec(select(Goal).order_by(Goal.deadline)).all():
        lines.append(f"QUEST id={g.id} '{g.title}' due {g.deadline}{' ' + g.due_time if g.due_time else ''}")
        for t in session.exec(select(Topic).where(Topic.goal_id == g.id).order_by(Topic.position)).all():
            lines.append(f"  topic id={t.id} '{t.name}' {t.est_hours}h{' DONE' if t.done else ''}")
    upcoming = session.exec(select(StudySession).where(StudySession.end >= now).order_by(StudySession.start)).all()[:40]
    names = {t.id: t.name for t in session.exec(select(Topic)).all()}
    for x in upcoming:
        lines.append(f"  session id={x.id} {x.start:%a %Y-%m-%d %H:%M}-{x.end:%H:%M} {x.kind} '{names.get(x.topic_id, '?')}'"
                     f"{' DONE' if x.done else ''}")
    return "\n".join(lines)


def _ok(text: str) -> str:
    return text


def _err(text: str) -> str:
    return f"Error: {text}"


_TYPES = {int: "integer", bool: "boolean", str: "string", float: "number"}


def _schema(params: dict) -> dict:
    """Full JSON schemas pass through; {"name": type} shorthands become one with every field required."""
    if params.get("type") == "object":
        return params
    return {"type": "object", "properties": {k: {"type": _TYPES[v]} for k, v in params.items()}, "required": list(params)}


async def run(message: str, history: list[dict]) -> dict:
    actions: list[str] = []  # human-readable log shown in the UI
    tools: list[dict] = []

    def tool(name: str, description: str, params: dict):
        def register(fn):
            tools.append({"name": name, "description": description, "parameters": _schema(params), "fn": fn})
            return fn
        return register

    @tool("create_quest", "Create a quest (an exam or deadline) with its topics.", {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "deadline": {"type": "string", "description": "YYYY-MM-DD"},
            "due_time": {"type": "string", "description": "optional HH:MM; lets a quest be due later today"},
            "topics": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "summary": {"type": "string"},
                "difficulty": {"type": "integer", "minimum": 1, "maximum": 5}, "est_hours": {"type": "number"},
            }, "required": ["name", "est_hours"]}},
        },
        "required": ["title", "deadline", "topics"],
    })
    async def create_quest(args):
        try:
            deadline = date.fromisoformat(args["deadline"])
            due_time = args.get("due_time") or ""
            if due_time:
                due_time = datetime.strptime(due_time, "%H:%M").strftime("%H:%M")
        except ValueError:
            return _err("deadline must be YYYY-MM-DD and due_time HH:MM")
        if planner.due_at(Goal(title="", deadline=deadline, due_time=due_time)) <= datetime.now():
            return _err("that's not in the future")
        if not args["topics"]:
            return _err("give at least one topic")
        with Session(engine) as session:
            g = Goal(title=args["title"], deadline=deadline, due_time=due_time)
            session.add(g)
            session.commit()
            session.add_all(Topic(goal_id=g.id, position=i, name=t["name"], summary=t.get("summary", ""),
                                  difficulty=t.get("difficulty", 3), est_hours=max(0.5, float(t["est_hours"])))
                            for i, t in enumerate(args["topics"]))
            session.commit()
            gid = g.id
        actions.append(f"Created quest “{args['title']}” due {deadline:%d %b}{' ' + due_time if due_time else ''} "
                       f"with {len(args['topics'])} topics")
        return _ok(f"created quest id={gid}")

    @tool("delete_quest", "Delete a quest with its topics and sessions.", {"quest_id": int})
    async def delete_quest(args):
        with Session(engine) as session:
            g = session.get(Goal, args["quest_id"])
            if not g:
                return _err("no such quest")
            rag.delete_goal(g.id)
            for f in UPLOAD_DIR.glob(f"{g.id}_*"):
                f.unlink(missing_ok=True)
            for model in (StudySession, Topic, Document):
                session.exec(delete(model).where(model.goal_id == g.id))
            title = g.title
            session.delete(g)
            session.commit()
        actions.append(f"Deleted quest “{title}”")
        return _ok("deleted")

    @tool("set_topic_done", "Mark a topic finished (true) or not finished (false).", {"topic_id": int, "done": bool})
    async def set_topic_done(args):
        with Session(engine) as session:
            t = session.get(Topic, args["topic_id"])
            if not t:
                return _err("no such topic")
            t.done = args["done"]
            session.add(t)
            session.commit()
            actions.append(f"{'Ticked' if args['done'] else 'Unticked'} topic “{t.name}”")
        return _ok("ok")

    @tool("set_session_done", "Mark a study session done (true) or not done (false).", {"session_id": int, "done": bool})
    async def set_session_done(args):
        with Session(engine) as session:
            s = session.get(StudySession, args["session_id"])
            if not s:
                return _err("no such session")
            s.done = args["done"]
            session.add(s)
            session.commit()
            actions.append(f"Marked the {s.start:%a %H:%M} session {'done' if args['done'] else 'not done'}")
        return _ok("ok")

    @tool("move_session", "Move a session to a new start time. It keeps its length.",
          {"session_id": int, "start": str})
    async def move_session(args):
        try:
            start = datetime.fromisoformat(args["start"])
        except ValueError:
            return _err("start must be YYYY-MM-DDTHH:MM")
        with Session(engine) as session:
            s = session.get(StudySession, args["session_id"])
            if not s:
                return _err("no such session")
            try:
                planner.move_session(session, s, start)
            except ValueError as e:
                return _err(str(e))
        actions.append(f"Moved a session to {start:%a %d %b %H:%M}")
        return _ok("moved")

    @tool("update_study_time", "Change daily study minutes, session length (minutes) and/or start time (HH:MM).", {
        "type": "object",
        "properties": {"daily_minutes": {"type": "integer", "minimum": 15, "maximum": 720},
                       "session_minutes": {"type": "integer", "minimum": 15, "maximum": 120},
                       "day_start": {"type": "string", "description": "HH:MM"}},
    })
    async def update_study_time(args):
        with Session(engine) as session:
            s = get_settings(session)
            for k in ("daily_minutes", "session_minutes", "day_start"):
                if args.get(k) is not None:
                    setattr(s, k, args[k])
            session.add(s)
            session.commit()
            actions.append(f"Study time: {s.daily_minutes} min/day, {s.session_minutes} min sessions from {s.day_start}")
        return _ok("updated")

    with Session(engine) as session:
        snap = snapshot(session)
    convo = "".join(f"{m['role'].upper()}: {m['content'][:400]}\n" for m in history[-6:])
    convo = f"CONVERSATION SO FAR\n{convo}\n" if convo else ""
    reply = await llm.ask(
        SYSTEM,
        f"SNAPSHOT\n{snap}\n\n{convo}STUDENT: {message}",
        tools=tools,
        max_turns=12,
    )
    if actions:
        with Session(engine) as session:
            planner.rebuild_plan(session, get_settings(session))
    return {"reply": reply, "actions": actions}
