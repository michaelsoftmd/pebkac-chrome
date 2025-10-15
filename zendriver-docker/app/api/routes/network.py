"""
Network interception and monitoring routes
"""

import asyncio
from typing import Annotated, Optional
from fastapi import APIRouter, HTTPException, Body, Depends
from zendriver import cdp
from zendriver.core.intercept import BaseFetchInterception
from zendriver.cdp.fetch import RequestStage
from zendriver.cdp.network import ResourceType
import logging

from app.core.browser import BrowserManager
from app.api.dependencies import get_browser_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ===========================
# Network Intercept
# ===========================

@router.post("/intercept/start")
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

@router.post("/intercept/list")
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

        # Add handler with guaranteed cleanup
        tab.add_handler(cdp.network.RequestWillBeSent, request_handler)

        try:
            # Wait a bit to collect requests
            await asyncio.sleep(2)
        finally:
            # ALWAYS remove handler, even if exception occurs
            try:
                tab.remove_handlers(cdp.network.RequestWillBeSent, request_handler)
            except Exception as cleanup_error:
                logger.warning(f"Failed to remove network handler: {cleanup_error}")

        return {
            "status": "success",
            "count": len(requests),
            "requests": requests[:50]  # Limit to 50 most recent
        }

    except Exception as e:
        logger.error(f"Network listing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
