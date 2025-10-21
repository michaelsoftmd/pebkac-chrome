"""
Browser navigation and control routes
"""

from typing import Annotated
from fastapi import APIRouter, HTTPException, Body, Depends, status
import logging

from app.core.browser import BrowserManager
from app.core.exceptions import BrowserError, ElementNotFoundError
from app.core.timeouts import TIMEOUTS
from app.models.requests import NavigationRequest, ClickRequest, OpenBackgroundTabRequest, CloseTabRequest
from app.services.element import ElementService
from app.api.dependencies import get_browser_manager, get_element_service
from app.utils.browser_utils import safe_evaluate

logger = logging.getLogger(__name__)

router = APIRouter()


# ===========================
# Navigation Routes
# ===========================

@router.post("/navigate")
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

@router.post("/click")
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
    """Cloudflare challenge detection logic"""
    return await safe_evaluate(tab, """
        (() => {
            const indicators = {
                hasCfRay: !!document.querySelector('meta[name="cf-ray"]'),
                hasChallengeForm: !!document.querySelector('form#challenge-form, form[action*="cdn-cgi"]'),
                titleHasCloudflare: /cloudflare|checking|just a moment|checking your browser/i.test(document.title || ''),
                hasCfScript: Array.from(document.scripts || []).some(s =>
                    s.src && s.src.includes('cloudflare')),
                bodyTextCloudflare: /checking your browser|just a moment|please wait|ddos protection by cloudflare|ray id/i.test(document.body?.innerText || '')
            };
            return indicators;
        })()
    """)

async def _determine_challenge_type(indicators):
    """Determine if Cloudflare challenge is present"""
    if not indicators or not isinstance(indicators, dict):
        return "none", False

    is_cloudflare = any([
        indicators.get('titleHasCloudflare', False),
        indicators.get('hasChallengeForm', False),
        indicators.get('hasCfScript', False),
        indicators.get('bodyTextCloudflare', False)
    ])

    challenge_type = "cloudflare" if is_cloudflare else "none"

    return challenge_type, is_cloudflare

@router.get("/cloudflare/detect")
async def detect_cloudflare(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)]
):
    """Check if current page has Cloudflare challenge"""
    tab = await browser_manager.get_tab()

    try:
        from app.utils.browser_utils import safe_evaluate

        # Use challenge detection
        indicators = await _get_challenge_indicators(tab)
        challenge_type, is_cloudflare = await _determine_challenge_type(indicators)

        # Additional check for Cloudflare interactive challenges
        if is_cloudflare:
            from app.core.cloudflare import cf_is_interactive_challenge_present
            has_cf_interactive = await cf_is_interactive_challenge_present(tab, timeout=TIMEOUTS.element_find)
            if has_cf_interactive:
                challenge_type = "cloudflare_interactive"
        else:
            has_cf_interactive = False

        return {
            "status": "challenge_detected" if is_cloudflare else "no_challenge",
            "has_cloudflare": is_cloudflare,
            "has_challenge": has_cf_interactive,
            "challenge_type": challenge_type,
            "indicators": indicators or {}
        }

    except Exception as e:
        logger.error(f"Cloudflare detection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "detection_failed", "message": str(e)}
        )

@router.post("/cloudflare/solve")
async def solve_cloudflare_challenge(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    timeout: int = Body(15, description="Timeout for solving challenge"),
    click_delay: float = Body(5, description="Delay between clicks")
):
    """Attempt to solve Cloudflare challenge if present"""
    tab = await browser_manager.get_tab()

    try:
        from app.utils.browser_utils import safe_evaluate

        # Use challenge detection
        indicators = await _get_challenge_indicators(tab)
        challenge_type, is_cloudflare_page = await _determine_challenge_type(indicators)

        # Solve Cloudflare challenge
        if is_cloudflare_page:
            from app.core.cloudflare import verify_cf
            await verify_cf(tab, click_delay=click_delay, timeout=timeout)
            return {
                "status": "success",
                "message": "Cloudflare challenge solved",
                "type": "cloudflare"
            }

        # No challenge found
        return {
            "status": "no_challenge",
            "message": "No Cloudflare challenge found"
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
# Cookie Management
# ===========================

@router.post("/cookies/save")
async def save_cookies(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    file: str = "cookies.dat"
):
    """Save browser cookies to file"""
    browser = await browser_manager.get_browser()
    await browser.cookies.save(file)
    return {"status": "saved", "file": file}

@router.post("/cookies/load")
async def load_cookies(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    file: str = "cookies.dat"
):
    """Load cookies from file"""
    browser = await browser_manager.get_browser()
    await browser.cookies.load(file)
    return {"status": "loaded", "file": file}


# ===========================
# Tab Management
# ===========================

@router.post("/tabs/open_background")
async def open_background_tab(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    request: OpenBackgroundTabRequest
):
    """
    Open a URL in a new background tab while keeping tab 0 (main tab) active.

    This allows loading content in background without interrupting the main workflow.
    The new tab will load but tab 0 will remain the active/focused tab.
    """
    try:
        # Use BrowserManager service layer
        tab_index, total_tabs = await browser_manager.create_background_tab(str(request.url))

        return {
            "status": "success",
            "message": f"Opened {request.url} in background tab",
            "tab_index": tab_index,
            "total_tabs": total_tabs
        }
    except Exception as e:
        logger.error(f"Failed to open background tab: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to open background tab: {str(e)}"
        )


@router.get("/tabs/list")
async def list_tabs(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)]
):
    """
    List all open tabs with their URLs and indices.

    Tab 0 is the main/active tab and cannot be closed.
    """
    try:
        browser = await browser_manager.get_browser()
        tabs = browser.tabs

        tab_list = []
        for idx, tab in enumerate(tabs):
            try:
                # Get URL safely
                url = await safe_evaluate(tab, "window.location.href") or "about:blank"
            except Exception:
                url = "unknown"

            tab_list.append({
                "index": idx,
                "url": url,
                "is_main_tab": idx == 0,
                "closeable": idx != 0  # Only background tabs are closeable
            })

        return {
            "total_tabs": len(tabs),
            "tabs": tab_list
        }
    except Exception as e:
        logger.error(f"Failed to list tabs: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list tabs: {str(e)}"
        )


@router.post("/tabs/close")
async def close_tab(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    request: CloseTabRequest
):
    """
    Close a background tab by index.

    SAFETY CONSTRAINT: Cannot close tab 0 (the main/active tab).
    Only background tabs (index >= 1) can be closed.
    """
    # Safety check: NEVER allow closing tab 0 (already validated by pydantic)
    if request.tab_index == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot close main tab (tab 0). Only background tabs can be closed."
        )

    try:
        browser = await browser_manager.get_browser()
        tabs = browser.tabs

        # Validate tab index
        if request.tab_index < 0 or request.tab_index >= len(tabs):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tab index {request.tab_index}. Valid range: 1-{len(tabs)-1}"
            )

        # Close the tab
        tab_to_close = tabs[request.tab_index]
        await tab_to_close.close()

        # Ensure main tab is active
        if len(tabs) > 1:
            main_tab = tabs[0]
            await main_tab.activate()

        return {
            "status": "success",
            "message": f"Closed tab {request.tab_index}",
            "remaining_tabs": len(tabs) - 1
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to close tab {request.tab_index}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to close tab: {str(e)}"
        )
