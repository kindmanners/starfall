import os
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def get_db_connection():
    return psycopg2.connect(
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        cursor_factory=RealDictCursor,
    )


def initialize_schema() -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(schema)


def _one(query: str, params: tuple[Any, ...]):
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def get_user_by_email(email: str):
    return _one("SELECT * FROM users WHERE lower(email) = lower(%s)", (email,))


def get_user_by_username(username: str):
    return _one("SELECT * FROM users WHERE lower(username) = lower(%s)", (username,))


def get_user_by_id(user_id: int):
    return _one(
        "SELECT id, username, email, created_at FROM users WHERE id = %s",
        (user_id,),
    )


def create_user(username: str, email: str, password_hash: str) -> int:
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO users (username, email, hashed_password)
               VALUES (%s, lower(%s), %s) RETURNING id""",
            (username.strip(), email.strip(), password_hash),
        )
        return int(cur.fetchone()["id"])


def create_session(user_id: int, jti: str, expires_at) -> None:
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sessions (jti, user_id, expires_at)
               VALUES (%s, %s, %s)""",
            (jti, user_id, expires_at),
        )


def get_active_session(jti: str, user_id: int):
    return _one(
        """SELECT s.jti, s.expires_at, u.id, u.username, u.email, u.created_at
           FROM sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.jti = %s AND s.user_id = %s
             AND s.revoked_at IS NULL AND s.expires_at > CURRENT_TIMESTAMP""",
        (jti, user_id),
    )


def revoke_session(jti: str, user_id: int) -> bool:
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE sessions SET revoked_at = CURRENT_TIMESTAMP
               WHERE jti = %s AND user_id = %s AND revoked_at IS NULL
               RETURNING jti""",
            (jti, user_id),
        )
        return cur.fetchone() is not None


def revoke_all_sessions(user_id: int) -> list[str]:
    """Revoke every active device session, for example after a password change."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE sessions SET revoked_at = CURRENT_TIMESTAMP
               WHERE user_id = %s AND revoked_at IS NULL
               RETURNING jti::text""",
            (user_id,),
        )
        return [row["jti"] for row in cur.fetchall()]


def list_other_users(user_id: int) -> list[dict[str, Any]]:
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT u.id, u.username, MAX(m.created_at) AS last_message_at
               FROM users u
               LEFT JOIN messages m
                 ON (m.sender_id = u.id AND m.recipient_id = %s)
                 OR (m.sender_id = %s AND m.recipient_id = u.id)
               WHERE u.id <> %s
               GROUP BY u.id, u.username
               ORDER BY last_message_at DESC NULLS LAST, lower(u.username)""",
            (user_id, user_id, user_id),
        )
        return list(cur.fetchall())


def save_message(
    sender_id: int,
    recipient_id: int,
    content: str = "",
    *,
    file_name: str | None = None,
    file_key: str | None = None,
    file_size: int | None = None,
    file_mime: str | None = None,
):
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO messages
                   (sender_id, recipient_id, content, file_name, file_key, file_size, file_mime)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id, sender_id, recipient_id, content, file_name,
                         file_size, file_mime, created_at""",
            (sender_id, recipient_id, content, file_name, file_key, file_size, file_mime),
        )
        return cur.fetchone()


def get_conversation(user_id: int, other_id: int, limit: int = 200):
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT m.id, m.sender_id, m.recipient_id, m.content,
                      m.file_name, m.file_size, m.file_mime, m.created_at,
                      u.username AS sender_name
               FROM messages m
               JOIN users u ON u.id = m.sender_id
               WHERE (m.sender_id = %s AND m.recipient_id = %s)
                  OR (m.sender_id = %s AND m.recipient_id = %s)
               ORDER BY m.created_at DESC LIMIT %s""",
            (user_id, other_id, other_id, user_id, limit),
        )
        rows = list(cur.fetchall())
        rows.reverse()
        return rows


def get_message_file(message_id: int, user_id: int):
    return _one(
        """SELECT file_name, file_key, file_mime FROM messages
           WHERE id = %s AND file_key IS NOT NULL
             AND (sender_id = %s OR recipient_id = %s)""",
        (message_id, user_id, user_id),
    )
