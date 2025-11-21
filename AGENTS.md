# Repository Guidelines

## Project Structure & Module Organization
- `backend/`: FastAPI app (`main.py`) plus task wrapper (`task_engine.py`) that fans out logs to WebSocket clients and writes to SQLite `database.db`. Keep migrations small and additive; schema bootstraps on startup.
- `frontend/`: Static HTML/CSS/JS (`index.html`, `dashboard.html`, `app.js`, `style.css`) served by any static server; assets belong in `frontend/assets/`.
- `reference/`: Legacy scripts kept for comparison; do not edit unless explicitly refactoring history.

## Build, Test, and Development Commands
```bash
python -m venv .venv && source .venv/bin/activate   # optional env
pip install -r backend/requirements.txt             # backend deps
cd backend && uvicorn main:app --reload --port 8000 # run API
cd ../frontend && python -m http.server 5500        # serve UI
```
- Override frontend API origin with `window.PANGGUAI_API_BASE` in `index.html` (WS URL auto-derives), and set `PANGGUAI_PASSWORD_SALT` in the backend environment for stronger session hashing.

## Coding Style & Naming Conventions
- Python: PEP 8 with 4-space indents; prefer type hints and small helpers (see `get_db_connection`, `push_log`). Use snake_case for functions/vars, UpperCamelCase for Pydantic models.
- JS: Use `const`/`let`, arrow functions for helpers, semicolons kept as in `frontend/app.js`. Keep DOM IDs/classes aligned with existing dashboard/login markup.
- Keep user-facing copy concise and in the same language register already present (Chinese UI strings).

## Testing Guidelines
- No automated tests yet; add new tests under `backend/tests/` when introducing backend logic (pytest is recommended). For now, validate manually:
  - `curl -X POST http://localhost:8000/api/login -H "Content-Type: application/json" -d '{"phone":"...","token":"...","ua":"..."}'`
  - Start a task from `dashboard.html` and confirm WebSocket log streaming and task stop behavior.
- Ensure SQLite WAL files (`database.db-wal`, `database.db-shm`) are ignored from reviews unless schema changes are intentional.

## Commit & Pull Request Guidelines
- Commit messages should be imperative and scoped (e.g., `Add ws log buffering`, `Fix token validation`). Current history is minimal; stay consistent and keep bodies short but specific.
- PRs: include a clear summary, linked issue/trello if available, and screenshots/GIFs for UI changes (login and dashboard). Note schema tweaks, new env vars, and manual test results. Avoid committing local DB artifacts unless needed for schema updates.

## Security & Configuration Tips
- Do not log raw tokens or phone numbers beyond what `maskPhone`/`maskValue` already expose. Prefer masked logging in new endpoints.
- Keep secrets/env vars out of version control. When adding new config, document defaults and overrides in `README.md` and the relevant module docstring.

# 永远使用中文回答