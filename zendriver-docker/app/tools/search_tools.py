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
    description = """Search the web using various search engines. Returns dict with results array.

AFTER SEARCHING:
Analyze result relevance, then open 1-3 most valuable pages in background tabs for user.
Example: After searching reviews, open authoritative sites for user to explore.

ENGINES: duckduckgo (default), google, amazon, youtube, wikipedia, reddit, github, bing

PAGINATION:
- First call: web_search("query") → First page results
- More results: web_search("query", load_more=True) → Next page (must be on results page)
- Chain multiple load_more calls for additional pages

LIMITS:
- Default: 10 results per page
- Max: 50 results per call (use load_more for more)
- Adjust max_results for broader searches (20-50)

RETURNS: Dict with 'query', 'engine', 'results' (array of {title, url, domain})

NOT FOR NAVIGATION: Use navigate_browser to go directly to sites"""
    inputs = {
        "query": {"type": "string", "description": "Search query"},
        "engine": {
            "type": "string",
            "description": "Search engine: duckduckgo, google, amazon, youtube, wikipedia, reddit, github, bing",
            "default": "duckduckgo",
            "nullable": True
        },
        "load_more": {
            "type": "boolean",
            "description": "Click More Results/Next button to load next page. Only use after initial search on same query.",
            "default": False,
            "nullable": True
        },
        "site": {
            "type": "string",
            "description": "Site to search (optional, redundant with engine)",
            "default": None,
            "nullable": True
        },
        "max_results": {
            "type": "integer",
            "description": "Number of results to return per page (default: 10, max: 50). Use load_more for additional pages.",
            "default": None,
            "nullable": True
        }
    }
    output_type = "string"  # JSON string containing search results

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_extraction)

        # Load search configuration from environment
        self.max_results_default = int(os.getenv("SEARCH_MAX_RESULTS_DEFAULT", "10"))
        self.max_results_limit = int(os.getenv("SEARCH_MAX_RESULTS_LIMIT", "50"))
        self.search_configs = {
            "duckduckgo": {
                "url": "https://duckduckgo.com",
                "input_selector": "input[type='text'], input[type='search']",
                "more_results_selector": "button:has-text('More'), a:has-text('More')"
            },
            "google": {
                "url": "https://www.google.com",
                "input_selector": "input[type='text'], textarea[name='q']",
                "more_results_selector": "a:has-text('Next'), a[aria-label*='Next']"
            },
            "bing": {
                "url": "https://www.bing.com",
                "input_selector": "input[type='text'], input[type='search']",
                "more_results_selector": "a:has-text('Next'), a.sb_pagN"
            },
            "amazon": {
                "url": "https://www.amazon.com",
                "input_selector": "input[type='text']",
                "more_results_selector": "a:has-text('Next'), a.s-pagination-next"
            },
            "youtube": {
                "url": "https://www.youtube.com",
                "input_selector": "input[type='text'], input#search",
                "more_results_selector": None  # YouTube uses infinite scroll
            },
            "wikipedia": {
                "url": "https://en.wikipedia.org",
                "input_selector": "input[type='text'], input[type='search']",
                "more_results_selector": "a:has-text('next'), a.mw-nextlink"
            },
            "reddit": {
                "url": "https://www.reddit.com",
                "input_selector": "input[type='search'], input[type='text']",
                "more_results_selector": None  # Reddit uses infinite scroll
            },
            "github": {
                "url": "https://github.com",
                "input_selector": "input[type='text']",
                "more_results_selector": "a:has-text('Next'), a.next_page"
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

    def forward(self, query: str, engine: str = "duckduckgo", load_more: bool = False, site: str = None, max_results: int = None) -> str:
        """Execute web search"""
        try:
            # Apply max_results limit
            if max_results is None:
                max_results = self.max_results_default
            else:
                max_results = min(max_results, self.max_results_limit)

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

            # PAGINATION MODE: If load_more=True, skip navigation and just click More Results
            if load_more:
                more_selector = config.get("more_results_selector")

                if more_selector is None:
                    return f"Error: {detected_site} does not support pagination (uses infinite scroll)"

                # Click the More Results / Next button
                click_response = self.client.post(
                    f"{self.api_url}/interaction/click",
                    json={"selector": more_selector}
                )

                if click_response.status_code != 200:
                    return f"Error: Could not find More Results/Next button. Make sure you're on a results page from a previous search."

                # Wait for new results to load
                time.sleep(3)

                # Skip to extraction (reuse extraction logic below)
            else:
                # NORMAL SEARCH MODE: Navigate and perform search
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

            # Capture search results page URL to return to after extraction
            current_url_response = self.client.get(f"{self.api_url}/get_current_url")
            search_results_url = None
            if current_url_response.status_code == 200:
                search_results_url = current_url_response.json().get("url", "")
                logger.info(f"Captured search results URL: {search_results_url}")

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

                        # Skip navigation, tracking, and non-product links
                        skip_patterns = [
                            '/gp/help/',           # Help pages
                            '/gp/subs/',           # Subscriptions
                            '/hz5/',               # Account management
                            '/hz/mycd/',           # Content management
                            'aax-fe.amazon',       # Ad redirects
                            '/x/c/',               # Tracking redirects
                            'ref_=nav_',           # Navigation refs
                            'ref_=footer_',        # Footer refs
                            '/auto-deliveries',    # Subscribe & Save
                            '/gp/browse.html',     # Browse nodes (not products)
                        ]

                        if (href and text and
                            href.startswith("https://") and
                            len(text) > 20 and len(text) < 300 and
                            not any(domain in href.lower() for domain in search_engine_domains) and
                            not any(pattern in href for pattern in skip_patterns)):

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

            # Navigate back to search results page to ensure main tab stays on results
            # This allows user to reference results while exploring background tabs
            if search_results_url:
                logger.info(f"Returning to search results page: {search_results_url}")
                self.client.post(
                    f"{self.api_url}/navigate",
                    json={"url": search_results_url}
                )
                time.sleep(1)  # Brief wait for page to load

            # Return Python dict - SmolAgents will handle stringification
            # Note: No auto-opening of tabs - LLM decides which results to open based on relevance
            return {
                "query": search_terms,
                "engine": detected_site,
                "results": unique_results[:max_results]
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
    description = """Navigate to a URL and automatically extract its content. Combines navigation + extraction in one step.

USE THIS TOOL to extract content from multiple URLs. It navigates to each URL and extracts content.

FEATURES:
- Navigates to URL in tab 0 (main tab)
- Waits for page load
- Extracts main content using Trafilatura (strips nav/ads)
- Returns page title and content (up to 2000 chars)

USE CASES:
- Extract content from multiple search result URLs
- Get article/documentation content
- Quick content preview without manual extraction

Example - Extract from multiple URLs:
    results = web_search("best pizza Brisbane")
    for result in results["results"][:3]:
        content = visit_webpage(url=result["url"])
        print(content)

OPTIONAL:
- wait_for: CSS selector to wait for before extracting (for dynamic content)
- extract_text: Set to False to just navigate without extraction

ALTERNATIVE: Use navigate_browser + extract_content separately for more control"""
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