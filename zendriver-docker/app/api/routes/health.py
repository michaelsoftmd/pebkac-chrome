"""
Health check and info routes
"""

from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.browser import BrowserManager
from app.core.database import DatabaseManager
from app.services.cache_service import ExtractorCacheService
from app.api.dependencies import get_browser_manager, get_database_manager, get_cache_service
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

@router.get("/cache/stats")
async def get_cache_stats(
    cache_service: Annotated[ExtractorCacheService, Depends(get_cache_service)]
):
    """
    Get comprehensive cache statistics

    Returns stats from:
    - L1 (Redis): Memory usage, key counts, selector counts
    - L2 (DuckDB): Page counts, size, age
    - Selector memory: Redis + DuckDB selector tracking with 90-day TTL
    """
    try:
        stats = await cache_service.get_comprehensive_stats()
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "cache_stats": stats
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
