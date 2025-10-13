"""
Dependency injection functions for FastAPI routes
"""

import os
from typing import Annotated, Any, Optional
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.browser import BrowserManager
from app.core.database import DatabaseManager, get_db
from app.services.element import ElementService
from app.services.substack import SubstackService
from app.services.cache_service import ExtractorCacheService
from app.services.agent_manager import AgentManager
from app.utils.cache import CacheManager

# ===========================
# Global singleton instances
# ===========================

# Single global browser manager
_browser_manager = None

# Global agent manager instance
_agent_manager: Optional[AgentManager] = None


# ===========================
# Dependency injection functions
# ===========================

def get_browser_manager() -> BrowserManager:
    """Get the single browser manager instance"""
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager(get_settings())
    return _browser_manager

def get_database_manager() -> DatabaseManager:
    """Get database manager instance"""
    return DatabaseManager()

def get_element_service(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)]
) -> ElementService:
    """Get element service instance"""
    return ElementService(browser_manager)

def get_substack_service(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    db_session: Annotated[Any, Depends(get_db)]
) -> SubstackService:
    """Get Substack service instance"""
    return SubstackService(browser_manager, db_session)

async def get_cache_service() -> ExtractorCacheService:
    """Get cache service instance"""
    settings = get_settings()
    if not settings.redis_url:
        settings.redis_url = os.getenv("REDIS_URL", "redis://redis-cache:6379")

    # Create manager without automatic task creation
    cache_manager = CacheManager(settings)

    # The cleanup task will start lazily when cache is first used
    return ExtractorCacheService(cache_manager)

def get_agent_manager() -> AgentManager:
    """Get or create agent manager singleton"""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager()
    return _agent_manager
