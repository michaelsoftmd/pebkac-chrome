"""
Zendriver Browser Automation API
"""

import os
import asyncio
from fastapi import FastAPI, HTTPException, Query, Body, Depends, status, Header
from contextlib import asynccontextmanager
import uvicorn
import logging
from typing import Optional, List, Dict, Any, Annotated
from datetime import datetime
from pydantic import BaseModel, Field
from zendriver import cdp
import base64
import re
from pathlib import Path

# Import refactored modules
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from app.core.config import Settings, get_settings
from app.core.browser import BrowserManager
from app.core.database import DatabaseManager, init_db, get_db
from app.core.exceptions import BrowserError, ElementNotFoundError
from app.core.timeouts import TIMEOUTS
from app.models.requests import NavigationRequest, ClickRequest, SubstackPublicationRequest, ExtractionRequestComplete
from app.services.element import ElementService
from app.services.substack import SubstackService
from app.services.cache_service import ExtractorCacheService
from app.services.workflows import WorkflowService
from app.utils.cache import CacheManager
from zendriver.cdp import input_ as cdp_input
from zendriver.core.intercept import BaseFetchInterception
from zendriver.cdp.fetch import RequestStage
from zendriver.cdp.network import ResourceType
from app.services.extraction import UnifiedExtractionService
from app.utils.browser_utils import safe_evaluate
from zendriver.core.keys import KeyEvents, SpecialKeys, KeyPressEvent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===========================
# Request Models for New Features
# ===========================
class TypeRequest(BaseModel):
    """Request model for typing text"""
    text: str = Field(..., description="Text to type")
    selector: Optional[str] = Field(None, description="CSS selector of input element")
    clear_first: Optional[bool] = Field(False, description="Clear field before typing")
    press_enter: Optional[bool] = Field(False, description="Press Enter after typing")
    delay: Optional[float] = Field(0.045, description="Delay between keystrokes (130 WPM - Speedy Gonzales)")

class ScrollRequest(BaseModel):
    """Request model for scrolling"""
    direction: Optional[str] = Field("down", description="Direction: up, down, left, right")
    pixels: Optional[int] = Field(300, description="Pixels to scroll")
    to_element: Optional[str] = Field(None, description="CSS selector to scroll to")
    smooth: Optional[bool] = Field(True, description="Use smooth scrolling")

class ElementSearchRequest(BaseModel):
    """Request model for finding elements"""
    element_type: Optional[str] = Field("all", description="Type: input, button, link, text, all")
    interactive_only: Optional[bool] = Field(True, description="Only return interactive elements")
    visible_only: Optional[bool] = Field(True, description="Only return visible elements")

class TabNavigationRequest(BaseModel):
    """Request model for tab navigation"""
    count: Optional[int] = Field(1, description="Number of times to press tab")
    shift: Optional[bool] = Field(False, description="Hold shift (go backwards)")

class ExtractionRequest(BaseModel):
    """Enhanced extraction request"""
    selector: Optional[str] = Field(None, description="CSS selector")
    extract_text: Optional[bool] = Field(True, description="Extract text content")
    extract_href: Optional[bool] = Field(False, description="Extract href attributes")
    extract_all: Optional[bool] = Field(False, description="Extract from all matching elements")
    extract_attributes: Optional[List[str]] = Field(None, description="List of attributes to extract")


# ===========================
# Dependency injection functions
# ===========================

# Single global browser manager
_browser_manager = None

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

def get_cache_service() -> ExtractorCacheService:
    """Get cache service instance"""
    settings = get_settings()
    if not settings.redis_url:
        settings.redis_url = os.getenv("REDIS_URL", "redis://redis-cache:6379")
    cache_manager = CacheManager(settings)
    return ExtractorCacheService(cache_manager)


# ===========================
# Application Lifespan
# ===========================

async def periodic_session_save(browser_manager: BrowserManager):
    """Save session data every 5 minutes"""
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes
            await browser_manager.save_session_data()
            logger.debug("Session auto-saved")
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

    # Shutdown - Cancel auto-save and do final save
    save_task.cancel()
    logger.info("Saving browser session data...")
    try:
        await browser_manager.save_session_data()
    except Exception as e:
        logger.error(f"Could not save session: {e}")

