import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from core.config import settings  # noqa: E402
from core.exceptions import register_exception_handlers  # noqa: E402
from database.connection import init_database  # noqa: E402
from migrations.startup import run_startup_tasks  # noqa: E402

from routers.auth_router import router as auth_router  # noqa: E402
from routers.users_router import router as users_router  # noqa: E402
from routers.rooms_router import router as rooms_router  # noqa: E402
from routers.turnover_router import router as turnover_router  # noqa: E402
from routers.daily_sheet_router import router as daily_sheet_router  # noqa: E402
from routers.housekeeping_router import router as housekeeping_router  # noqa: E402
from routers.guest_request_router import router as guest_request_router  # noqa: E402
from routers.engineering_router import router as engineering_router  # noqa: E402
from routers.checklist_router import router as checklist_router  # noqa: E402
from routers.dashboard_router import router as dashboard_router  # noqa: E402
from routers.reports_router import router as reports_router  # noqa: E402
from routers.uploads_router import router as uploads_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    run_startup_tasks()
    yield


app = FastAPI(
    title="Hotel Room Management API",
    version="1.0.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(rooms_router)
app.include_router(turnover_router)
app.include_router(daily_sheet_router)
app.include_router(housekeeping_router)
app.include_router(guest_request_router)
app.include_router(engineering_router)
app.include_router(checklist_router)
app.include_router(dashboard_router)
app.include_router(reports_router)
app.include_router(uploads_router)


@app.get("/")
def root():
    return {
        "message": "Hotel Room Management API is running",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=1802,
        reload=False,
    )
