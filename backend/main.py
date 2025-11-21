from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from task_engine import PangGuaiRunner, RunOptions


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
EXECUTOR = ThreadPoolExecutor(max_workers=20)
LOG_SUBSCRIBERS: dict[int, set[WebSocket]] = {}
LOG_HISTORY: dict[int, list[str]] = {}
LOG_LOCK = Lock()
PASSWORD_SALT = os.getenv("PANGGUAI_PASSWORD_SALT", "pangguai_salt_v1")
ACTIVE_RUNNERS: dict[str, PangGuaiRunner] = {}


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expire_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                ua_mode TEXT NOT NULL,
                ua TEXT,
                token TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        # Minimal schema evolution (avoid new entities)
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        column_additions = {
            "phone": "ALTER TABLE users ADD COLUMN phone TEXT",
            "token": "ALTER TABLE users ADD COLUMN token TEXT",
            "ua": "ALTER TABLE users ADD COLUMN ua TEXT",
            "nick": "ALTER TABLE users ADD COLUMN nick TEXT",
            "integral_balance": "ALTER TABLE users ADD COLUMN integral_balance INTEGER DEFAULT 0",
            "status": "ALTER TABLE users ADD COLUMN status INTEGER DEFAULT 1",
            "last_run_time": "ALTER TABLE users ADD COLUMN last_run_time INTEGER",
            "updated_at": "ALTER TABLE users ADD COLUMN updated_at INTEGER",
        }
        for name, ddl in column_additions.items():
            if name not in user_columns:
                conn.execute(ddl)

        # Ensure phone is unique when possible; ignore failures if legacy duplicates exist
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")
        except sqlite3.OperationalError:
            pass

        task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "options" not in task_columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN options TEXT")
    conn.commit()


def hash_password(password: str) -> str:
    return hashlib.sha256((password + PASSWORD_SALT).encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    """Allow legacy unsalted hashes for existing users while migrating to salted hashes."""
    new_hash = hash_password(password)
    if new_hash == stored_hash:
        return True
    legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return legacy_hash == stored_hash


def create_session(user_id: int, ttl_seconds: int = 60 * 60 * 4) -> str:
    token = str(uuid.uuid4())
    now = int(time.time())
    expire_at = now + ttl_seconds
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expire_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, expire_at, now),
        )
        conn.commit()
    return token


