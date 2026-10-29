from datetime import date, datetime
from typing import Any

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column
from sqlalchemy import inspect, text
from sqlmodel import Field, Session, SQLModel, create_engine

from app.config import DATA_DIR


class Settings(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    daily_minutes: int = 120
    session_minutes: int = 45
    day_start: str = "18:00"
    use_ai: bool = True
    ai_provider: str = ""  # empty = auto-detect; otherwise an id from llm.PROVIDERS
    ai_base_url: str = ""
    ai_model: str = ""
    ai_key: str = ""  # stays on this machine; never sent to the browser
    name: str = ""  # empty until the welcome screen is completed
    gender: str = ""  # boy | girl | other (picks the avatar)
    warnings: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class Goal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    deadline: date
    due_time: str = ""  # optional HH:MM; without it the quest is due at the start of the deadline day


class Document(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    filename: str
    n_chunks: int = 0


class Topic(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    position: int
    name: str
    summary: str = ""
    difficulty: int = 3
    est_hours: float = 1.0
    done: bool = False
    sources: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))


class StudySession(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    topic_id: int = Field(foreign_key="topic.id")
    kind: str  # learn | review
    start: NaiveDatetime
    end: NaiveDatetime
    done: bool = False
    pinned: bool = False  # time chosen by the student; rebuilds keep it


engine = create_engine(f"sqlite:///{DATA_DIR / 'app.db'}", connect_args={"check_same_thread": False})


# Columns added after the first release; older databases get them on startup.
NEW_COLUMNS = {
    "settings": {"use_ai": "BOOLEAN NOT NULL DEFAULT 1", "name": "VARCHAR NOT NULL DEFAULT ''",
                 "gender": "VARCHAR NOT NULL DEFAULT ''",
                 "ai_provider": "VARCHAR NOT NULL DEFAULT ''", "ai_base_url": "VARCHAR NOT NULL DEFAULT ''",
                 "ai_model": "VARCHAR NOT NULL DEFAULT ''", "ai_key": "VARCHAR NOT NULL DEFAULT ''"},
    "topic": {"done": "BOOLEAN NOT NULL DEFAULT 0"},
    "studysession": {"pinned": "BOOLEAN NOT NULL DEFAULT 0"},
    "goal": {"due_time": "VARCHAR NOT NULL DEFAULT ''"},
}


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        for table, columns in NEW_COLUMNS.items():
            existing = {c["name"] for c in inspect(conn).get_columns(table)}
            for name, sql in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql}"))


def get_session():
    with Session(engine) as session:
        yield session


def get_settings(session: Session) -> Settings:
    s = session.get(Settings, 1)
    if not s:
        s = Settings(id=1)
        session.add(s)
        session.commit()
        session.refresh(s)
    return s
