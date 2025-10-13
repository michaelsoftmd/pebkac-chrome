"""
Utility tools - copied from openapi-server/main.py
"""

import os
import logging
import httpx
from typing import List
from smolagents import Tool

# Timeout configuration - copy from original
class TIMEOUTS:
    http_request = int(os.getenv("TIMEOUT_HTTP_REQUEST", "5"))
    http_extraction = int(os.getenv("TIMEOUT_HTTP_EXTRACTION", "8"))
    page_load = int(os.getenv("TIMEOUT_PAGE_LOAD", "10"))

logger = logging.getLogger(__name__)


class ScreenshotTool(Tool):
    name = "take_screenshot"
    description = """Take a screenshot of the current page or specific element. Saves to /tmp/exports/.

USE CASES:
- Capture entire page: take_screenshot(full_page=True)
- Capture specific element: take_screenshot(selector=".product-details")
- Debug visual issues: Screenshot to verify element visibility
- Archive visual state: Save page appearance for later reference

FORMATS: PNG (default)
SAVES TO: /tmp/exports/ with timestamp filename

Returns path to saved screenshot file."""
    inputs = {
        "selector": {"type": "string", "description": "CSS selector of element to screenshot (optional)", "nullable": True},
        "full_page": {"type": "boolean", "description": "Capture full page", "default": False, "nullable": True}
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self, selector: str = None, full_page: bool = False) -> str:
        """Take screenshot and save to folder"""
        try:
            response = self.client.post(
                f"{self.api_url}/screenshot",
                json={"selector": selector, "full_page": full_page}
            )
            if response.status_code == 200:
                data = response.json()
                return f"Screenshot saved: {data.get('path', 'screenshot.jpg')}"
            return f"Failed to take screenshot"
        except Exception as e:
            return f"Screenshot failed: {str(e)}"


class GetElementPositionTool(Tool):
    name = "get_element_position"
    description = "Get the position and size of an element"
    inputs = {
        "selector": {"type": "string", "description": "CSS selector"},
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self, selector: str) -> str:
        """Get element position"""
        try:
            response = self.client.post(
                f"{self.api_url}/element/position",
                json={"selector": selector}
            )
            if response.status_code == 200:
                pos = response.json().get("position", {})
                return f"Position: x={pos.get('x')}, y={pos.get('y')}, width={pos.get('width')}, height={pos.get('height')}"
            return "Element not found"
        except Exception as e:
            return f"Position error: {str(e)}"


class InterceptNetworkTool(Tool):
    name = "intercept_network"
    description = """Intercept network requests matching a URL pattern. Currently limited to Document resource type.

ACTIONS:
- log: Monitor requests without blocking (default)
- block: Prevent requests from loading
- modify: Intercept and modify response (experimental)

URL PATTERNS:
- Wildcards: '*.jpg', '*api*', '*analytics*'
- Specific: 'https://example.com/api/*'

LIMITATIONS:
- Only intercepts Document resources (not XHR/Fetch)
- Single-use: Catches one request then stops
- Results not returned to agent (runs in background)

NOTE: For capturing dynamic AJAX data, see network-monitoring-proposal.md

Returns confirmation that interception started."""
    inputs = {
        "url_pattern": {"type": "string", "description": "URL pattern to intercept"},
        "action": {
            "type": "string",
            "description": "Action: block, modify, or log",
            "default": "log",
            "nullable": True
        }
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self, url_pattern: str, action: str = "log") -> str:
        """Start network interception"""
        try:
            response = self.client.post(
                f"{self.api_url}/intercept/start",
                json={
                    "url_pattern": url_pattern,
                    "resource_type": "Document",
                    "action": action
                }
            )
            if response.status_code == 200:
                data = response.json()
                return f"Interception started for pattern: {url_pattern} with action: {action}"
            return f"Failed to start interception"
        except Exception as e:
            return f"Interception error: {str(e)}"