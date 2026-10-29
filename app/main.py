import uuid

import httpx
from datetime import date, datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import Session, delete, select

from app import agent, llm, planner, rag
from app.config import ROOT, UPLOAD_DIR
from app.db import Document, Goal, Settings, StudySession, Topic, engine, get_session, get_settings, init_db

app = FastAPI(title="Syllabuddy")


@app.middleware("http")
async def no_stale_files(request, call_next):
    # Make browsers re-check the UI files so updates show without a hard refresh.
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
init_db()
with Session(engine) as _s:
    llm.enabled = get_settings(_s).use_ai
    _settings_at_start = get_settings(_s)
DB = Depends(get_session)


@app.get("/api/state")
def state(session: Session = DB):
    # Carry over: unfinished sessions from previous days move forward automatically.
    # Today's are left alone in case the student just hasn't ticked them yet.
    start_of_today = datetime.combine(date.today(), datetime.min.time())
    if session.exec(select(StudySession).where(StudySession.done == False, StudySession.end < start_of_today)).first():  # noqa: E712
        planner.rebuild_plan(session, get_settings(session))
    goals = session.exec(select(Goal).order_by(Goal.deadline)).all()
    docs = session.exec(select(Document)).all()
    topics = session.exec(select(Topic).order_by(Topic.position)).all()
    return {
        "ai": llm.available(),
        "ai_ready": llm.configured(),
        "ai_config": llm.public_config(),
        "ai_detected": llm.detected,
        "ai_providers": [{"id": k, "label": v[0], "base_url": v[1], "needs_key": bool(v[2]), "model": v[3]}
                         for k, v in llm.PROVIDERS.items()],
        "settings": get_settings(session).model_dump(exclude={"ai_key"}),  # the key never leaves the server
        "goals": [{**g.model_dump(), "documents": [d for d in docs if d.goal_id == g.id],
                   "topics": [t for t in topics if t.goal_id == g.id]} for g in goals],
        "sessions": session.exec(select(StudySession).order_by(StudySession.start)).all(),
    }


@app.post("/api/goals")
async def create_goal(title: str = Form(...), deadline: date = Form(...), due_time: str = Form(""),
                      daily_hours: float | None = Form(None), day_start: str = Form(""),
                      files: list[UploadFile] = File(...), session: Session = DB):
    goal = Goal(title=title, deadline=deadline, due_time=due_time.strip())
    try:
        if planner.due_at(goal) <= datetime.now():
            raise ValueError
    except ValueError:
        raise HTTPException(400, "The due date and time must be in the future (times as HH:MM).")
    # Optional study time from the form; blank keeps the current one.
    settings = get_settings(session)
    if daily_hours:
        if not 0.25 <= daily_hours <= 12:
            raise HTTPException(400, "Study hours per day must be between 0.25 and 12.")
        settings.daily_minutes = round(daily_hours * 60)
    if day_start.strip():
        try:
            settings.day_start = datetime.strptime(day_start.strip(), "%H:%M").strftime("%H:%M")
        except ValueError:
            raise HTTPException(400, "Start time must be HH:MM, e.g. 19:00.")
    session.add(settings)
    session.add(goal)
    session.commit()
    try:
        for f in files:
            if "." + f.filename.rsplit(".", 1)[-1].lower() not in rag.SUPPORTED:
                raise ValueError(f"{f.filename}: use PDF, DOCX, MD or TXT")
            path = UPLOAD_DIR / f"{goal.id}_{uuid.uuid4().hex[:8]}_{f.filename}"  # quest id prefix: deleted with it
            path.write_bytes(await f.read())
            doc = Document(goal_id=goal.id, filename=f.filename)
            session.add(doc)
            session.commit()
            doc.n_chunks = rag.index_file(path, doc.id, goal.id, f.filename)
            session.add(doc)
        session.commit()
        await planner.extract_topics(session, goal)
    except ValueError as e:
        _delete_goal(session, goal)
        raise HTTPException(400, str(e))
    planner.rebuild_plan(session, get_settings(session))
    return {"ok": True}


@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: int, session: Session = DB):
    goal = session.get(Goal, goal_id) or _404()
    _delete_goal(session, goal)
    planner.rebuild_plan(session, get_settings(session))
    return {"ok": True}


def _delete_goal(session: Session, goal: Goal) -> None:
    rag.delete_goal(goal.id)
    delete_uploads(goal.id)
    for model in (StudySession, Topic, Document):
        session.exec(delete(model).where(model.goal_id == goal.id))
    session.delete(goal)
    session.commit()


class SettingsIn(BaseModel):
    daily_minutes: int = Field(ge=15, le=720)
    session_minutes: int = Field(ge=15, le=120)
    day_start: str = Field(pattern=r"^\d{2}:\d{2}$")


@app.put("/api/settings")
def update_settings(body: SettingsIn, session: Session = DB):
    s = get_settings(session)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    planner.rebuild_plan(session, s)
    return {"ok": True}


@app.post("/api/plan")
def rebuild(session: Session = DB):
    planner.rebuild_plan(session, get_settings(session))
    return {"ok": True}


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    gender: str = Field(pattern="^(boy|girl|other)$")


@app.put("/api/profile")
def update_profile(body: ProfileIn, session: Session = DB):
    s = get_settings(session)
    s.name, s.gender = body.name.strip(), body.gender
    session.add(s)
    session.commit()
    return {"ok": True}


class TopicDoneIn(BaseModel):
    done: bool


@app.patch("/api/topics/{topic_id}")
def mark_topic(topic_id: int, body: TopicDoneIn, session: Session = DB):
    t = session.get(Topic, topic_id) or _404()
    t.done = body.done
    session.add(t)
    session.commit()
    planner.rebuild_plan(session, get_settings(session))
    return {"ok": True}


