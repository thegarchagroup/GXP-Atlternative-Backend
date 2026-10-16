# Hotel Room Management API (FastAPI)

Backend for room turnover, housekeeping inspections and engineering repairs.
Runs on **http://localhost:1802**, interactive API docs at **http://localhost:1802/docs**.

## Quick start (local)

Requires **Python 3.11 or newer**. Nothing else: by default it uses a local SQLite file.

**Windows**: double-click `start_local.bat`, or in a terminal:
```bat
cd hotel-room-management-backend
start_local.bat
```

**Linux / macOS**:
```bash
cd hotel-room-management-backend
./start_local.sh
```

The script creates a virtual environment (`.venv`), installs dependencies, creates a `.env`
for local use and starts the API. On the first run it prints the administrator sign-in:

```
First sign-in:  Department = Front Desk / Admin
                User ID    = admin
                Password   = (random, printed here and stored in .env)
```

You are asked to choose a new password at first sign-in. Then start the frontend
(`hotel-room-management-frontend/start_local`) and open **http://localhost:5173**.

### Manual steps (same thing, by hand)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
python scripts/setup_local_env.py         # creates .env (only if missing)
python main.py                            # serves on port 1802
```

## Using MySQL instead of SQLite

1. Create a database and user (MySQL 8):
   ```sql
   CREATE DATABASE hotel_rooms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'hotel_app'@'localhost' IDENTIFIED BY 'choose-a-password';
   GRANT ALL PRIVILEGES ON hotel_rooms.* TO 'hotel_app'@'localhost';
   ```
2. In `.env`, replace the `DATABASE_URL` line:
   ```
   DATABASE_URL=mysql+pymysql://hotel_app:choose-a-password@localhost:3306/hotel_rooms?charset=utf8mb4
   ```
   (Or leave `DATABASE_URL` empty and set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.)
3. Restart `python main.py`. Tables are created and reference data is seeded automatically.
   The first admin is created again from `BOOTSTRAP_ADMIN_*` because the new database has none.

## First administrator

Two ways, both only when needed:
- **From `.env`**: `BOOTSTRAP_ADMIN_USER_ID` / `BOOTSTRAP_ADMIN_PASSWORD` create an admin on startup
  **only if no active Front Desk admin exists**. Remove the password from `.env` afterwards if you like.
- **From the command line** (prompts for the password):
  ```bash
  python -m migrations.cli create-admin --user-id frontdesk.lead --name "Asha Rao"
  ```

The admin then creates Housekeeping and Engineering accounts under **Users** in the web app.

## Database migrations

Migrations are versioned in `migrations/startup.py` and recorded in the `schema_migrations` table.
They never drop tables, and startup is safe to repeat.
- Applied automatically on startup when `AUTO_MIGRATE=true` (default).
- Manually: `python -m migrations.cli migrate` and `python -m migrations.cli status`.
- First run seeds room types (Standard, Deluxe, Suite) and the three default checklists.
  Edit them in the web app under **Checklists** and **Rooms → Room types**.

## Tests

```bash
pip install -r requirements.txt
python -m pytest -q                         # uses a temporary SQLite database
# against MySQL (the database is wiped by the tests, use a throwaway one):
TEST_DATABASE_URL="mysql+pymysql://user:pass@localhost:3306/hrm_test?charset=utf8mb4" python -m pytest -q
```
Windows PowerShell: `$env:TEST_DATABASE_URL="..."; python -m pytest -q`

45 tests cover login, wrong department, token expiry/revocation, department permissions, user
admin (last-admin protection, soft delete), rooms, ticket creation and duplicate prevention,
checklist validation, failed inspections raising repairs, engineering failures blocking completion,
re-cleaning, the Ready-for-Guest release rules, invalid transitions, checklist history snapshots,
uploads and reports.

## Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL. Local default: `sqlite:///./hotel_local.db` |
| `JWT_SECRET_KEY` | Required, 32+ random characters (generated for you) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Session length, default 480 |
| `CORS_ORIGINS` | Comma-separated browser origins, default `http://localhost:5173` |
| `HOTEL_TIMEZONE` | IANA zone used for display, e.g. `Asia/Kolkata`. Stored times are UTC |
| `UPLOAD_DIR`, `MAX_UPLOAD_MB` | Photo/PDF storage folder and size limit |
| `RELEASE_DEPARTMENTS` | Who may mark a room Ready for Guest (all checks must still pass) |
| `BOOTSTRAP_ADMIN_*` | First administrator, see above |
| `AUTO_MIGRATE`, `SEED_REFERENCE_DATA` | Startup behaviour |
| `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` | Sign-in throttling |