# Create FastAPI app
app = FastAPI(
    title="Zendriver Browser Automation API",
    description="Enhanced browser automation API with Zendriver",
    version="4.0.0",
    lifespan=lifespan
)

# ===========================
# Core API Routes
# ===========================
@app.get("/")
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

@app.get("/health")
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

@app.get("/get_current_url")
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

@app.get("/cache/analytics")
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

@app.get("/optimization/suggest_selectors")
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

@app.post("/navigate")
async def navigate_to_url(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    request: NavigationRequest
):
    """Navigate in the persistent browser"""
    try:
        result = await browser_manager.navigate(
            url=str(request.url),
            wait_for=request.wait_for,
            wait_timeout=request.wait_timeout
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/click")
async def click_element(
    element_service: Annotated[ElementService, Depends(get_element_service)],
    request: ClickRequest
):
    """Click an element"""
    try:
        await element_service.click_element(
            selector=request.selector,
            text=request.text,
            wait_after=request.wait_after
        )
        
        return {
            "status": "success",
            "message": "Element clicked successfully"
        }
    except ElementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BrowserError as e:
        raise HTTPException(status_code=500, detail=str(e))

# ===========================
# Cloudflare Handling
# ===========================
async def _get_challenge_indicators(tab):
    """Unified challenge detection logic for both Cloudflare and reCAPTCHA"""
    return await safe_evaluate(tab, """
        (() => {
            const indicators = {
                // Cloudflare indicators
                hasCfRay: !!document.querySelector('meta[name="cf-ray"]'),
                hasChallengeForm: !!document.querySelector('form#challenge-form, form[action*="cdn-cgi"]'),
                titleHasCloudflare: /cloudflare|checking|just a moment|checking your browser/i.test(document.title || ''),
                hasCfScript: Array.from(document.scripts || []).some(s => 
                    s.src && s.src.includes('cloudflare')),
                bodyTextCloudflare: /checking your browser|just a moment|please wait|ddos protection by cloudflare|ray id/i.test(document.body?.innerText || ''),
                
                // reCAPTCHA indicators
                hasRecaptchaIframe: document.querySelectorAll('iframe[src*="recaptcha"], iframe[src*="google.com/recaptcha"], iframe[title="reCAPTCHA"]').length > 0,
                hasRecaptchaElement: document.querySelectorAll('.g-recaptcha, .recaptcha, [class*="recaptcha"], [data-sitekey]').length > 0,
                hasRecaptchaScript: Array.from(document.scripts || []).some(s => 
                    s.src && (s.src.includes('recaptcha') || s.src.includes('google.com/recaptcha'))),
                titleHasRecaptcha: /recaptcha|not a robot|verify you are human/i.test(document.title || ''),
                bodyTextRecaptcha: /i'm not a robot|recaptcha|please verify|verify you are not a robot/i.test(document.body?.innerText || '')
            };
            return indicators;
        })()
    """)

async def _determine_challenge_type(indicators):
    """Determine challenge type from unified indicators"""
    if not indicators or not isinstance(indicators, dict):
        return "none", False, False
        
    is_cloudflare = any([
        indicators.get('titleHasCloudflare', False),
        indicators.get('hasChallengeForm', False),
        indicators.get('hasCfScript', False),
        indicators.get('bodyTextCloudflare', False)
    ])
    
    is_recaptcha = any([
        indicators.get('hasRecaptchaIframe', False),
        indicators.get('hasRecaptchaElement', False),
        indicators.get('hasRecaptchaScript', False),
        indicators.get('titleHasRecaptcha', False),
        indicators.get('bodyTextRecaptcha', False)
    ])
    
    if is_cloudflare and is_recaptcha:
        challenge_type = "mixed"
    elif is_cloudflare:
        challenge_type = "cloudflare"
    elif is_recaptcha:
        challenge_type = "recaptcha"
    else:
        challenge_type = "none"
    
    return challenge_type, is_cloudflare, is_recaptcha
@app.get("/cloudflare/detect")
async def detect_cloudflare(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)]
):
    """Check if current page has Cloudflare challenge"""
    tab = await browser_manager.get_tab()
    
    try:
        from app.utils.browser_utils import safe_evaluate
        
        # Use unified challenge detection
        indicators = await _get_challenge_indicators(tab)
        challenge_type, is_cloudflare, is_recaptcha = await _determine_challenge_type(indicators)
        
        # Additional check for Cloudflare interactive challenges
        if is_cloudflare:
            from app.core.cloudflare import cf_is_interactive_challenge_present
            has_cf_interactive = await cf_is_interactive_challenge_present(tab, timeout=TIMEOUTS.element_find)
            if has_cf_interactive:
                challenge_type = "cloudflare_interactive"
        else:
            has_cf_interactive = False
            
        return {
            "status": "challenge_detected" if (is_cloudflare or is_recaptcha) else "no_challenge",
            "has_cloudflare": is_cloudflare,
            "has_recaptcha": is_recaptcha,
            "has_challenge": has_cf_interactive or is_recaptcha,
            "challenge_type": challenge_type,
            "indicators": indicators or {}
        }
        
    except Exception as e:
        logger.error(f"Cloudflare detection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "detection_failed", "message": str(e)}
        )

