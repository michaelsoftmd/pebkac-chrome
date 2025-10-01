"""
Search and web navigation tools - copied from openapi-server/main.py
"""

import os
import logging
import time
import httpx
import re
from typing import Optional
from smolagents import Tool
from urllib.parse import urlparse

# Timeout configuration - copy from original
class TIMEOUTS:
    http_request = int(os.getenv("TIMEOUT_HTTP_REQUEST", "5"))
    http_extraction = int(os.getenv("TIMEOUT_HTTP_EXTRACTION", "8"))
    page_load = int(os.getenv("TIMEOUT_PAGE_LOAD", "10"))

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    name = "web_search"
    description = """Search the web using various search engines OR search within specific sites. Returns Python dict with results array.
    Examples:
    - 'laptops' -> searches DuckDuckGo for laptops
    - 'search google for laptops' -> searches Google for laptops
    - 'laptops on amazon' -> searches within Amazon for laptops
    - Returns: Either JSON or Python dict with 'query', 'engine', and 'results' keys
    - Access results like: urls = [r['url'] for r in search_result['results']]
    - For navigation to specific sites, use navigate_browser tool instead."""
    inputs = {
        "query": {"type": "string", "description": "Search query"},
        "engine": {
            "type": "string",
            "description": "Search engine: duckduckgo, google, amazon, youtube, wikipedia, reddit, github, bing",
            "default": "duckduckgo",
            "nullable": True
        },
        "site": {
            "type": "string",
            "description": "Site to search (optional, redundant with engine)",
            "default": None,
            "nullable": True
        }
    }
    output_type = "string"  # JSON string containing search results

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_extraction)
        self.search_configs = {
            "duckduckgo": {
                "url": "https://duckduckgo.com",
                "input_selector": "input[name='q']",
                "result_selectors": ["a[href]", "h2 a", ".result__a"]
            },
            "google": {
                "url": "https://www.google.com",
                "input_selector": "input[name='q'], textarea[name='q']",
                "result_selectors": ["h3", "a[jsname]", ".g a"]
            },
            "bing": {
                "url": "https://www.bing.com",
                "input_selector": "input[name='q']",
                "result_selectors": ["h2 a", ".b_algo h2 a", "cite"]
            },
            "amazon": {
                "url": "https://www.amazon.com",
                "input_selector": "input#twotabsearchtextbox",
                "result_selectors": ["div[data-component-type='s-search-result']", "h2 a"]
            },
            "youtube": {
                "url": "https://www.youtube.com",
                "input_selector": "input#search",
                "result_selectors": ["ytd-video-renderer", "a#video-title"]
            },
            "wikipedia": {
                "url": "https://en.wikipedia.org",
                "input_selector": "input[name='search']",
                "result_selectors": [".mw-search-result-heading", ".searchmatch"]
            },
            "reddit": {
                "url": "https://www.reddit.com",
                "input_selector": "input[type='search']",
                "result_selectors": ["div[data-testid='post-container']", "a[data-click-id='body']"]
            },
            "github": {
                "url": "https://github.com",
                "input_selector": "input[type='text'][placeholder*='Search']",
                "result_selectors": [".repo-list-item", "a.Link--primary"]
            }
        }

    def parse_search_intent(self, query: str):
        """Better pattern matching"""
        # First check if this is actually a navigation request (wrong tool!)
        nav_patterns = [
            r"^(go to|navigate to|open|visit)\s+(\S+)",
            r"^(\w+)\.(com|org|net|io|co|gov)",
        ]
        for pattern in nav_patterns:
            if re.match(pattern, query, re.IGNORECASE):
                # This should use NavigateBrowserTool instead!
                return "navigation_request", query

        # Now check for search patterns
        # Check if query explicitly mentions a search engine/site
        site_keywords = {
            "google": "google",
            "bing": "bing",
            "amazon": "amazon",
            "youtube": "youtube",
            "wikipedia": "wikipedia",
            "reddit": "reddit",
            "github": "github"
        }

        query_lower = query.lower()
        detected_site = "duckduckgo"  # default
        search_terms = query  # default to full query

        # Look for "search [site] for [terms]" pattern
        match = re.search(r"search\s+(\w+)\s+for\s+(.+)", query_lower)
        if match:
            potential_site = match.group(1)
            if potential_site in site_keywords:
                detected_site = potential_site
                search_terms = match.group(2)
                return detected_site, search_terms

        # Look for "[terms] on [site]" pattern
        match = re.search(r"(.+)\s+on\s+(\w+)$", query_lower)
        if match:
            potential_site = match.group(2)
            if potential_site in site_keywords:
                detected_site = potential_site
                search_terms = match.group(1)
                return detected_site, search_terms

        # No pattern matched - use full query on default engine
        return detected_site, query

    def forward(self, query: str, engine: str = "duckduckgo", site: str = None) -> str:
        """Execute web search"""
        try:
            # Use engine parameter if provided, otherwise parse intent from query
            if engine and engine != "duckduckgo":
                # Use the provided engine
                detected_site = engine
                search_terms = query
            else:
                # Parse intent from query text
                detected_site, search_terms = self.parse_search_intent(query)

                # Check if this was a navigation request (wrong tool!)
                if detected_site == "navigation_request":
                    return "Error: This appears to be a navigation request. Please use the navigate_browser tool instead for going to specific websites."

            # Continue with search...
            config = self.search_configs.get(detected_site, self.search_configs["duckduckgo"])

            # Check if we're already on the search engine to avoid unnecessary navigation
            current_url_response = self.client.get(f"{self.api_url}/get_current_url")
            should_navigate = True

            if current_url_response.status_code == 200:
                current_url = current_url_response.json().get("url", "")
                if config["url"] in current_url:
                    # We're already on this search engine, navigate to homepage first to reset state
                    logger.debug(f"Already on {detected_site}, navigating to homepage to reset state")

            # Navigate to the search site (always navigate to ensure clean state)
            nav_response = self.client.post(
                f"{self.api_url}/navigate",
                json={"url": config["url"]}
            )

            if nav_response.status_code != 200:
                return f"Navigation failed: {nav_response.status_code}"

            time.sleep(2)

            # If no search query, just stay on homepage
            if not search_terms:
                return f"Navigated to {detected_site} homepage"

            # Type search query
            type_response = self.client.post(
                f"{self.api_url}/interaction/type",
                json={
                    "text": search_terms,
                    "selector": config["input_selector"],
                    "clear_first": True
                }
            )

            if type_response.status_code != 200:
                return f"Failed to type query: {type_response.status_code}"

            time.sleep(0.3)

            # Press Enter
            enter_response = self.client.post(
                f"{self.api_url}/interaction/keyboard",
                json={"key": "Enter"}
            )

            if enter_response.status_code != 200:
                return f"Failed to press Enter: {enter_response.status_code}"

            # Wait for results to load
            time.sleep(3)

            # Extract results
            extract_response = self.client.post(
                f"{self.api_url}/extraction/extract",
                json={
                    "selector": "a[href]",
                    "extract_all": True,
                    "extract_text": True,
                    "extract_href": True
                }
            )

            search_results = []
            if extract_response.status_code == 200:
                data = extract_response.json()
                if data.get("status") == "success" and data.get("data"):
                    for item in data["data"]:
                        if not isinstance(item, dict):
                            continue
                        href = item.get("href", "")
                        text = item.get("text", "").strip()

                        # Filter for actual result links
                        search_engine_domains = ["duckduckgo", "duck.co", "google.com", "bing.com"]
                        if (href and text and
                            href.startswith("https://") and
                            len(text) > 20 and len(text) < 300 and
                            not any(domain in href.lower() for domain in search_engine_domains)):

                            search_results.append({
                                "title": text[:150],
                                "url": href
                            })

            # Deduplicate by URL
            seen_urls = set()
            unique_results = []
            for result in search_results:
                if result["url"] not in seen_urls:
                    seen_urls.add(result["url"])
                    # Add domain for context
                    result["domain"] = urlparse(result["url"]).netloc
                    unique_results.append(result)

            # Return Python dict - SmolAgents will handle stringification
            return {
                "query": search_terms,
                "engine": detected_site,
                "results": unique_results[:10]
            }

        except Exception as e:
            logger.error(f"Search error: {e}")
            return f"Search failed: {str(e)}"