def delete_uploads(goal_id: int) -> None:
    for f in UPLOAD_DIR.glob(f"{goal_id}_*"):
        f.unlink(missing_ok=True)


class ResetIn(BaseModel):
    everything: bool = False  # False: only clear the profile (back to the welcome screen)


@app.post("/api/reset")
def reset(body: ResetIn, session: Session = DB):
    s = get_settings(session)
    if body.everything:
        for model in (StudySession, Topic, Document, Goal):
            session.exec(delete(model))
        rag.delete_all()
        for f in UPLOAD_DIR.iterdir():
            f.unlink(missing_ok=True)
        fresh = Settings(id=1)
        for k in ("daily_minutes", "session_minutes", "day_start", "warnings", "use_ai", "ai_provider", "ai_base_url", "ai_model", "ai_key"):
            setattr(s, k, getattr(fresh, k))
        llm.enabled = s.use_ai
        apply_ai(s)
    s.name, s.gender = "", ""
    session.add(s)
    session.commit()
    return {"ok": True}


class AIToggleIn(BaseModel):
    on: bool


@app.put("/api/ai")
def toggle_ai(body: AIToggleIn, session: Session = DB):
    s = get_settings(session)
    s.use_ai = llm.enabled = body.on
    session.add(s)
    session.commit()
    return {"ai": llm.available()}


class SessionPatch(BaseModel):
    done: bool | None = None
    start: datetime | None = None  # student picks their own time for this session


@app.patch("/api/sessions/{session_id}")
def update_session(session_id: int, body: SessionPatch, session: Session = DB):
    s = session.get(StudySession, session_id) or _404()
    if body.done is not None:
        s.done = body.done
    if body.start is not None:
        try:
            planner.move_session(session, s, body.start)
        except ValueError as e:
            raise HTTPException(400, str(e))
        planner.rebuild_plan(session, get_settings(session))  # shift auto-placed sessions out of its way
        return {"ok": True}
    session.add(s)
    session.commit()
    return {"ok": True}


def apply_ai(s: Settings) -> None:
    """Uses the provider saved in Settings, or auto-detects one when none is saved."""
    if s.ai_provider:
        llm.configure(s.ai_provider, s.ai_base_url, s.ai_model, s.ai_key)
    else:
        llm.auto_connect()


apply_ai(_settings_at_start)


class AIConfigIn(BaseModel):
    provider: str  # "auto" or an id from llm.PROVIDERS
    base_url: str = ""
    model: str = ""
    key: str | None = None  # None keeps the saved key


@app.put("/api/ai/config")
def set_ai_config(body: AIConfigIn, session: Session = DB):
    s = get_settings(session)
    if body.provider == "auto":
        s.ai_provider = s.ai_base_url = s.ai_model = s.ai_key = ""
    else:
        if body.provider not in llm.PROVIDERS:
            raise HTTPException(400, "Unknown provider.")
        base = body.base_url.strip() or llm.PROVIDERS[body.provider][1]
        if not base or not body.model.strip():
            raise HTTPException(400, "Enter a model name and an address.")
        if body.key is not None:
            s.ai_key = body.key.strip()
        elif body.provider != s.ai_provider:
            s.ai_key = ""  # a saved key belongs to the previous provider
        s.ai_provider, s.ai_base_url, s.ai_model = body.provider, base, body.model.strip()
    session.add(s)
    session.commit()
    apply_ai(s)
    return {"ai": llm.available(), **llm.public_config()}


@app.post("/api/ai/test")
async def test_ai():
    if not llm.configured():
        raise HTTPException(400, "Atlas isn't connected to an AI yet.")
    was, llm.enabled = llm.enabled, True
    try:
        reply = await llm.ask("You are a connection test.", "Reply with the single word OK.")
    except llm.LLMError as e:
        raise HTTPException(503, str(e))
    finally:
        llm.enabled = was
    return {"reply": reply[:80], **llm.public_config()}


@app.post("/api/ai/detect")
def detect_ai():
    llm.auto_connect() if llm.cfg["auto"] else llm.detect()
    return {"found": len(llm.detected), **llm.public_config()}


class ModelsIn(BaseModel):
    provider: str
    base_url: str = ""
    key: str | None = None


@app.post("/api/ai/models")
def ai_models(body: ModelsIn, session: Session = DB):
    s = get_settings(session)
    base = body.base_url.strip() or llm.PROVIDERS.get(body.provider, ("", ""))[1]
    key = body.key if body.key else (s.ai_key if body.provider == s.ai_provider else "")
    try:
        return {"models": llm.list_models(body.provider, base, key)}
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(400, f"Couldn't list models ({e.__class__.__name__}). Check the address and key.")


class AgentIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = []


@app.post("/api/agent")
async def run_agent(body: AgentIn):
    if not llm.available():
        raise HTTPException(503, "Atlas is off or not connected to an AI. Set it up in Setup.")
    try:
        return await agent.run(body.message, body.history)
    except llm.LLMError as e:
        raise HTTPException(503, str(e))


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    goal_id: int | None = None


@app.post("/api/chat")
async def chat(body: AskIn):
    return await planner.answer(body.question, body.goal_id)


STATIC = ROOT / "app" / "static"


@app.get("/", include_in_schema=False)
def index():
    # Stamp asset URLs with their last-modified time so browsers never run stale CSS/JS.
    version = int(max(f.stat().st_mtime for f in STATIC.iterdir() if f.is_file()))
    html = (STATIC / "index.html").read_text().replace("{{v}}", str(version))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _404():
    raise HTTPException(404, "Not found")


app.mount("/", StaticFiles(directory=STATIC), name="static")
