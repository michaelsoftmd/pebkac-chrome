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
    description = "Extract content from the current page"
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
                    "extract_all": False
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
    description = "Extract content from multiple CSS selectors in parallel for faster data gathering"
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


class GarboPageMarkdownTool(Tool):
    name = "garbo_page_markdown"
    description = "Garbo the current browser page content as a markdown file"
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
        """Garbo export current page as markdown"""
        try:
            response = self.client.post(
                f"{self.api_url}/garbo/page_markdown",
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