def get_user_by_token(auth_header: Optional[str]) -> sqlite3.Row:
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    # Support "Bearer <token>" or raw token
    parts = auth_header.split()
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else parts[0]
    now = int(time.time())
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT users.id AS id, users.username AS username
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expire_at > ?
            """,
            (token, now),
        )
        user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return user


def push_log(user_id: int, message: str) -> None:
    """Append a log line and fan out to subscribers."""
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    with LOG_LOCK:
        history = LOG_HISTORY.setdefault(user_id, [])
        history.append(line)
        if len(history) > 200:
            history.pop(0)
        subscribers = list(LOG_SUBSCRIBERS.get(user_id, set()))
    if not subscribers or MAIN_LOOP is None:
        return
    for ws in subscribers:
        try:
            asyncio.run_coroutine_threadsafe(ws.send_text(line), MAIN_LOOP)
        except RuntimeError:
            # likely closed, drop silently to avoid noisy errors
            continue


def get_user_row(user_id: int) -> sqlite3.Row:
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    return row


class RegisterForm(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class LoginForm(BaseModel):
    username: str
    password: str


class TaskCreate(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$", description="手机号")
    ua_mode: str = Field("auto", description="auto|custom")
    ua_value: Optional[str] = None


class LoginReport(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$")
    token: str
    ua: str


class UserStatus(BaseModel):
    nick: Optional[str]
    integral: int
    task_status: str


class TaskOptions(BaseModel):
    video: bool = True
    alipay: bool = True


class TaskResponse(BaseModel):
    id: str
    phone: str
    ua_mode: str
    ua: Optional[str]
    token: Optional[str]
    status: str
    error: Optional[str]
    created_at: int
    updated_at: int


app = FastAPI(title="PangGuai Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_event_loop()
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/register")
def register(body: RegisterForm) -> dict:
    now = int(time.time())
    password_hash = hash_password(body.password)
    with get_db_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (body.username, password_hash, now),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=400, detail="用户名已存在") from exc
    return {"message": "ok"}


@app.post("/auth/login")
def login(body: LoginForm) -> dict:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?", (body.username,),
        )
        row = cursor.fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    session_token = create_session(user_id=row["id"])
    return {"token": session_token, "user_id": row["id"]}


@app.post("/api/login")
def api_login(body: LoginReport) -> dict:
    """前端上报 phone + token + ua，返回 uid + 会话令牌，并同步积分。"""
    now = int(time.time())

    # 同步查询当前积分与昵称，提升前端反馈
    temp_runner = PangGuaiRunner(token=body.token, ua=body.ua)
    current_integral = 0
    current_nick = None
    try:
        current_integral = temp_runner.balance()
        current_nick = temp_runner.get_username()
    except Exception:
        pass  # 查询失败不阻断登录

    with get_db_connection() as conn:
        cursor = conn.execute("SELECT id FROM users WHERE phone = ?", (body.phone,))
        row = cursor.fetchone()
        if row:
            user_id = row["id"]
            conn.execute(
                """
                UPDATE users
                SET token = ?, ua = ?, status = 1, updated_at = ?, last_run_time = last_run_time,
                    integral_balance = COALESCE(?, integral_balance), nick = COALESCE(?, nick)
                WHERE id = ?
                """,
                (body.token, body.ua, now, current_integral, current_nick, user_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at, phone, token, ua, status, updated_at, integral_balance, nick)
                VALUES (?, '', ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (body.phone, now, body.phone, body.token, body.ua, now, current_integral, current_nick),
            )
            user_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()
    session_token = create_session(user_id=user_id)
    return {"code": 200, "msg": "Login Success", "data": {"uid": user_id, "session_token": session_token}}


def require_user(authorization: Optional[str] = Header(None)) -> sqlite3.Row:
    return get_user_by_token(authorization)


def current_task_status(user_id: int) -> str:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT status FROM tasks WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
    return row["status"] if row else "idle"


@app.get("/api/user/status", response_model=UserStatus)
def user_status(user=Depends(require_user)) -> UserStatus:
    row = get_user_row(user["id"])
    task_state = current_task_status(user["id"])
    return UserStatus(
        nick=row["nick"],
        integral=row["integral_balance"] or 0,
        task_status=task_state,
    )


@app.post("/tasks", response_model=TaskResponse)
def create_task(
    body: TaskCreate,
    user=Depends(require_user),
) -> TaskResponse:
    task_id = str(uuid.uuid4())
    now = int(time.time())
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO tasks (id, user_id, phone, ua_mode, ua, token, status, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, NULL, 'pending', NULL, ?, ?)
            """,
            (task_id, user["id"], body.phone, body.ua_mode, now, now),
        )
        conn.commit()
    EXECUTOR.submit(run_task_job, task_id, user["id"])
    return fetch_task(task_id, user["id"])


@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks(user=Depends(require_user)) -> list[TaskResponse]:
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, phone, ua_mode, ua, token, status, error, created_at, updated_at
            FROM tasks WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user["id"],),
        )
        tasks = [dict(row) for row in cursor.fetchall()]
    return tasks  # type: ignore[return-value]


@app.post("/api/task/start", response_model=TaskResponse)
def api_task_start(
    options: TaskOptions,
    user=Depends(require_user),
) -> TaskResponse:
    if current_task_status(user["id"]) == "running":
        raise HTTPException(status_code=400, detail="任务正在运行中，请勿重复提交")
    user_row = get_user_row(user["id"])
    if not user_row["token"] or not user_row["phone"]:
        raise HTTPException(status_code=400, detail="缺少 token 或手机号，请重新登录后重试")
    now = int(time.time())
    start_of_day = now - (now % 86400)
    three_days_ago = now - (3 * 86400)
    options_json = json.dumps(options.dict())
    task_id: str
    with get_db_connection() as conn:
        conn.execute("DELETE FROM tasks WHERE user_id = ? AND created_at < ?", (user["id"], three_days_ago))
        cursor = conn.execute(
            """
            SELECT id FROM tasks
            WHERE user_id = ? AND created_at >= ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user["id"], start_of_day),
        )
        existing = cursor.fetchone()
        if existing:
            task_id = existing["id"]
            conn.execute(
                """
                UPDATE tasks
                SET phone = ?, ua_mode = 'custom', ua = ?, token = ?, status = 'pending',
                    error = NULL, options = ?, created_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    user_row["phone"],
                    user_row["ua"],
                    user_row["token"],
                    options_json,
                    now,
                    now,
                    task_id,
                    user["id"],
                ),
            )
        else:
            task_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO tasks (id, user_id, phone, ua_mode, ua, token, status, error, options, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?, ?)
                """,
                (
                    task_id,
                    user["id"],
                    user_row["phone"],
                    "custom",
                    user_row["ua"],
                    user_row["token"],
                    options_json,
                    now,
                    now,
                ),
            )
        conn.commit()
    EXECUTOR.submit(run_task_job, task_id, user["id"])
    return fetch_task(task_id, user["id"])


@app.post("/api/task/stop")
def api_task_stop(user=Depends(require_user)) -> dict:
    """停止当前用户正在运行的任务。"""
    user_id = user["id"]
    stopped = 0
    now = int(time.time())
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT id FROM tasks WHERE user_id = ? AND status IN ('running', 'pending')",
            (user_id,),
        )
        rows = cursor.fetchall()
        for row in rows:
            task_id = row["id"]
            if task_id in ACTIVE_RUNNERS:
                ACTIVE_RUNNERS[task_id].stop()
                stopped += 1
            conn.execute(
                "UPDATE tasks SET status = 'failed', error = '用户手动停止', updated_at = ? WHERE id = ?",
                (now, task_id),
            )
        conn.commit()
    return {"code": 200, "msg": "任务停止指令已发送" if stopped else "当前没有运行中的任务"}


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, user=Depends(require_user)) -> TaskResponse:
    return fetch_task(task_id, user["id"])


@app.post("/tasks/{task_id}/retry", response_model=TaskResponse)
def retry_task(
    task_id: str,
    user=Depends(require_user),
) -> TaskResponse:
    now = int(time.time())
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT id, phone, ua_mode FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user["id"]),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        conn.execute(
            """
            UPDATE tasks
            SET status = 'pending', error = NULL, token = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now, task_id),
        )
        conn.commit()
    EXECUTOR.submit(run_task_job, task_id, user["id"])
    return fetch_task(task_id, user["id"])


