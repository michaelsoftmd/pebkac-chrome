"""
Zendriver Browser Automation API
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.core.database import init_db
from app.api.dependencies import get_browser_manager
from app.api.routes import (
    health,
    browser,
    interaction,
    extraction,
    network,
    capture,
    agent
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ===========================
# Application Lifespan
# ===========================

async def periodic_session_save(browser_manager):
    """Save session data every 5 minutes"""
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes
            await browser_manager.save_session_data()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Auto-save failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting application...")
    init_db()

    # Create single browser instance
    browser_manager = get_browser_manager()
    try:
        await browser_manager.get_browser()
        logger.info("Persistent browser initialized")
    except Exception as e:
        logger.error(f"Browser init failed: {e}")

    # Start periodic save task
    save_task = asyncio.create_task(periodic_session_save(browser_manager))
    logger.info("Started periodic session save (5 min intervals)")

    yield

    # Shutdown - Cancel auto-save, save session, and cleanup browser
    save_task.cancel()
    logger.info("Saving browser session data...")
    try:
        await browser_manager.save_session_data()
    except Exception as e:
        logger.error(f"Could not save session: {e}")

    logger.info("Cleaning up browser...")
    try:
        await browser_manager.cleanup()
    except Exception as e:
        logger.error(f"Browser cleanup failed: {e}")


# ===========================
# Application Setup
# ===========================

# Create FastAPI app
app = FastAPI(
    title="Zendriver Browser Automation API",
    description="Enhanced browser automation API with Zendriver",
    version="4.0.0",
    lifespan=lifespan
)

# CORS middleware for control panel access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8888"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(browser.router, tags=["browser"])
app.include_router(interaction.router, tags=["interaction"])
app.include_router(extraction.router, tags=["extraction"])
app.include_router(network.router, tags=["network"])
app.include_router(capture.router, tags=["capture"])
app.include_router(agent.router, tags=["agent"])


# ===========================
# Run the application
# ===========================

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info"
    )
