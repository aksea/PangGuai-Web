# --- manager.py ---
import asyncio
import time
from pathlib import Path
from typing import Dict, Optional, Set
from fastapi import WebSocket
from core.runner import AsyncPangGuaiRunner
from models import RunConfig
from database import update_task_status, update_user_balance

class TaskHandle:
    def __init__(self, task: asyncio.Task, stop_event: asyncio.Event, log_path: Path):
        self.task = task
        self.stop_event = stop_event
        self.log_path = log_path
        self.ws_subscribers: Set[WebSocket] = set()
        self.log_history: list[str] = []

    async def broadcast_log(self, message: str):
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.log_history.append(line)
        if len(self.log_history) > 100:
            self.log_history.pop(0)
        
        # 1. 写文件
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

        # 2. WS 推送
        if not self.ws_subscribers:
            return
        
        to_remove = set()
        for ws in self.ws_subscribers:
            try:
                await ws.send_text(line)
            except Exception:
                to_remove.add(ws)
        
        for ws in to_remove:
            self.ws_subscribers.discard(ws)

class TaskManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.active_tasks = {}  # type: Dict[int, TaskHandle]
            cls._instance.log_dir = Path("logs")
            cls._instance.log_dir.mkdir(exist_ok=True)
        return cls._instance

    def get_handle(self, user_id: int) -> Optional[TaskHandle]:
        return self.active_tasks.get(user_id)

    async def start_task(self, user_id: int, task_id: str, config: RunConfig):
        if user_id in self.active_tasks:
            raise ValueError("Task already running")

        # 准备日志
        user_log_dir = self.log_dir / str(user_id)
        user_log_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        log_path = user_log_dir / f"{ts}_{task_id}.log"

        stop_event = asyncio.Event()
        
        # 创建 Handle 并预先放入字典 (为了让 log 立即生效)
        handle = TaskHandle(None, stop_event, log_path) # Task 稍后填入
        self.active_tasks[user_id] = handle

        async def _runner_wrapper():
            try:
                runner = AsyncPangGuaiRunner(
                    config=config, 
                    log_func=lambda msg: asyncio.create_task(handle.broadcast_log(msg)),
                    stop_event=stop_event
                )
                await update_task_status(task_id, "running")
                await handle.broadcast_log(f"任务 {task_id} 启动")
                
                result = await runner.run()
                
                # 成功完成
                await update_task_status(task_id, "done")
                await update_user_balance(user_id, result.get("integral", 0), result.get("username"))
            
            except InterruptedError:
                await update_task_status(task_id, "failed", "用户停止")
                await handle.broadcast_log("任务已被用户停止")
            except asyncio.CancelledError:
                await update_task_status(task_id, "failed", "用户停止")
                await handle.broadcast_log("任务已被用户停止")
                raise
            except Exception as e:
                import traceback
                traceback.print_exc()
                await update_task_status(task_id, "failed", str(e))
                await handle.broadcast_log(f"异常退出: {e}")
            finally:
                # 清理
                if user_id in self.active_tasks and self.active_tasks[user_id] == handle:
                    del self.active_tasks[user_id]

        # 真正的启动
        async_task = asyncio.create_task(_runner_wrapper())
        handle.task = async_task
        return log_path

    async def stop_task(self, user_id: int):
        handle = self.active_tasks.get(user_id)
        if handle:
            handle.stop_event.set()
            # 等待一小会确保它收到
            await handle.broadcast_log("正在停止...")
            if handle.task and not handle.task.done():
                try:
                    handle.task.cancel()
                    await asyncio.wait_for(handle.task, timeout=5)
                except Exception:
                    pass
            return True
        return False

    async def subscribe_logs(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        current_handle = None

        async def attach_handle():
            nonlocal current_handle
            new_handle = self.active_tasks.get(user_id)
            if new_handle and new_handle is not current_handle:
                current_handle = new_handle
                new_handle.ws_subscribers.add(websocket)
                for line in new_handle.log_history:
                    await websocket.send_text(line)

        # 初始检查
        await attach_handle()
        if current_handle is None:
            await websocket.send_text("[System] 当前无运行中任务")

        try:
            while True:
                # 周期性附加到新任务并保持连接
                await attach_handle()
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=3)
                except asyncio.TimeoutError:
                    continue
        except Exception:
            if current_handle:
                current_handle.ws_subscribers.discard(websocket)
