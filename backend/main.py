# --- main.py ---
from __future__ import annotations
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from database import (
    init_db, get_db, fetch_user_by_token, 
    DB_PATH
)
import aiosqlite
from models import (
    RegisterForm, LoginForm, LoginReport, TaskCreate, 
    TaskOptions, TaskResponse, UserStatus, RunConfig
)
from core.utils import hash_password, verify_password, normalize_ua
from manager import TaskManager

app = FastAPI(title="PangGuai Async Backend", version="2.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

task_manager = TaskManager()

@app.on_event("startup")
async def startup_event():
    await init_db()

@app.get("/health")
def health():
    return {"status": "ok", "mode": "async"}

# --- 认证相关 ---

@app.post("/auth/register")
async def register(body: RegisterForm, db: aiosqlite.Connection = Depends(get_db)):
    now = int(time.time())
    pwd_hash = hash_password(body.password)
    try:
        await db.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (body.username, pwd_hash, now)
        )
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(400, "用户名已存在")
    return {"message": "ok"}

@app.post("/auth/login")
async def login(body: LoginForm, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT id, password_hash FROM users WHERE username = ?", (body.username,))
    row = await cursor.fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "用户名密码错误")
    
    token = str(uuid.uuid4())
    now = int(time.time())
    await db.execute(
        "INSERT INTO sessions (token, user_id, expire_at, created_at) VALUES (?, ?, ?, ?)",
        (token, row["id"], now + 14400, now)
    )
    await db.commit()
    return {"token": token, "user_id": row["id"]}

async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(401, "Missing Token")
    parts = authorization.split()
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else parts[0]
    user = await fetch_user_by_token(token)
    if not user:
        raise HTTPException(401, "Invalid Token")
    return user

# --- 业务 API ---

@app.post("/api/login")
async def api_login(body: LoginReport, db: aiosqlite.Connection = Depends(get_db)):
    """App 扫码/验证码登录上报"""
    now = int(time.time())
    
    # 1. 查旧数据
    cursor = await db.execute("SELECT id, ua FROM users WHERE phone = ?", (body.phone,))
    row = await cursor.fetchone()
    
    # 2. UA 处理
    final_ua = normalize_ua(body.ua)
    if row and row["ua"] and "android" in row["ua"].lower():
        # 如果老用户已经有安卓 UA，尽量保持
        final_ua = row["ua"]
    
    user_id = None
    if row:
        user_id = row["id"]
        await db.execute(
            """
            UPDATE users 
            SET token = ?, ua = ?, status = 1, updated_at = ? 
            WHERE id = ?
            """,
            (body.token, final_ua, now, user_id)
        )
    else:
        await db.execute(
            """
            INSERT INTO users (username, password_hash, created_at, phone, token, ua, status, updated_at)
            VALUES (?, '', ?, ?, ?, ?, 1, ?)
            """,
            (body.phone, now, body.phone, body.token, final_ua, now)
        )
        user_id = (await db.execute("SELECT last_insert_rowid()")).lastrowid

    # 创建 Session
    session_token = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO sessions (token, user_id, expire_at, created_at) VALUES (?, ?, ?, ?)",
        (session_token, user_id, now + 14400, now)
    )
    await db.commit()
    
    return {"code": 200, "msg": "Login Success", "data": {"uid": user_id, "session_token": session_token}}

@app.get("/api/user/status", response_model=UserStatus)
async def user_status(user = Depends(get_current_user), db: aiosqlite.Connection = Depends(get_db)):
    # 查最新任务状态
    cursor = await db.execute(
        "SELECT status FROM tasks WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1", 
        (user["id"],)
    )
    task_row = await cursor.fetchone()
    t_status = task_row["status"] if task_row else "idle"
    
    # 如果内存中正在跑，强制覆盖状态（防止数据库未及时更新）
    if task_manager.get_handle(user["id"]):
        t_status = "running"

    return UserStatus(
        nick=user["nick"],
        integral=user["integral_balance"] or 0,
        task_status=t_status
    )

@app.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(user = Depends(get_current_user), db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC", (user["id"],))
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]

@app.post("/api/task/start", response_model=TaskResponse)
async def start_task_endpoint(
    options: TaskOptions,
    user = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db)
):
    if task_manager.get_handle(user["id"]):
        raise HTTPException(400, "任务已在运行中")

    if not user["token"] or not user["phone"]:
        raise HTTPException(400, "用户信息缺失，请重新登录")

    now = int(time.time())
    start_of_day = now - (now % 86400)
    
    # 查找今日任务复用，或新建
    cursor = await db.execute(
        "SELECT * FROM tasks WHERE user_id = ? AND created_at >= ? ORDER BY updated_at DESC LIMIT 1",
        (user["id"], start_of_day)
    )
    existing = await cursor.fetchone()
    
    options_json = json.dumps(options.dict())
    
    if existing:
        task_id = existing["id"]
        await db.execute(
            """
            UPDATE tasks 
            SET status = 'pending', error = NULL, options = ?, updated_at = ?, token = ?, ua = ?
            WHERE id = ?
            """,
            (options_json, now, user["token"], user["ua"], task_id)
        )
    else:
        task_id = str(uuid.uuid4())
        await db.execute(
            """
            INSERT INTO tasks (id, user_id, phone, ua_mode, ua, token, status, error, options, created_at, updated_at)
            VALUES (?, ?, ?, 'custom', ?, ?, 'pending', NULL, ?, ?, ?)
            """,
            (task_id, user["id"], user["phone"], user["ua"], user["token"], options_json, now, now)
        )
    
    await db.commit()
    
    # 启动异步任务
    config = RunConfig(token=user["token"], ua=user["ua"], options=options)
    await task_manager.start_task(user["id"], task_id, config)
    
    # 返回最新状态
    cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    return dict(row)

@app.post("/api/task/stop")
async def stop_task_endpoint(user = Depends(get_current_user)):
    success = await task_manager.stop_task(user["id"])
    return {"code": 200, "msg": "停止指令已发送" if success else "无运行中任务"}

@app.websocket("/ws/logs/{uid}")
async def ws_logs_endpoint(uid: int, websocket: WebSocket):
    await task_manager.subscribe_logs(uid, websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)