def run_task_job(task_id: str, user_id: int) -> None:
    """运行长任务：读取任务记录 + 用户 token/UA，执行脚本，推送日志。"""
    push_log(user_id, f"任务 {task_id} 开始执行")
    now = int(time.time())
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE tasks SET status = 'running', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        conn.commit()
        # 获取任务配置
        cursor = conn.execute(
            "SELECT phone, ua, token, options FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
        task_row = cursor.fetchone()
    if not task_row:
        push_log(user_id, "任务不存在，终止")
        return

    if not task_row["token"] or not task_row["ua"]:
        fail_task(task_id, user_id, "缺少 token 或 UA")
        return

    opts_dict = {}
    if task_row["options"]:
        try:
            opts_dict = json.loads(task_row["options"])
        except json.JSONDecodeError:
            opts_dict = {}
    options = RunOptions(**opts_dict)

    runner = PangGuaiRunner(
        token=task_row["token"],
        ua=task_row["ua"],
        options=options,
        logger=lambda msg: push_log(user_id, msg),
    )
    ACTIVE_RUNNERS[task_id] = runner

    try:
        result = runner.run()
        now = int(time.time())
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'done', ua = ?, token = ?, error = NULL, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (task_row["ua"], task_row["token"], now, task_id, user_id),
            )
            conn.execute(
                """
                UPDATE users
                SET integral_balance = ?, nick = COALESCE(nick, ?), last_run_time = ?
                WHERE id = ?
                """,
                (result.get("integral", 0), result.get("username"), now, user_id),
            )
            conn.commit()
        push_log(user_id, f"任务 {task_id} 完成，今日收益 {result.get('gain', 0)}")
    except Exception as exc:  # pragma: no cover - defensive log
        if isinstance(exc, InterruptedError):
            push_log(user_id, "任务已被用户停止")
        else:
            fail_task(task_id, user_id, str(exc))
    finally:
        ACTIVE_RUNNERS.pop(task_id, None)


def fail_task(task_id: str, user_id: int, message: str) -> None:
    now = int(time.time())
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = 'failed', error = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (message, now, task_id, user_id),
        )
        conn.commit()
    push_log(user_id, f"任务 {task_id} 失败：{message}")


def fetch_task(task_id: str, user_id: int) -> TaskResponse:
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, phone, ua_mode, ua, token, status, error, created_at, updated_at
            FROM tasks WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id),
        )
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskResponse(**dict(row))


@app.websocket("/ws/logs/{uid}")
async def ws_logs(uid: int, websocket: WebSocket) -> None:
    await websocket.accept()
    with LOG_LOCK:
        LOG_SUBSCRIBERS.setdefault(uid, set()).add(websocket)
        history = LOG_HISTORY.get(uid, [])
    for line in history[-50:]:
        await websocket.send_text(line)
    try:
        while True:
            # keep alive / ignore messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        with LOG_LOCK:
            LOG_SUBSCRIBERS.get(uid, set()).discard(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