async def _solve_recaptcha_checkbox(tab, timeout: int = 15):
    """
    Find and click reCAPTCHA checkbox using precise coordinate-based clicking.
    Returns (success: bool, message: str)
    """
    try:
        logger.debug("Looking for reCAPTCHA checkbox...")

        # Find the reCAPTCHA anchor iframe
        iframe_selectors = [
            'iframe[src*="google.com/recaptcha/api2/anchor"]',
            'iframe[src*="google.com/recaptcha/enterprise/anchor"]',
            'iframe[title="reCAPTCHA"]',
            'iframe[name^="a-"][src*="recaptcha"]'
        ]

        anchor_frame = None
        for selector in iframe_selectors:
            try:
                anchor_frame = await tab.find(selector, timeout=TIMEOUTS.element_find)
                if anchor_frame:
                    logger.info(f"Found reCAPTCHA iframe with selector: {selector}")
                    break
            except:
                continue

        if not anchor_frame:
            return False, "No reCAPTCHA iframe found"

        # Use precise coordinate clicking like Cloudflare method
        try:
            logger.info("Attempting to click reCAPTCHA checkbox using precise coordinates")

            # Scroll iframe into view
            await anchor_frame.scroll_into_view()
            await asyncio.sleep(0.5)  # Wait for scroll to complete

            # Re-find the element to get fresh node ID after scroll
            anchor_frame = None
            for selector in iframe_selectors:
                try:
                    anchor_frame = await tab.find(selector, timeout=2)
                    if anchor_frame:
                        break
                except:
                    continue

            if not anchor_frame:
                return False, "reCAPTCHA iframe disappeared after scroll"

            # Get the iframe's box model for precise clicking
            from zendriver import cdp

            logger.debug(f"Getting box model for reCAPTCHA iframe (node_id: {anchor_frame.node.node_id})")
            try:
                box_model_result = await tab.send(
                    cdp.dom.get_box_model(node_id=anchor_frame.node.node_id)
                )
            except Exception as e:
                if "Could not find node" in str(e):
                    # Try alternative approach - click by position
                    try:
                        logger.warning("Node ID stale, trying alternative position method")
                        pos = await anchor_frame.get_position()
                        if pos:
                            click_x = pos.center[0] * 0.15  # 15% from left
                            click_y = pos.center[1]
                            await tab.mouse_click(click_x, click_y)
                            logger.info("reCAPTCHA clicked using alternative position method")
                            await asyncio.sleep(2)
                            return True, "Clicked using alternative position method"
                    except Exception as alt_e:
                        logger.error(f"Alternative click method failed: {alt_e}")
                    return False, f"Click failed: {str(e)}"
                else:
                    raise

            # Extract coordinates from content quad
            content_quad = box_model_result.content
            x_coords = content_quad[0::2]  # x coordinates of 4 corners
            y_coords = content_quad[1::2]  # y coordinates of 4 corners

            min_x = min(x_coords)
            max_x = max(x_coords)
            min_y = min(y_coords)
            max_y = max(y_coords)

            # Calculate click position for reCAPTCHA checkbox
            # reCAPTCHA checkbox is typically in the left part of the iframe
            click_x = min_x + (max_x - min_x) * 0.15  # 15% from left edge
            click_y = min_y + (max_y - min_y) * 0.5   # Center vertically

            logger.debug(
                f"reCAPTCHA iframe dimensions: width={max_x - min_x}, height={max_y - min_y}"
            )
            logger.debug(f"Calculated click coordinates: ({click_x}, {click_y})")

            # Perform the precise mouse click
            await tab.mouse_click(click_x, click_y)
            logger.info("reCAPTCHA checkbox clicked using precise coordinates")

            # Wait for click to register
            await asyncio.sleep(2)

            # Check if we passed (look for token)
            from app.utils.browser_utils import safe_evaluate
            token_check = await safe_evaluate(tab, """
                (() => {
                    const response = document.querySelector('[name="g-recaptcha-response"]');
                    return response && response.value ? 'passed' : 'unknown';
                })()
            """)

            if token_check == 'passed':
                return True, "reCAPTCHA checkbox clicked - passed without challenge"

            # Check if challenge iframe appeared
            try:
                challenge_frame = await tab.find('iframe[src*="bframe"]', timeout=TIMEOUTS.element_find)
                if challenge_frame:
                    return True, "reCAPTCHA checkbox clicked - challenge appeared (requires manual solving)"
            except:
                pass

            return True, "reCAPTCHA checkbox clicked using precise coordinates"

        except Exception as e:
            logger.error(f"Error clicking reCAPTCHA: {e}")
            return False, f"Coordinate click error: {str(e)}"

    except Exception as e:
        logger.error(f"Failed to solve reCAPTCHA: {e}")
        return False, f"Error: {str(e)}"

