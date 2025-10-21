"""
Network API response capture routes
"""

import asyncio
import json
import re
from typing import Annotated, Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from zendriver import cdp
from zendriver.cdp.network import get_response_body
import logging

from app.core.browser import BrowserManager
from app.api.dependencies import get_browser_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ===========================
# API Response Capture
# ===========================

class CaptureAPIRequest(BaseModel):
    action: str  # "navigate" or "click"
    url: Optional[str] = None
    selector: Optional[str] = None
    api_pattern: Optional[str] = None
    timeout: int = 5


@router.post("/api/capture_response")
async def capture_api_response(
    request: CaptureAPIRequest,
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)]
):
    """
    Capture API/AJAX responses during navigation or interaction.

    Performs an action (navigate or click) and captures matching JSON responses.
    If api_pattern is provided, returns first matching response.
    If api_pattern is omitted, returns all JSON responses (auto-discovery mode).
    """
    tab = await browser_manager.get_tab()
    captured_responses: List[Dict[str, Any]] = []

    try:
        # Enable network domain
        await tab.send(cdp.network.enable())

        # Handler to capture responses
        def response_handler(event):
            try:
                # Only process ResponseReceived events
                if not hasattr(event, 'response'):
                    return

                response = event.response

                # Check if matches pattern (if provided)
                if request.api_pattern:
                    if not re.search(request.api_pattern, response.url):
                        return

                # Check if JSON content type
                content_type = response.headers.get("content-type", "").lower()
                if "application/json" not in content_type and "text/json" not in content_type:
                    return

                # Capture this response
                captured_responses.append({
                    "request_id": event.request_id,
                    "url": response.url,
                    "status": response.status
                })

            except Exception as e:
                logger.warning(f"Error in response handler: {e}")

        # Add handler
        tab.add_handler(cdp.network.ResponseReceived, response_handler)

        try:
            # Perform action
            if request.action == "navigate":
                if not request.url:
                    raise HTTPException(status_code=400, detail="url required for navigate action")
                await tab.get(request.url)

            elif request.action == "click":
                if not request.selector:
                    raise HTTPException(status_code=400, detail="selector required for click action")
                element = await tab.select(request.selector)
                if not element:
                    raise HTTPException(status_code=404, detail=f"Element not found: {request.selector}")
                await element.click()

            else:
                raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

            # Wait for responses to be captured
            await asyncio.sleep(request.timeout)

        finally:
            # ALWAYS remove handler
            try:
                tab.remove_handler(cdp.network.ResponseReceived, response_handler)
            except Exception as e:
                logger.warning(f"Failed to remove response handler: {e}")

        # Fetch response bodies
        results: List[Dict[str, Any]] = []
        for captured in captured_responses:
            try:
                body, is_base64 = await tab.send(get_response_body(request_id=captured["request_id"]))

                if body:
                    # Try to parse as JSON
                    try:
                        data = json.loads(body)
                        results.append({
                            "url": captured["url"],
                            "status": captured["status"],
                            "data": data
                        })
                    except json.JSONDecodeError:
                        # Not valid JSON, skip
                        logger.debug(f"Response from {captured['url']} is not valid JSON")

            except Exception as e:
                logger.warning(f"Failed to get response body for {captured['url']}: {e}")

        # Return single response or array based on pattern
        if request.api_pattern and results:
            return results[0]  # First matching response
        elif request.api_pattern and not results:
            return {"error": f"No API responses matched pattern: {request.api_pattern}", "captured_count": 0}
        else:
            return results  # All JSON responses (auto-discovery mode)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API capture error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
