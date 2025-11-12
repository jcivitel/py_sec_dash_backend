"""
Main FastAPI Application Entry Point
Sec-Dash-Backend - CrowdSec Data Analysis Backend
"""

import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)

# Import routers
from app.api import alerts, health, country

# Stream listener thread reference
stream_thread = None


def start_stream_listener():
    """Start CrowdSec stream listener in background thread"""
    from app.crowdsec_client import start_stream_listener

    logger.info("Starting CrowdSec decision stream listener...")
    try:
        start_stream_listener()
    except Exception as e:
        logger.error(f"Stream listener error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    global stream_thread

    logger.info("Application starting...")

    # Start stream listener in background thread
    stream_thread = threading.Thread(target=start_stream_listener, daemon=True)
    stream_thread.start()
    logger.info("CrowdSec stream listener started in background")

    yield

    logger.info("Application shutting down...")
    # Thread will auto-exit as daemon


# Create FastAPI app
app = FastAPI(
    title="Sectacho API",
    description="CrowdSec Decision Stream Management",
    version="0.1.0",
    lifespan=lifespan,
)

# Add state limiter
app.state.limiter = limiter

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(alerts.router, prefix="/api/v1", tags=["decisions"])
app.include_router(country.router, prefix="/api/v1", tags=["country"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Welcome to Sectacho API", "version": "0.1.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=os.getenv("DEBUG", "False") == "True",
    )
