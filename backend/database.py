# --- database.py ---
import aiosqlite
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"
TOKEN_VALID_SECONDS = 30 * 24 * 60 * 60

async def get_db():
    """FastAPI 依赖使用的生成器"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db

async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL;")
        # 用户表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                phone TEXT UNIQUE,
                token TEXT,
                ua TEXT,
                device_id TEXT,
                nick TEXT,
                integral_balance INTEGER DEFAULT 0,
                status INTEGER DEFAULT 1,
                last_run_time INTEGER,
                updated_at INTEGER
            )
        """)
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN device_id TEXT")
        except aiosqlite.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
        # 会话表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expire_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        # 任务表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                ua_mode TEXT NOT NULL,
                ua TEXT,
                token TEXT,
                status TEXT NOT NULL,
                error TEXT,
                options TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        # 索引
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)")
        await conn.commit()

# 便捷函数
async def fetch_user_by_token(db: aiosqlite.Connection, token: str):
    now = int(time.time())
    valid_since = now - TOKEN_VALID_SECONDS
    cursor = await db.execute(
        """
        SELECT users.* 
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ? AND sessions.expire_at > ?
        """,
        (token, now),
    )
    user = await cursor.fetchone()
    if not user:
        return None

    # Token 30 天有效期校验：仅对手机号/托管用户生效
    if user["phone"]:
        last_update = user["updated_at"] or 0
        expired = (
            not user["token"] 
            or last_update < valid_since 
            or (user["status"] is not None and user["status"] <= 0)
        )
        if expired:
            await db.execute(
                "UPDATE users SET token = NULL, status = 0, updated_at = ? WHERE id = ?",
                (now, user["id"])
            )
            await db.commit()
            return None
    return user

async def update_task_status(task_id: str, status: str, error: str = None, db: Optional[aiosqlite.Connection] = None):
    now = int(time.time())
    owns_conn = db is None
    if owns_conn:
        db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(
            "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, now, task_id)
        )
        await db.commit()
    finally:
        if owns_conn and db:
            await db.close()

async def update_user_balance(user_id: int, integral: int, nick: str = None, db: Optional[aiosqlite.Connection] = None):
    now = int(time.time())
    owns_conn = db is None
    if owns_conn:
        db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(
            """
            UPDATE users 
            SET integral_balance = ?, nick = COALESCE(?, nick), last_run_time = ? 
            WHERE id = ?
            """,
            (integral, nick, now, user_id)
        )
        await db.commit()
    finally:
        if owns_conn and db:
            await db.close()
