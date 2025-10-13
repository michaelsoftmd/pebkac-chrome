"""
Health check and info routes
"""

from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.browser import BrowserManager
from app.core.database import DatabaseManager
from app.api.dependencies import get_browser_manager, get_database_manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def root():
    """API information"""
    settings = get_settings()
    return {
        "service": settings.app_name,
        "version": "4.0.0",
        "status": "ready",
        "features": [
            "navigation", "clicking", "typing", "scrolling",
            "element_discovery", "tab_navigation", "extraction", "keyboard",
            "browser_warmup"
        ],
        "warmup_status": "enabled"
    }

@router.get("/health")
async def health_check(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    db_manager: Annotated[DatabaseManager, Depends(get_database_manager)]
):
    """Health check endpoint"""
    browser_status = False
    try:
        from app.core.browser import is_browser_alive
        browser = await browser_manager.get_browser()
        browser_status = await is_browser_alive(browser)
    except Exception:
        pass

    db_healthy = False
    try:
        sessions = db_manager.get_research_sessions(limit=1)
        db_healthy = True
    except Exception:
        pass

    return {
        "status": "healthy",
        "browser_running": browser_status,
        "database_healthy": db_healthy,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/get_current_url")
async def get_current_url(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)]
):
    """Get current URL from persistent browser"""
    try:
        tab = await browser_manager.get_tab()
        url = await tab.evaluate("window.location.href")
        title = await tab.evaluate("document.title")

        return {
            "status": "success",
            "url": url or "about:blank",
            "title": title or "Untitled"
        }
    except Exception as e:
        logger.error(f"Error getting URL: {e}")
        return {
            "status": "error",
            "url": "unknown",
            "error": str(e)
        }
