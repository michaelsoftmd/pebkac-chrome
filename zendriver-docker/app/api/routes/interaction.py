"""
User interaction routes (typing, scrolling, keyboard, elements)
"""

import asyncio
from typing import Annotated, Optional, Dict
from fastapi import APIRouter, HTTPException, Body, Depends
from pydantic import BaseModel, Field
from zendriver import cdp
from zendriver.cdp import input_ as cdp_input
from zendriver.core.keys import KeyEvents, SpecialKeys, KeyPressEvent
import logging

from app.core.browser import BrowserManager
from app.core.exceptions import ElementNotFoundError
from app.core.timeouts import TIMEOUTS
from app.api.dependencies import get_browser_manager
from app.utils.browser_utils import safe_evaluate

logger = logging.getLogger(__name__)

router = APIRouter()


# ===========================
# Request Models
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


# ===========================
# Type/Input and Keyboard Functionality
# ===========================

@router.post("/interaction/type")
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

@router.post("/interaction/keyboard")
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

@router.post("/interaction/scroll")
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

@router.post("/interaction/find_elements")
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

@router.post("/element/position")
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

@router.post("/interaction/tab_navigate")
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