@app.post("/cloudflare/solve")
async def solve_cloudflare_challenge(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    timeout: int = Body(15, description="Timeout for solving challenge"),
    click_delay: float = Body(5, description="Delay between clicks")
):
    """Attempt to solve Cloudflare challenge if present"""
    tab = await browser_manager.get_tab()
    
    try:
        from app.utils.browser_utils import safe_evaluate
        
        # Use unified challenge detection
        indicators = await _get_challenge_indicators(tab)
        challenge_type, is_cloudflare_page, is_recaptcha_page = await _determine_challenge_type(indicators)
        
        # Solve Cloudflare challenge
        if is_cloudflare_page:
            from app.core.cloudflare import verify_cf
            await verify_cf(tab, click_delay=click_delay, timeout=timeout)
            return {
                "status": "success",
                "message": "Cloudflare challenge solved",
                "type": "cloudflare"
            }
        
        # Solve reCAPTCHA challenge
        if is_recaptcha_page:
            success, message = await _solve_recaptcha_checkbox(tab, timeout)
            if success:
                return {
                    "status": "success",
                    "message": message,
                    "type": "recaptcha"
                }
            else:
                return {
                    "status": "error",
                    "error": message,
                    "type": "recaptcha"
                }
        
        # No challenge found
        return {
            "status": "no_challenge",
            "message": "No Cloudflare or reCAPTCHA challenge found"
        }
        
    except TimeoutError as e:
        return {
            "status": "timeout",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Cloudflare solve error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# ===========================
# Type/Input and Keyboard Functionality
# ===========================
@app.post("/interaction/type")
async def type_text(
    request: TypeRequest,
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)]
):
    """Type text into an element"""
    tab = await browser_manager.get_tab()
    
    try:
        element = None
        
        # Find element by selector
        if request.selector:
            element = await tab.select(request.selector, timeout=TIMEOUTS.element_find)
            if not element:
                # Try finding by text if selector looks like text
                element = await tab.find(request.selector, timeout=TIMEOUTS.element_find)
        
        if not element:
            raise ElementNotFoundError(f"Could not find element: {request.selector}")
        
        # Clear if requested
        if request.clear_first:
            await element.clear_input()
        
        # Type the text with fast but natural timing (Speedy Gonzales style)
        if request.delay and request.delay > 0:
            import random
            # Character-by-character typing with human-like variance
            for char in request.text:
                base_delay = request.delay
                # Add tighter variance for faster but still natural feel
                actual_delay = base_delay + random.uniform(-0.015, 0.02)
                
                # Shorter pauses after punctuation for speed
                if char in '.!?,;:':
                    actual_delay += random.uniform(0.02, 0.05)
                
                # Extra short pause for spaces (natural word boundaries)
                if char == ' ':
                    actual_delay += random.uniform(0.005, 0.015)
                
                await element.send_keys(char)
                await asyncio.sleep(actual_delay)
        else:
            # Send all at once if no delay specified
            await element.send_keys(request.text)
        
        # Press Enter if requested
        if request.press_enter:
            await asyncio.sleep(0.3)  # Small delay before Enter
            await element.send_keys("\n")
            await asyncio.sleep(3)  # Wait for action to complete
        
        return {
            "status": "success",
            "message": f"Typed text: {request.text[:50]}..."
        }
        
    except Exception as e:
        logger.error(f"Type text error: {e}")
        return {"status": "error", "error": str(e)}

