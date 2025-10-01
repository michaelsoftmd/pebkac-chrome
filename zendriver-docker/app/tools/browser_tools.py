"""
Browser automation tools - copied from openapi-server/main.py
"""

import os
import logging
import time
import httpx
from smolagents import Tool

# Timeout configuration - copy from original
class TIMEOUTS:
    http_request = int(os.getenv("TIMEOUT_HTTP_REQUEST", "5"))
    http_extraction = int(os.getenv("TIMEOUT_HTTP_EXTRACTION", "8"))
    page_load = int(os.getenv("TIMEOUT_PAGE_LOAD", "10"))

logger = logging.getLogger(__name__)


class NavigateBrowserTool(Tool):
    name = "navigate_browser"
    description = "Navigate to a URL using the browser"
    inputs = {
        "url": {"type": "string", "description": "URL to navigate to"},
        "force_refresh": {
            "type": "boolean",
            "description": "Force refresh bypassing cache",
            "default": False,
            "nullable": True
        },
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self, url: str, force_refresh: bool = False) -> str:
        """Navigate to URL using synchronous httpx with timeout handling"""
        # Validate URL first
        if not url.startswith(('http://', 'https://')):
            # Try to add https://
            url = f'https://{url}'

        # Check if this looks like search results instead of a URL
        if '\n' in url or 'Web Search Results' in url or '# Web Search Results' in url:
            return "Error: It appears you're trying to navigate to search results text. Please extract a specific URL from the search results first."

        try:
            response = self.client.post(
                f"{self.api_url}/navigate",
                json={"url": url, "force_refresh": force_refresh},
                timeout=TIMEOUTS.page_load
            )

            if response.status_code == 200:
                return f"Successfully navigated to {url}"
            else:
                # Don't return error string, raise exception
                raise Exception(f"Navigation failed: HTTP {response.status_code}")

        except httpx.TimeoutException:
            # Let SmolAgents see the actual timeout
            raise TimeoutError(f"Navigation timed out after {TIMEOUTS.page_load}s: {url}")
        except Exception as e:
            logger.warning(f"Navigation error: {e}")
            raise  # Let SmolAgents handle it


class GetCurrentURLTool(Tool):
    name = "get_current_url"
    description = "Get the current URL of the browser tab"
    inputs = {
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self) -> str:
        """Get current URL using synchronous httpx"""
        try:
            response = self.client.get(f"{self.api_url}/get_current_url")
            if response.status_code == 200:
                data = response.json()
                return data.get("url", "unknown")
            return "Failed to get current URL"
        except Exception as e:
            logger.error(f"Get URL error: {e}")
            return f"Error: {str(e)}"


class ClickElementTool(Tool):
    name = "click_element"
    description = "Click an element on the page"
    inputs = {
        "selector": {
            "type": "string",
            "description": "CSS selector or text to click",
            "nullable": True
        },
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self, selector: str = "body") -> str:
        """Click element using synchronous httpx"""
        try:
            response = self.client.post(
                f"{self.api_url}/click",
                json={
                    "selector": selector if selector != "body" else None
                },
            )

            if response.status_code == 200:
                return f"Successfully clicked element: {selector}"
            else:
                return f"Failed to click: {response.text}"

        except Exception as e:
            logger.error(f"Click error: {e}")
            raise  # Let SmolAgents handle the error


class TypeTextTool(Tool):
    name = "type_text"
    description = "Type text into an input field"
    inputs = {
        "text": {"type": "string", "description": "Text to type"},
        "selector": {
            "type": "string",
            "description": "CSS selector of input field (optional - uses focused element if not provided)",
            "default": None,
            "nullable": True
        },
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self, text: str, selector: str = None) -> str:
        """Type text using synchronous httpx"""
        try:
            response = self.client.post(
                f"{self.api_url}/interaction/type",
                json={
                    "text": text,
                    "selector": selector,
                    "clear_first": True,
                },
            )

            if response.status_code == 200:
                result = "Successfully typed text"
                return result
            else:
                return f"Failed to type: {response.text}"

        except Exception as e:
            logger.error(f"Type error: {e}")
            return f"Type failed: {str(e)}"


class KeyboardNavigationTool(Tool):
    """A helper for all TYPETEXT and WEBSEARCH tools. Press Enter, Tab, Escape, Arrow Keys"""
    name = "keyboard_navigate"
    description = "Press keys like Tab, Escape, Arrow keys, etc."
    inputs = {
        "key": {
            "type": "string",
            "description": "Key to press: Tab, Enter, Escape, ArrowUp, ArrowDown, ArrowLeft, ArrowRight, PageUp, PageDown, Home, End, Backspace, Delete, Space"
        }
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self, key: str) -> str:
        """Send navigation key"""
        try:
            response = self.client.post(
                f"{self.api_url}/interaction/keyboard",
                json={"key": key}
            )

            if response.status_code == 200:
                return f"Pressed {key} key successfully"
            else:
                return f"Failed to press {key}: {response.text}"

        except Exception as e:
            logger.error(f"Navigation error: {e}")
            return f"Navigation failed: {str(e)}"