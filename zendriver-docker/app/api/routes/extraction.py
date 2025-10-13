"""
Content extraction and cache analytics routes
"""

from typing import Annotated, Optional, List
from datetime import datetime
from urllib.parse import urlparse
from fastapi import APIRouter, Query, Body, Depends
from pydantic import BaseModel, Field
import logging

from app.core.browser import BrowserManager
from app.models.requests import ExtractionRequestComplete
from app.services.cache_service import ExtractorCacheService
from app.services.extraction import UnifiedExtractionService
from app.api.dependencies import get_browser_manager, get_cache_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ===========================
# Request Models
# ===========================

class ExtractionRequest(BaseModel):
    """Enhanced extraction request"""
    selector: Optional[str] = Field(None, description="CSS selector")
    extract_text: Optional[bool] = Field(True, description="Extract text content")
    extract_href: Optional[bool] = Field(False, description="Extract href attributes")
    extract_all: Optional[bool] = Field(False, description="Extract from all matching elements")
    extract_attributes: Optional[List[str]] = Field(None, description="List of attributes to extract")


# ===========================
# Cache Analytics
# ===========================

@router.get("/cache/analytics")
async def get_cache_analytics(
    cache_service: Annotated[ExtractorCacheService, Depends(get_cache_service)]
):
    """Get cache performance analytics and insights"""
    try:
        stats = {
            "memory_cache_size": len(cache_service.cache.memory_cache),
            "cache_enabled": cache_service.cache.settings.redis_url is not None,
            "redis_connected": cache_service.cache.redis_client is not None,
            "timestamp": datetime.now().isoformat()
        }

        # Get sample of cached keys for analysis
        sample_keys = list(cache_service.cache.memory_cache.keys())[:20]
        stats["sample_cached_items"] = len(sample_keys)

        # Analyze cache key patterns
        bypass_patterns = {"search": 0, "dynamic": 0, "structural": 0, "other": 0}
        for key in sample_keys:
            if "search" in key:
                bypass_patterns["search"] += 1
            elif any(pattern in key for pattern in ["price", "stock", "live"]):
                bypass_patterns["dynamic"] += 1
            elif any(pattern in key for pattern in ["nav", "header", "footer"]):
                bypass_patterns["structural"] += 1
            else:
                bypass_patterns["other"] += 1

        stats["cache_patterns"] = bypass_patterns

        # Get best performing selectors if available
        if hasattr(cache_service, 'get_best_selectors'):
            try:
                best_selectors = await cache_service.get_best_selectors("example.com")
                stats["selector_optimization_available"] = len(best_selectors) > 0
            except:
                stats["selector_optimization_available"] = False

        return stats

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@router.get("/optimization/suggest_selectors")
async def suggest_optimized_selectors(
    cache_service: Annotated[ExtractorCacheService, Depends(get_cache_service)],
    url: str = Query(..., description="URL to get optimized selectors for"),
    element_type: str = Query("general", description="Element type: navigation, content, forms, links, general")
):
    """Get optimized selector suggestions for a URL"""
    try:
        optimized_selector = await cache_service.get_optimized_selector(url, element_type)

        # Get performance stats for the domain
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        best_selectors = await cache_service.get_best_selectors(domain) if domain else []

        return {
            "status": "success",
            "url": url,
            "element_type": element_type,
            "optimized_selector": optimized_selector,
            "available_selectors_count": len(best_selectors),
            "domain_has_data": len(best_selectors) > 0,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# ===========================
# Extraction Operations
# ===========================

@router.post("/extraction/parallel")
async def parallel_extraction(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    cache_service: Annotated[ExtractorCacheService, Depends(get_cache_service)],
    selectors: List[str] = Body(...)
):
    """Extract from multiple selectors in parallel with caching - faster for SmolAgents"""
    service = UnifiedExtractionService(browser_manager, cache_service)
    results = await service.extract_parallel(selectors, use_cache=True)
    return results

@router.post("/extraction/extract")
async def extract_content(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    cache_service: Annotated[ExtractorCacheService, Depends(get_cache_service)],
    request: ExtractionRequestComplete
):
    """Universal extraction with caching support"""
    service = UnifiedExtractionService(browser_manager, cache_service)

    # Use the service's extract method
    result = await service.extract(
        selector=request.selector,
        xpath=request.xpath,
        extract_all=request.extract_all,
        extract_text=request.extract_text,
        extract_href=request.extract_href,
        use_cache=request.use_cache,
        include_metadata=request.include_metadata
    )

    # Return the result which already includes formatted_output for Open WebUI
    return result