@app.post("/interaction/keyboard")
async def keyboard_action(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    request: Dict[str, str] = Body(...)
):
    """Send keyboard key press using Zendriver's native keyboard support"""
    key = request.get("key", "")
    
    tab = await browser_manager.get_tab()
    
    try:
        # Map common key names to SpecialKeys
        special_key_map = {
            "enter": SpecialKeys.ENTER,
            "return": SpecialKeys.ENTER,
            "tab": SpecialKeys.TAB,
            "escape": SpecialKeys.ESCAPE,
            "esc": SpecialKeys.ESCAPE,
            "backspace": SpecialKeys.BACKSPACE,
            "delete": SpecialKeys.DELETE,
            "space": SpecialKeys.SPACE,
            "arrowup": SpecialKeys.ARROW_UP,
            "arrowdown": SpecialKeys.ARROW_DOWN,
            "arrowleft": SpecialKeys.ARROW_LEFT,
            "arrowright": SpecialKeys.ARROW_RIGHT,
        }
        
        key_lower = key.lower()
        
        # Check if it's a special key
        if key_lower in special_key_map:
            special_key = special_key_map[key_lower]
            key_event = KeyEvents(special_key)
            payloads = key_event.to_cdp_events(KeyPressEvent.DOWN_AND_UP)
            
            # Send the CDP events directly to the tab
            for payload in payloads:
                await tab.send(cdp.input_.dispatch_key_event(**payload))
        else:
            # For regular characters, use KeyEvents.from_text
            payloads = KeyEvents.from_text(key, KeyPressEvent.CHAR)
            for payload in payloads:
                await tab.send(cdp.input_.dispatch_key_event(**payload))
        
        # Small delay to let the action complete
        await asyncio.sleep(0.1)
        
        return {
            "status": "success",
            "message": f"Pressed key: {key}"
        }
        
    except Exception as e:
        logger.error(f"Keyboard action error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ===========================
# Scroll Functionality
# ===========================
@app.post("/interaction/scroll")
async def scroll_page(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    request: ScrollRequest
):
    """Scroll the page"""
    tab = await browser_manager.get_tab()
    try:
        if request.to_element:
            # Scroll to specific element
            script = f"""
                const element = document.querySelector('{request.to_element}');
                if (element) {{
                    element.scrollIntoView({{
                        behavior: '{'smooth' if request.smooth else 'auto'}',
                        block: 'center'
                    }});
                    return true;
                }}
                return false;
            """
            success = await safe_evaluate(tab, script)
            if not success:
                raise ElementNotFoundError(f"Element not found: {request.to_element}")
        else:
            # Directional scrolling
            x, y = 0, 0
            if request.direction == "down":
                y = request.pixels
            elif request.direction == "up":
                y = -request.pixels
            elif request.direction == "right":
                x = request.pixels
            elif request.direction == "left":
                x = -request.pixels
            
            script = f"""
                window.scrollBy({{
                    left: {x},
                    top: {y},
                    behavior: '{'smooth' if request.smooth else 'auto'}'
                }});
                return {{
                    x: window.pageXOffset,
                    y: window.pageYOffset
                }};
            """
            position = await safe_evaluate(tab, script)
            
            return {
                "status": "success",
                "message": f"Scrolled {request.direction} by {request.pixels}px",
                "current_position": position
            }
        
        return {
            "status": "success",
            "message": f"Scrolled to element: {request.to_element}" if request.to_element else "Scroll completed"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "scroll_failed",
                "message": str(e),
                "request": {"direction": request.direction, "pixels": request.pixels}
            }
        )

