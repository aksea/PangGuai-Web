# PangGuai-Web

基于 FastAPI 的任务托管后端与静态控制台前端。后端负责锁定设备指纹（UA + DeviceID）、管理手机号 Token、调度任务；前端提供登录/任务控制与日志查看。

## 目录结构
- backend/：FastAPI 服务、任务调度与设备指纹逻辑（使用 aiosqlite/httpx）。
- frontend/：纯静态页面（index.html、dashboard.html 等），通过 `API_BASE` 与后端交互。
- reference/：示例与历史文件（已被 .gitignore 覆盖，不参与开发）。

## 快速开始（开发）
1) 准备环境：Python 3.10+，Node 非必需（前端为静态文件）。
2) 安装依赖（示例）：
   ```bash
   cd backend
   pip install fastapi uvicorn[standard] httpx aiosqlite pydantic
   ```
3) 运行后端：
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```
   首次启动会自动初始化 SQLite（backend/database.db），按当前表结构创建。
4) 打开前端：
   - 直接用浏览器打开 `frontend/index.html`，或用任意静态服务器。
   - 如需自定义后端地址，在页面注入 `window.PANGGUAI_API_BASE = "http://your-api";`。

## 核心行为提示
- 登录/上报：后端完全忽略前端 UA，自动生成并绑定随机 UA + DeviceID，老用户仅在缺失时补全，不会覆盖已绑定指纹。
- 任务策略：Runner 仅执行类型 604/605/606，敏感词过滤（认证/绑卡/充值/开通/办卡/上传/完善），支付宝隐藏任务 taskCode=9 独立执行；连续无奖励会跳过以减少无效循环。
- 积分同步：`/api/user/status?refresh=1` 在无运行任务时会请求官方接口刷新积分并写回数据库；前端在任务结束后自动触发一次刷新。

## 常用接口
- POST `/api/login`：手机号+Token 上报并绑定指纹。
- POST `/api/task/start`：按当前用户绑定指纹启动任务。
- POST `/api/task/stop`：停止当前任务。
- GET `/api/user/status`：查询积分与任务状态（可选 `refresh=1`）。
- WS `/ws/logs/{uid}`：实时查看任务日志。

## 开发提示
- 请勿提交数据库、日志、reference 目录及 AGENTS.md；.gitignore 已覆盖，若误追踪可 `git rm --cached` 清理索引。
- 默认数据库路径 `backend/database.db`，若需要隔离环境，可在同目录下替换文件或调整代码路径。
