import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.db.database import init_db
from app.db.seed_data import seed_database
from app.api.routes_system_record import router as system_router
from app.api.routes_workflow import router as workflow_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("support_agent.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Customer Support Resolution System...")
    # Initialize DB tables
    await init_db()
    # Seed default realistic ground truth records
    try:
        summary = await seed_database()
        logger.info(f"Database readiness verified: {summary}")
    except Exception as e:
        logger.warning(f"Database seed skipped or failed: {e}")
    yield
    logger.info("Shutting down AI Customer Support Resolution System...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Agentic AI system for customer support resolution with deterministic business rules, MCP tools, and human approval.",
    lifespan=lifespan,
)

# CORS middleware for Web Dashboard & UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Include API routers
app.include_router(system_router)
app.include_router(workflow_router)

# Mount static assets
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "database": settings.get_async_db_url().split("@")[-1] if "@" in settings.get_async_db_url() else settings.get_async_db_url(),
        "primary_model": settings.PRIMARY_MODEL,
        "fallback_models": settings.fallback_model_list,
    }

@app.get("/", tags=["UI"])
@app.get("/customer", tags=["UI"])
@app.get("/customer/{full_path:path}", tags=["UI"])
@app.get("/agent", tags=["UI"])
@app.get("/agent/{full_path:path}", tags=["UI"])
async def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs_url": "/docs",
        "health_url": "/health",
        "system_api": "/api/system",
    }