# ===========================
# Element Discovery
# ===========================
@app.post("/interaction/find_elements")
async def find_elements(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    request: ElementSearchRequest
):
    """Find elements using native Zendriver methods"""
    tab = await browser_manager.get_tab()
    
    selectors = {
        "input": "input, textarea, select",
        "button": "button, input[type='submit'], input[type='button'], [role='button']",
        "link": "a[href]",
        "text": "p, span, div, h1, h2, h3, h4, h5, h6",
        "all": "*"
    }
    
    selector = selectors.get(request.element_type, "*")
    
    try:
        elements = await tab.select_all(selector, timeout=TIMEOUTS.element_find)
        results = []
        
        for elem in elements[:50]:  # Limit to 50
            if elem:
                position = await elem.get_position()
                if position and (not request.visible_only or position.width > 0):
                    results.append({
                        "tagName": elem.tag_name,
                        "text": elem.text[:100] if elem.text else None,
                        "id": elem.attrs.get("id"),
                        "className": elem.attrs.get("class"),
                        "href": elem.attrs.get("href"),
                        "position": {
                            "x": position.left,
                            "y": position.top,
                            "width": position.width,
                            "height": position.height
                        } if position else None
                    })
        
        return {
            "status": "success",
            "count": len(results),
            "elements": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/element/position")
async def get_element_position(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    selector: str = Body(..., description="CSS selector of element")
):
    """Get element position and dimensions"""
    tab = await browser_manager.get_tab()
    
    try:
        element = await tab.find(selector, timeout=TIMEOUTS.element_find)
        if not element:
            raise ElementNotFoundError(f"Element not found: {selector}")
        
        position = await element.get_position(abs=True)
        if not position:
            raise HTTPException(status_code=404, detail="Could not determine element position")
        
        return {
            "status": "success",
            "selector": selector,
            "position": {
                "x": position.left,
                "y": position.top,
                "width": position.width,
                "height": position.height,
                "center_x": position.center[0],
                "center_y": position.center[1],
                "abs_x": position.abs_x if hasattr(position, 'abs_x') else None,
                "abs_y": position.abs_y if hasattr(position, 'abs_y') else None
            }
        }
    except Exception as e:
        logger.error(f"Position error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ===========================
# Tab Navigation
# ===========================
@app.post("/interaction/tab_navigate")
async def tab_navigate(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    request: TabNavigationRequest
):
    """Navigate through page using Tab key"""
    tab = await browser_manager.get_tab()
    
    try:
        # Press Tab key the specified number of times
        for _ in range(request.count):
            if request.shift:
                # Shift+Tab (go backwards)
                await tab.send(cdp_input.dispatch_key_event(type_="keyDown", key="Shift"))
                await tab.send(cdp_input.dispatch_key_event(type_="keyDown", key="Tab"))
                await tab.send(cdp_input.dispatch_key_event(type_="keyUp", key="Tab"))
                await tab.send(cdp_input.dispatch_key_event(type_="keyUp", key="Shift"))
            else:
                # Tab (go forwards)
                await tab.send(cdp_input.dispatch_key_event(type_="keyDown", key="Tab"))
                await tab.send(cdp_input.dispatch_key_event(type_="keyUp", key="Tab"))
            
            await asyncio.sleep(0.1)
        
        # Get information about the currently focused element
        focused_element = await safe_evaluate(tab, """
            const el = document.activeElement;
            if (el) {
                return {
                    tagName: el.tagName,
                    type: el.type || null,
                    id: el.id || null,
                    className: el.className || null,
                    text: el.innerText ? el.innerText.substring(0, 100) : null,
                    placeholder: el.placeholder || null,
                    href: el.href || null
                };
            }
            return null;
        """)
        
        return {
            "status": "success",
            "message": f"Pressed Tab {request.count} time(s)",
            "focused_element": focused_element
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ===========================
# Database Operations
# ===========================
@app.post("/cookies/save")
async def save_cookies(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    file: str = "cookies.dat"
):
    """Save browser cookies to file"""
    browser = await browser_manager.get_browser()
    await browser.cookies.save(file)
    return {"status": "saved", "file": file}

@app.post("/cookies/load")
async def load_cookies(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    file: str = "cookies.dat"
):
    """Load cookies from file"""
    browser = await browser_manager.get_browser()
    await browser.cookies.load(file)
    return {"status": "loaded", "file": file}

# ===========================
# Parallel Operations
# ===========================
@app.post("/extraction/parallel")
async def parallel_extraction(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    cache_service: Annotated[ExtractorCacheService, Depends(get_cache_service)],
    selectors: List[str] = Body(...)
):
    """Extract from multiple selectors in parallel with caching - faster for SmolAgents"""
    service = UnifiedExtractionService(browser_manager, cache_service)
    results = await service.extract_parallel(selectors, use_cache=True)
    return results

# ===========================
# Extraction and Cache-Extract
# ===========================
# Extraction endpoint:
@app.post("/extraction/extract")
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



# ===========================
# Network Intercept
# ===========================
@app.post("/intercept/start")
async def start_interception(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    url_pattern: str = Body(..., description="URL pattern to intercept (e.g., *.jpg, *api*)"),
    resource_type: str = Body("Document", description="Resource type: Document, Script, Image, Stylesheet, XHR, Fetch"),
    action: str = Body("log", description="Action: log, block, modify")
):
    """Start intercepting network requests matching pattern"""
    tab = await browser_manager.get_tab()
    
    try:
        # Map string to ResourceType enum
        resource_type_map = {
            "Document": ResourceType.DOCUMENT,
            "Script": ResourceType.SCRIPT,
            "Image": ResourceType.IMAGE,
            "Stylesheet": ResourceType.STYLESHEET,
            "XHR": ResourceType.XHR,
            "Fetch": ResourceType.FETCH,
        }
        
        resource = resource_type_map.get(resource_type, ResourceType.DOCUMENT)
        
        # Create interception
        interceptor = BaseFetchInterception(
            tab,
            url_pattern,
            RequestStage.RESPONSE,  # Intercept at response stage
            resource
        )
        
        # Start interception in background
        async def intercept_handler():
            async with interceptor:
                # Wait for matching request
                request = await interceptor.request
                response_body = await interceptor.response_body
                
                if action == "block":
                    await interceptor.fail_request(cdp.network.ErrorReason.BLOCKED_BY_CLIENT)
                    return {"blocked": True, "url": request.url}
                elif action == "modify":
                    # Example: modify response
                    await interceptor.fulfill_request(
                        response_code=200,
                        body="Modified response content"
                    )
                    return {"modified": True, "url": request.url}
                else:  # log
                    await interceptor.continue_request()
                    return {
                        "logged": True,
                        "url": request.url,
                        "method": request.method,
                        "response_size": len(response_body[0]) if response_body else 0
                    }
        
        # Run in background
        asyncio.create_task(intercept_handler())

        return {
            "status": "interception_started",
            "pattern": url_pattern,
            "resource_type": resource_type,
            "action": action
        }

    except Exception as e:
        logger.error(f"Interception error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
@app.post("/intercept/list")
async def list_network_requests(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    url_filter: Optional[str] = Body(None, description="Optional URL filter pattern")
):
    """List recent network requests (requires network domain enabled)"""
    tab = await browser_manager.get_tab()
    
    try:
        # Enable network domain
        await tab.send(cdp.network.enable())
        
        # Collect network events for a short period
        requests = []
        
        async def request_handler(event: cdp.network.RequestWillBeSent):
            if not url_filter or url_filter in event.request.url:
                requests.append({
                    "url": event.request.url,
                    "method": event.request.method,
                    "timestamp": event.timestamp,
                    "type": event.type_.value if event.type_ else None
                })
        
        # Add handler
        tab.add_handler(cdp.network.RequestWillBeSent, request_handler)
        
        # Wait a bit to collect requests
        await asyncio.sleep(2)
        
        # Remove handler
        tab.remove_handlers(cdp.network.RequestWillBeSent, request_handler)

        return {
            "status": "success",
            "count": len(requests),
            "requests": requests[:50]  # Limit to 50 most recent
        }

    except Exception as e:
        logger.error(f"Network listing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ===========================
# Export Operations
# ===========================
@app.post("/garbo/page_markdown")
async def garbo_page_as_markdown(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    settings: Annotated[Settings, Depends(get_settings)],
    include_metadata: bool = Body(True, description="Include page metadata"),
    use_trafilatura: bool = Body(True, description="Use Trafilatura for better extraction")
):
    """Garbo current page content as markdown"""
    tab = await browser_manager.get_tab()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Get page URL and title
    current_url = await safe_evaluate(tab, "window.location.href")
    page_title = await safe_evaluate(tab, "document.title")
    
    # Extract content
    if use_trafilatura:
        # Use Trafilatura for high-quality extraction
        from app.services.extraction import UnifiedExtractionService
        extraction_service = UnifiedExtractionService(browser_manager, None)
        result = await extraction_service.extract_with_trafilatura(tab)
        
        if result and result.get("status") == "success":
            content = result["content"]["main_text"]
            metadata = result["metadata"]
        else:
            # Fallback to basic extraction
            content = await safe_evaluate(tab, "document.body.innerText")
            metadata = {"title": page_title, "url": current_url}
    else:
        # Basic extraction
        content = await safe_evaluate(tab, "document.body.innerText")
        metadata = {"title": page_title, "url": current_url}
    
    # Build markdown
    md_content = f"# {metadata.get('title', 'Untitled')}\n\n"
    
    if include_metadata:
        md_content += f"**URL:** {metadata.get('url', current_url)}\n"
        md_content += f"**Exported:** {datetime.now().isoformat()}\n"
        if metadata.get('author'):
            md_content += f"**Author:** {metadata['author']}\n"
        if metadata.get('date'):
            md_content += f"**Date:** {metadata['date']}\n"
        if metadata.get('description'):
            md_content += f"**Description:** {metadata['description']}\n"
        md_content += "\n---\n\n"
    
    # Add main content
    md_content += content if content else "No content extracted"
    
    # Save file to tmp directory (same pattern as screenshots)
    exports_dir = '/tmp/exports'
    os.makedirs(exports_dir, exist_ok=True)
    
    # Clean filename from title
    safe_title = re.sub(r'[^\w\s-]', '', page_title or 'page')[:50]
    filename = f"{timestamp}_{safe_title}.md"
    filepath = os.path.join(exports_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md_content)
    
    return {
        "status": "success",
        "filename": filename,
        "path": filepath,
        "size_bytes": len(md_content.encode('utf-8')),
        "url": current_url,
        "title": page_title
    }

@app.post("/screenshot")
async def take_screenshot(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    selector: Optional[str] = Body(None, description="CSS selector of element to screenshot"),
    full_page: bool = Body(False, description="Capture full page"),
    format: str = Body("png", description="jpeg or png")
):
    """Take screenshot of page or element"""
    tab = await browser_manager.get_tab()
    
    try:
        # Screenshot directory - use system /tmp (always writable)
        screenshot_dir = '/tmp/screenshots'
        os.makedirs(screenshot_dir, exist_ok=True)
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        screenshot_filename = f"screenshot_{timestamp}.{format}"
        screenshot_path = os.path.join(screenshot_dir, screenshot_filename)

        # Take screenshot
        if selector:
            element = await tab.find(selector, timeout=TIMEOUTS.element_find)
            if not element:
                raise ElementNotFoundError(f"Element not found: {selector}")
            filename = await element.save_screenshot(filename=screenshot_path, format=format)
        else:
            filename = await tab.save_screenshot(filename=screenshot_path, format=format, full_page=full_page)
        
        return {
            "status": "success",
            "path": filename,
            "format": format
        }
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
