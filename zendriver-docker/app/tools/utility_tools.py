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


class CaptureAPIResponseTool(Tool):
    name = "capture_api_response"
    description = """Capture API/AJAX response data during navigation or interaction.

Modern websites load data via JavaScript APIs instead of rendering it in HTML.
This tool captures those API responses as structured JSON, which is often cleaner
and more reliable than extracting from HTML.

Args:
    action: "navigate" to load a URL, or "click" to click an element
    url: URL to navigate to (required if action="navigate")
    selector: Element to click (required if action="click")
    api_pattern: Regex to match API URLs (optional - if omitted, captures all JSON responses)
    timeout: Seconds to wait for API response (default: 5)

Returns:
    If api_pattern provided: {"url": "...", "data": {...}} - single response
    If api_pattern omitted: [{"url": "...", "data": {...}}, ...] - all JSON responses

Common API patterns:
    - Product data: ".*/api/product/.*"
    - Search results: ".*/search.*" or ".*autocomplete.*"
    - User data: ".*/api/user/.*" or ".*/api/me"
    - GraphQL: ".*/graphql"
    - Any JSON file: ".*\\.json$"
    - Any API: ".*/api/.*"

Examples:
    # Get product data (know the pattern)
    data = capture_api_response(
        action="navigate",
        url="https://amazon.com/product/B08XYZ",
        api_pattern=".*/api/product/.*"
    )
    # Returns: {"url": "https://api.amazon.com/product/B08XYZ", "data": {"price": 348.00, ...}}

    # Explore all APIs (auto-discovery mode)
    responses = capture_api_response(
        action="navigate",
        url="https://example.com/search?q=headphones"
    )
    # Returns: [{"url": "...", "data": {...}}, {"url": "...", "data": {...}}, ...]

    # Capture infinite scroll data
    data = capture_api_response(
        action="click",
        selector=".load-more",
        api_pattern=".*/api/posts.*"
    )

Why use this instead of extract_content?
    - Structured JSON data vs messy HTML extraction
    - More reliable (API contracts more stable than HTML selectors)
    - Faster (single JSON parse vs multiple DOM queries)
    - More complete (APIs often return data not shown in UI)
"""
    inputs = {
        "action": {
            "type": "string",
            "description": "'navigate' to load URL or 'click' to click element"
        },
        "url": {
            "type": "string",
            "description": "URL to navigate to (if action='navigate')",
            "nullable": True
        },
        "selector": {
            "type": "string",
            "description": "CSS selector to click (if action='click')",
            "nullable": True
        },
        "api_pattern": {
            "type": "string",
            "description": "Regex pattern to match API URL (optional - omit to capture all JSON)",
            "nullable": True
        },
        "timeout": {
            "type": "integer",
            "description": "Seconds to wait for API response (default: 5)",
            "default": 5,
            "nullable": True
        }
    }
    output_type = "any"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=30)  # Longer timeout for API capture

    def forward(self, action: str, url: str = None, selector: str = None,
                api_pattern: str = None, timeout: int = 5):
        """Capture API responses during action"""
        try:
            response = self.client.post(
                f"{self.api_url}/api/capture_response",
                json={
                    "action": action,
                    "url": url,
                    "selector": selector,
                    "api_pattern": api_pattern,
                    "timeout": timeout
                },
                timeout=timeout + 10  # Extra time for HTTP overhead
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "error": f"API capture failed with status {response.status_code}",
                    "detail": response.text
                }
        except Exception as e:
            return {
                "error": f"API capture error: {str(e)}"
            }