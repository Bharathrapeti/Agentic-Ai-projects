"""SQLite persistence for the Interview Coach.

The database is deliberately small and dependency-free.  Every write is
committed immediately so a browser refresh does not lose completed answers.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).with_name("interview_coach.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(path: Path | str = DB_PATH) -> None:
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interview_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(user_id),
                job_role TEXT NOT NULL,
                skill_level TEXT NOT NULL,
                interview_type TEXT NOT NULL,
                topics TEXT NOT NULL DEFAULT '',
                number_of_questions INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                overall_score REAL,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS questions (
                question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES interview_sessions(session_id) ON DELETE CASCADE,
                question_number INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                UNIQUE(session_id, question_number)
            );
            CREATE TABLE IF NOT EXISTS answers (
                answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL UNIQUE REFERENCES questions(question_id) ON DELETE CASCADE,
                answer_text TEXT NOT NULL,
                score REAL NOT NULL,
                feedback TEXT NOT NULL,
                suggestion TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS performance (
                performance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL UNIQUE REFERENCES interview_sessions(session_id) ON DELETE CASCADE,
                strengths TEXT NOT NULL,
                weaknesses TEXT NOT NULL,
                recommendations TEXT NOT NULL,
                overall_score REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "created_at" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        # Migrate starter databases without breaking existing data.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(interview_sessions)")}
        for name, definition in (
            ("topics", "TEXT NOT NULL DEFAULT ''"),
            ("created_at", "TEXT"),
            ("completed_at", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
        ):
            if name not in columns:
                db.execute(f"ALTER TABLE interview_sessions ADD COLUMN {name} {definition}")
        answer_columns = {row["name"] for row in db.execute("PRAGMA table_info(answers)")}
        if "created_at" not in answer_columns:
            db.execute("ALTER TABLE answers ADD COLUMN created_at TEXT")
        performance_columns = {row["name"] for row in db.execute("PRAGMA table_info(performance)")}
        if "created_at" not in performance_columns:
            db.execute("ALTER TABLE performance ADD COLUMN created_at TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_answers_question ON answers(question_id)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_performance_session ON performance(session_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_created ON interview_sessions(created_at DESC)")


def get_or_create_user(name: str, path: Path | str = DB_PATH) -> int:
    with connect(path) as db:
        normalized_name = name.strip()
        existing = db.execute("SELECT user_id FROM users WHERE name = ? ORDER BY user_id LIMIT 1", (normalized_name,)).fetchone()
        if existing:
            return int(existing["user_id"])
        cursor = db.execute("INSERT INTO users(name, created_at) VALUES (?, ?)", (normalized_name, _now()))
        return int(cursor.lastrowid)


def create_session(user_id: int, job_role: str, skill_level: str, interview_type: str,
                   question_count: int, topics: list[str] | None = None,
                   path: Path | str = DB_PATH) -> int:
    # Preserve the old positional ``path`` argument used by integrations.
    if isinstance(topics, (str, Path)) and path == DB_PATH:
        path, topics = topics, None
    with connect(path) as db:
        cursor = db.execute(
            """INSERT INTO interview_sessions
            (user_id, job_role, skill_level, interview_type, number_of_questions, topics, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, job_role, skill_level, interview_type, question_count,
             json.dumps(topics or []), _now()),
        )
        return int(cursor.lastrowid)


def save_questions(session_id: int, questions: list[str], path: Path | str = DB_PATH) -> None:
    with connect(path) as db:
        db.executemany(
            "INSERT OR IGNORE INTO questions(session_id, question_number, question_text) VALUES (?, ?, ?)",
            [(session_id, index, text) for index, text in enumerate(questions, 1)],
        )


def save_question(session_id: int, question: str, path: Path | str = DB_PATH) -> int:
    with connect(path) as db:
        next_number = db.execute(
            "SELECT COALESCE(MAX(question_number), 0) + 1 FROM questions WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        cursor = db.execute(
            "INSERT INTO questions(session_id, question_number, question_text) VALUES (?, ?, ?)",
            (session_id, next_number, question),
        )
        return int(cursor.lastrowid)


def prior_questions(user_id: int, limit: int = 250, path: Path | str = DB_PATH) -> list[str]:
    with connect(path) as db:
        rows = db.execute(
            """SELECT q.question_text FROM questions q
            JOIN interview_sessions s ON s.session_id=q.session_id
            WHERE s.user_id=? ORDER BY q.question_id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [row["question_text"] for row in rows]


def get_questions(session_id: int, path: Path | str = DB_PATH) -> list[sqlite3.Row]:
    with connect(path) as db:
        return db.execute("SELECT * FROM questions WHERE session_id = ? ORDER BY question_number", (session_id,)).fetchall()


def save_answer(question_id: int, answer: dict[str, Any], path: Path | str = DB_PATH) -> None:
    with connect(path) as db:
        db.execute("DELETE FROM answers WHERE question_id = ?", (question_id,))
        db.execute(
            """INSERT INTO answers(question_id, answer_text, score, feedback, suggestion, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (question_id, answer["answer"], float(answer["score"]), answer["feedback"],
             answer["suggestion"], _now()),
        )


def finish_session(session_id: int, report: dict[str, Any], path: Path | str = DB_PATH) -> None:
    with connect(path) as db:
        db.execute(
            "UPDATE interview_sessions SET status='completed', completed_at=?, overall_score=? WHERE session_id=?",
            (_now(), float(report["overall_score"]), session_id),
        )
        db.execute("DELETE FROM performance WHERE session_id = ?", (session_id,))
        db.execute(
            """INSERT INTO performance(session_id, strengths, weaknesses, recommendations, overall_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, json.dumps(report["strengths"]), json.dumps(report["weaknesses"]),
             json.dumps(report["recommendations"]), float(report["overall_score"]), _now()),
        )


def history(limit: int = 10, path: Path | str = DB_PATH) -> list[sqlite3.Row]:
    with connect(path) as db:
        return db.execute(
            """SELECT s.*, u.name FROM interview_sessions s JOIN users u ON u.user_id=s.user_id
            WHERE s.status='completed' ORDER BY s.created_at DESC LIMIT ?""", (limit,)
        ).fetchall()


def session_details(session_id: int, path: Path | str = DB_PATH) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
    with connect(path) as db:
        session = db.execute("SELECT * FROM interview_sessions WHERE session_id=?", (session_id,)).fetchone()
        rows = db.execute(
            """SELECT q.*, a.answer_text, a.score, a.feedback, a.suggestion
            FROM questions q LEFT JOIN answers a ON a.question_id=q.question_id
            WHERE q.session_id=? ORDER BY q.question_number""", (session_id,)
        ).fetchall()
        return session, rows
