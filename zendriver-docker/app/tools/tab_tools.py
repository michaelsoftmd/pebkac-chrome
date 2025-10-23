"""
Background tab management tools for multi-URL operations.

These tools allow opening content in background tabs while keeping the main tab (tab 0) active.
Tab 0 is the persistent "active" tab and CANNOT be closed - only background tabs can be closed.
"""

import httpx
from typing import Dict, Any
from smolagents import Tool


class OpenBackgroundTabTool(Tool):
    name = "open_background_tab"
    description = """Open valuable pages in background tabs AFTER extracting their content.

    IMPORTANT: Tab 0 is the ONLY operable tab. Tabs 1-3 are background tabs for user exploration.
    Maximum 3 background tabs should be opened.

    WORKFLOW:
    1. Extract content from URLs using visit_webpage()
    2. Analyze which pages are most valuable
    3. Open those valuable pages (max 3) in background tabs for user

    You should already know what's on the page before opening it in a background tab.

    Example: After visiting 5 review sites, open the 2-3 best ones for user to read in full.

    Note: Background tabs are read-only for the user - only tab 0 is operable for automation.
    """

    inputs = {
        "url": {"type": "string", "description": "URL to open in background tab"}
    }
    output_type = "any"

    def __init__(self, api_url: str = "http://localhost:8080"):
        super().__init__()
        self.api_url = api_url

    def forward(self, url: str) -> Dict[str, Any]:
        """Open URL in background tab"""
        endpoint = f"{self.api_url}/tabs/open_background"

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(endpoint, json={"url": url})
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            return {"error": f"Failed to open background tab: {str(e)}", "url": url}


class ListTabsTool(Tool):
    name = "list_tabs"
    description = """List all open browser tabs with their URLs and indices.

    Returns information about all tabs including:
    - Tab index (0 = main tab, 1+ = background tabs)
    - Current URL
    - Whether it's the main tab
    - Whether it can be closed (only background tabs are closeable)

    Returns:
        Dict with total_tabs count and list of tab details

    Example usage:
        tabs_info = list_tabs()
        print(f"Total tabs: {tabs_info['total_tabs']}")
        for tab in tabs_info['tabs']:
            print(f"Tab {tab['index']}: {tab['url']}")
    """

    inputs = {}
    output_type = "any"

    def __init__(self, api_url: str = "http://localhost:8080"):
        super().__init__()
        self.api_url = api_url

    def forward(self) -> Dict[str, Any]:
        """List all tabs"""
        endpoint = f"{self.api_url}/tabs/list"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(endpoint)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            return {"error": f"Failed to list tabs: {str(e)}", "tabs": []}


class CloseTabTool(Tool):
    name = "close_tab"
    description = """Close a background tab by its index.

    SAFETY CONSTRAINT: Cannot close tab 0 (the main/active tab). Only background tabs
    (index >= 1) can be closed. Attempting to close tab 0 will return an error.

    Args:
        tab_index: Index of the tab to close (must be >= 1)

    Returns:
        Dict with status and remaining tab count

    Example usage:
        # Open some background tabs
        open_background_tab(url="https://example.com/page1")
        open_background_tab(url="https://example.com/page2")

        # List tabs to see indices
        tabs = list_tabs()

        # Close a specific background tab
        close_tab(tab_index=1)

    Note: Tab indices may shift after closing. Always use list_tabs() to get current indices.
    """

    inputs = {
        "tab_index": {"type": "integer", "description": "Index of tab to close (must be >= 1, cannot be 0)"}
    }
    output_type = "any"

    def __init__(self, api_url: str = "http://localhost:8080"):
        super().__init__()
        self.api_url = api_url

    def forward(self, tab_index: int) -> Dict[str, Any]:
        """Close a background tab"""
        # Client-side safety check to prevent accidental calls
        if tab_index == 0:
            return {
                "error": "Cannot close main tab (tab 0). Only background tabs can be closed.",
                "status": "error"
            }

        endpoint = f"{self.api_url}/tabs/close"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(endpoint, json={"tab_index": tab_index})
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                return {"error": e.response.json().get("detail", str(e)), "status": "error"}
            return {"error": f"Failed to close tab: {str(e)}", "status": "error"}
        except httpx.HTTPError as e:
            return {"error": f"Failed to close tab: {str(e)}", "status": "error"}
