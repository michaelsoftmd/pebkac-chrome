"""
Content extraction tools - copied from openapi-server/main.py
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


class ExtractContentTool(Tool):
    name = "extract_content"
    description = """Extract content from the CURRENT ACTIVE TAB (tab 0). Returns text and links.

IMPORTANT: Extracts from tab 0 only (the main tab).
- CANNOT extract from background tabs - use visit_webpage(url) instead
- Background tabs remain separate from automation

SELECTOR DISCOVERY:
Empty selector = automatic extraction (Trafilatura). For targeted extraction, discover selectors by:
1. Inspecting page structure (look for semantic HTML, data attributes, unique IDs)
2. Testing selectors incrementally (start broad, refine with classes/attributes)
3. Prefer specific selectors over generic ones

Flexible selector patterns to try:
- Products: '.product', '[data-product-id]', 'article[class*="product"]'
- Prices: '.price', '[data-price]', 'span[class*="price"]'
- Links: 'a[href*="keyword"]', '.link-container a', 'nav a'
- Text content: 'article', 'main', '.content', '[role="main"]'
- Attributes: '[data-*]', '[aria-label*="..."]', '[class*="..."]'

Avoid overly-generic selectors like 'a' or 'div' - be specific to get meaningful content.

Links are automatically extracted (hrefs included in results)."""
    inputs = {
        "selector": {
            "type": "string",
            "description": "CSS selector to extract from (leave empty for universal extraction)",
            "default": None,
            "nullable": True
        },
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_extraction)

    def forward(self, selector: str = None) -> str:
        """Extract content with timeout handling"""
        try:
            response = self.client.post(
                f"{self.api_url}/extraction/extract",
                json={
                    "selector": selector,
                    "extract_text": True,
                    "extract_all": False,
                    "extract_href": True
                }
            )

            if response.status_code == 200:
                data = response.json()
                # Handle universal extraction response format
                if data.get("status") == "success":
                    # Use compact formatted_output from our optimized extraction
                    formatted_output = data.get("formatted_output")
                    if formatted_output:
                        return formatted_output[:800]  # Limit to ~200 words

                    # Fallback to manual formatting
                    content = data.get("data")
                    if isinstance(content, list):
                        # Format list of elements
                        return f"Found {len(content)} elements: " + str(content[:5])[:800]
                    elif isinstance(content, dict):
                        text = content.get('text', '')[:600]  # Limit content
                        title = content.get('title', 'Unknown')[:50]
                        return f"Title: {title}\n\n{text}"
                    else:
                        return str(content)[:800]
                else:
                    raise Exception(f"Extraction failed: HTTP {response.status_code}")
            else:
                raise Exception("Unable to extract content - API unreachable")

        except httpx.TimeoutException:
            raise TimeoutError(f"Content extraction timed out after {TIMEOUTS.http_extraction}s")
        except Exception as e:
            # Generic error handling
            logger.warning(f"Extraction error: {e}")
            raise  # Let SmolAgents handle it


class ParallelExtractionTool(Tool):
    name = "extract_multiple"
    description = """Extract content from multiple CSS selectors in parallel for faster data gathering.

USE CASES:
- Extract product title + price + rating simultaneously: ['h2.product-title', 'span.price', 'div.rating']
- Get multiple page sections: ['main article', 'aside', 'footer']
- Extract different link types: ['a[href*="/product/"]', 'a[href*="/category/"]']
- Faster than calling extract_content multiple times sequentially

Returns aggregated results with cache statistics."""
    inputs = {
        "selectors": {"type": "array", "description": "List of CSS selectors to extract from simultaneously"}
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_extraction)

    def forward(self, selectors: List[str]) -> str:
        """Extract from multiple selectors in parallel"""
        try:
            response = self.client.post(
                f"{self.api_url}/extraction/parallel",
                json=selectors
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    results = data.get("data", {})
                    cached_count = data.get("cached_count", 0)
                    extracted_count = data.get("extracted_count", 0)

                    # Format results for agent understanding
                    output = f"Extracted from {len(results)} selectors "
                    output += f"({cached_count} cached, {extracted_count} fresh):\n\n"

                    for selector, content in results.items():
                        if content:
                            output += f"'{selector}': {content[:200]}...\n"
                        else:
                            output += f"'{selector}': (no content found)\n"

                    return output
                else:
                    return f"Parallel extraction failed: {data.get('error', 'Unknown error')}"
            else:
                return f"Failed to extract in parallel: {response.text}"

        except Exception as e:
            logger.error(f"Parallel extraction error: {e}")
            return f"Parallel extraction failed: {str(e)}"


class CapturePageMarkdownTool(Tool):
    name = "capture_page_markdown"
    description = """Capture the current page content as a markdown file for long-term storage.

FEATURES:
- Uses Trafilatura for intelligent content extraction
- Saves to /tmp/exports/ with timestamp and page title
- Includes metadata: URL, title, author, date, description
- Strips navigation, ads, and boilerplate content
- Preserves main article/page content

USE WHEN:
- Saving article/documentation for later reference
- Archiving research content
- Creating offline copies of important pages

Returns filename and file size, not the content itself."""
    inputs = {
        "include_metadata": {
            "type": "boolean",
            "description": "Include page metadata like author, date",
            "default": True,
            "nullable": True
        }
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_extraction)

    def forward(self, include_metadata: bool = True) -> str:
        """Capture current page as markdown"""
        try:
            response = self.client.post(
                f"{self.api_url}/capture/page_markdown",
                json={"include_metadata": include_metadata, "use_trafilatura": True}
            )

            if response.status_code == 200:
                data = response.json()
                return f"Page exported successfully: {data['filename']} ({data['size_bytes']} bytes) - Title: {data.get('title', 'Unknown')}"
            else:
                error_text = response.text
                logger.error(f"Export failed with status {response.status_code}: {error_text}")
                return f"Export failed: {error_text}"

        except Exception as e:
            logger.error(f"Export error: {e}")
            return f"Dump failed: {str(e)}"