## How the workflow is enforced

Ticket statuses drive room statuses; every transition is checked in `services/` and runs in one
database transaction with an audit-log entry.

1. **Front Desk** records a checkout → ticket `AWAITING_HOUSEKEEPING` (one open ticket per room,
   unless an admin gives a reason for an exception) → assigns a housekeeper.
2. **Housekeeping** starts → the current checklists are copied into the inspection (later edits
   don't change it) → marks cleaning tasks and Pass/Fail/N/A → submits. Required items and remarks
   on failures are enforced.
3. Any failure opens a **repair request** and the room becomes `ENGINEERING_REQUIRED`.
4. **Engineering** takes it, starts, records diagnosis, repair notes and its checklist. Completion is
   refused while any check fails. It can send the room back for **re-cleaning**.
5. **Release** (`POST /api/v1/turnover/{id}/release`) succeeds only when housekeeping passed, every
   failure was repaired, every repair's engineering check passed and any re-clean passed. Otherwise it
   returns `RELEASE_BLOCKED` with the list of reasons.

## API overview

All endpoints are under `/api/v1`. Full request/response schemas: http://localhost:1802/docs

| Group | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/change-password` |
| Users (admin) | `GET/POST /users`, `GET/PUT/DELETE /users/{id}`, `PATCH /users/{id}/status`, `POST /users/{id}/reset-password` |
| Rooms | `GET/POST /rooms`, `GET/PUT /rooms/{id}`, `PATCH /rooms/{id}/status`, `PATCH /rooms/{id}/occupancy`, `GET /rooms/{id}/history`, `GET/POST /rooms/types`, `PUT /rooms/types/{id}` |
| Turnover | `GET/POST /turnover`, `GET /turnover/{id}`, `POST /turnover/{id}/assign`, `/start`, `/release`, `/cancel`, `PATCH /turnover/{id}/priority`, `GET /turnover/{id}/timeline`, `/readiness` |
| Housekeeping | `GET /housekeeping/my-tickets`, `POST /housekeeping/{id}/start`, `GET/PUT /housekeeping/{id}/checklist`, `POST /housekeeping/{id}/submit` |
| Engineering | `GET /engineering/my-tickets`, `GET /engineering/repairs`, `GET /engineering/{id}`, `POST /engineering/{id}/assign`, `/start`, `/complete`, `/reopen`, `GET/PUT /engineering/{id}/checklist` |
| Checklists | `GET/POST /checklists`, `GET /checklists/preview`, `GET/PUT/DELETE /checklists/{id}`, `POST /checklists/{id}/items`, `PUT/DELETE /checklists/items/{id}` |
| Dashboards | `GET /dashboard/frontdesk`, `/housekeeping`, `/engineering`, `/notifications`, `/staff` |
| Reports | `GET /reports/room-turnover`, `GET /reports/maintenance` |
| Uploads | `POST /uploads` (JPEG/PNG/WebP/PDF), `GET /uploads/{id}` |
| Health | `GET /health` (no auth) |

Errors always look like `{"error": {"code": "...", "message": "...", "details": ...}}`.

**Authentication**: the web app uses an httpOnly cookie; API clients and Swagger can send
`Authorization: Bearer <access_token>` from the login response. Signing out, a password reset or
deactivation revokes existing tokens.

## Troubleshooting

- **Sign-in works but you are bounced back to the login page**: open the app at
  `http://localhost:5173`, not `http://127.0.0.1:5173`. The session cookie is tied to `localhost`.
- **CORS error in the browser console**: add your frontend address to `CORS_ORIGINS` and restart.
- **Port 1802 in use**: stop the other process, or run `uvicorn main:app --port 1900` and change
  `VITE_API_BASE_URL` in the frontend `.env` to match.
- **Forgot the admin password**: `python -m migrations.cli create-admin --user-id admin2 --name "Admin"`.

## Project layout

```
main.py            entry point (port 1802)
routers/           HTTP endpoints, one file per area
services/          business rules and workflow transitions
repositories/      query helpers
models/            SQLAlchemy tables      schemas/  request/response models
core/              config, security, permissions, errors
database/          engine and session     migrations/  versioned migrations, seed data, CLI
scripts/           setup_local_env.py     tests/       pytest suite
```

`Dockerfile` and `docker-compose.yml` (API + MySQL) are included for when you deploy later; they are
not needed to run locally.

## Known limitations

- Sign-in throttling is per process (in memory). Use a shared store if you run several API processes.
- Live updates use polling (every 20 s by default), not WebSockets.
- Uploaded files are stored on local disk (`UPLOAD_DIR`).
