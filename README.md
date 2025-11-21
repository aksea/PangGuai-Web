# PangGuai-Web

一个将原有胖乖脚本封装为 Web SaaS 的示例项目：FastAPI 后端 + 前端登录/控制台，`reference/` 留存旧脚本以供对照。

## 目录结构

```
PangGuai-Web/
├── backend/
│   ├── main.py            # FastAPI 入口，提供登录/任务 API
│   ├── task_engine.py     # 任务执行器（封装胖乖脚本为类，含日志回调）
│   ├── database.db        # SQLite 数据库（运行时会自动建表）
│   └── requirements.txt
├── frontend/
│   ├── index.html         # 短信验证码登录页（自动获取 Token 并上报）
│   ├── dashboard.html     # 控制台（启动任务、停止任务、实时日志）
│   ├── app.js             # 前端逻辑与 API 调用（含 reportTokenLogin 钩子）
│   ├── style.css          # “Clean SaaS” 样式
│   └── assets/            # 静态资源占位
└── reference/             # 旧代码备份（未改动）
```

## 快速开始

1. 进入目录并创建虚拟环境（可选）：

```bash
cd PangGuai-Web
python -m venv .venv && source .venv/bin/activate
```

2. 安装依赖：

```bash
pip install -r backend/requirements.txt
```

3. 启动后端：

```bash
cd backend
uvicorn main:app --reload --port 8000
```

4. 启动前端（任意静态服务器即可，例如）：

```bash
cd ../frontend
python -m http.server 5500
```

浏览器打开 `http://localhost:5500/index.html`。

## 登录 & 认证

- 短信验证码登录后，前端会调用内置的加密脚本获取 Token，并通过 `window.reportTokenLogin` 自动上报。
- 后端会实时查询积分并写入 SQLite，返回 `session_token`；后续请求需携带 `Authorization: Bearer <session_token>`。

## API 提示

- `POST /api/login` { phone, token, ua } → { uid, session_token }；登录即查询积分/昵称并写库
- `GET /api/user/status` → { nick, integral, task_status }
- `POST /api/task/start` { video: bool, alipay: bool }
- `POST /api/task/stop` 停止当前用户的运行/排队任务
- `GET /ws/logs/{uid}` WebSocket 实时日志（前端按 `API_BASE` 动态拼接 ws/wss）
- 兼容旧接口：`/auth/login`、`/tasks` 列表查询

## 接入自动化

- `backend/task_engine.py` 将 `reference/胖乖0903.py` 改造成 `PangGuaiRunner`（支持停止、日志回调、积分收尾查询）。
- 前端或原 H5 调用 `window.reportTokenLogin({phone, token, ua})` 上报凭证，后端写库并返回会话令牌，任务可在控制台启动/停止。

## 备注

- SQLite 表会在启动时自动创建，`database.db` 已预置占位文件。
- 前端默认使用 `http://localhost:8000`，可通过 `window.PANGGUAI_API_BASE` 覆盖；WS 地址也随之自动调整（ws/wss）。
