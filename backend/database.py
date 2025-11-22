# --- database.py ---
import aiosqlite
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"

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
                nick TEXT,
                integral_balance INTEGER DEFAULT 0,
                status INTEGER DEFAULT 1,
                last_run_time INTEGER,
                updated_at INTEGER
            )
        """)
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
async def fetch_user_by_token(token: str):
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT users.* 
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expire_at > ?
            """,
            (token, now),
        )
        return await cursor.fetchone()

async def update_task_status(task_id: str, status: str, error: str = None):
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, now, task_id)
        )
        await db.commit()

async def update_user_balance(user_id: int, integral: int, nick: str = None):
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE users 
            SET integral_balance = ?, nick = COALESCE(?, nick), last_run_time = ? 
            WHERE id = ?
            """,
            (integral, nick, now, user_id)
        )
        await db.commit()