class SearchHistoryTool(Tool):
    name = "search_history"
    description = "Get search history from cache"
    inputs = {}
    output_type = "string"

    def __init__(self, duckdb_url: str):
        super().__init__()
        self.duckdb_url = duckdb_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)

    def forward(self) -> str:
        """Get cached search history using synchronous httpx"""
        try:
            response = self.client.get(f"{self.duckdb_url}/cache/stats")
            if response.status_code == 200:
                data = response.json()
                return f"Cache stats: {data.get('total_pages', 0)} pages cached"
            return "No cache history available"
        except Exception as e:
            return f"Failed to get history: {str(e)}"


class VisitWebpageTool(Tool):
    name = "visit_webpage"
    description = "Visit a webpage and return its content"
    inputs = {
        "url": {"type": "string", "description": "URL to visit"},
        "wait_for": {"type": "string", "description": "CSS selector to wait for", "nullable": True, "default": None},
        "extract_text": {"type": "boolean", "description": "Extract text content", "default": True, "nullable": True}
    }
    output_type = "string"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.page_load)

    def forward(self, url: str, wait_for: str = None, extract_text: bool = True) -> str:
        """Visit webpage and extract content"""
        try:
            # Navigate to the page
            nav_response = self.client.post(
                f"{self.api_url}/navigate",
                json={"url": url, "wait_for": wait_for, "wait_timeout": 10}
            )

            if nav_response.status_code != 200:
                return f"Failed to navigate to {url}"

            nav_data = nav_response.json()
            page_title = nav_data.get('title', 'Unknown')

            if extract_text:
                # Extract page content - use regular extract for reliability
                # Custom extractors "all" and "href" are new, will cause weird, potentially undesirable behaviour
                extract_response = self.client.post(
                    f"{self.api_url}/extraction/extract",
                    json={
                        "selector": None,
                        "extract_text": True,
                        "extract_all": True,
                        "extract_href": True,
                    }
                )

                if extract_response.status_code == 200:
                    extract_data = extract_response.json()
                    content = extract_data.get("data")

                    # Handle the response properly
                    if content:
                        if isinstance(content, dict):
                            text = content.get('text', '')
                            if text:
                                return f"Page title: {page_title}\n\nContent:\n{text[:2000]}..."
                        elif isinstance(content, str):
                            return f"Page title: {page_title}\n\nContent:\n{content[:2000]}..."

                    # If no content extracted, still return with page title
                    return f"Page title: {page_title}\n\nContent: (No text extracted)"
                else:
                    # If extraction failed, return navigation success with error info
                    return f"Page title: {page_title}\n\nContent extraction failed (status: {extract_response.status_code})"

            # This should never be reached due to extract_text logic above
            return f"Successfully visited {url} - Title: {page_title}"

        except Exception as e:
            logger.error(f"Visit webpage error: {e}")
            return f"Failed to visit {url}: {str(e)}"