# OpenAPI Tools Server

A FastAPI server that bridges SmolAgents with browser automation tools via Zendriver.

## Features
- Browser automation through Zendriver
- SmolAgents integration for AI-powered tool use
- Redis caching (L1)
- DuckDB storage (L2)
- Compatible with local LLMs via llama.cpp

## Usage
This service is designed to run as part of the podman-compose stack.

## API Documentation
Navigation Endpoints
Navigate to URL
POST /navigate
Content-Type: application/json

{
  "url": "https://example.com",
  "wait_for": "h1.title",        // Optional: CSS selector to wait for
  "wait_timeout": 10,             // Optional: Timeout in seconds
  "force_refresh": false          // Optional: Bypass cache
}

Response:
{
  "status": "success",
  "url": "https://example.com",
  "title": "Example Domain"
}
Get Current URL
GET /get_current_url

Response:
{
  "status": "success",
  "url": "https://example.com/page",
  "title": "Current Page Title"
}
Content Extraction Endpoints
Extract Content
POST /extraction/extract
Content-Type: application/json

{
  "selector": "article.main",      // Optional: CSS selector
  "xpath": "//div[@class='content']", // Optional: XPath selector
  "extract_all": false,            // Extract all matching elements
  "extract_text": true,            // Extract text content
  "extract_href": false,           // Extract link URLs
  "use_cache": true,               // Use cached results
  "include_metadata": true         // Include metadata
}

Response:
{
  "status": "success",
  "data": {
    "text": "Extracted content...",
    "title": "Article Title",
    "metadata": {
      "author": "John Doe",
      "date": "2024-01-01",
      "description": "Article description"
    }
  },
  "formatted_output": "Formatted for LLM context",
  "cached": false,
  "extraction_method": "trafilatura"
}
Parallel Extraction
POST /extraction/parallel
Content-Type: application/json

["h1.title", "div.price", "span.rating", "p.description"]

Response:
{
  "status": "success",
  "data": {
    "h1.title": "Product Name",
    "div.price": "$99.99",
    "span.rating": "4.5 stars",
    "p.description": "Product description..."
  },
  "cached_count": 2,
  "extracted_count": 2
}
Interaction Endpoints
Click Element
POST /click
Content-Type: application/json

{
  "selector": "button.submit",    // CSS selector
  "text": "Submit",               // Or click by text
  "wait_after": 1.0               // Wait after clicking (seconds)
}

Response:
{
  "status": "success",
  "message": "Element clicked successfully"
}
Type Text
POST /interaction/type
Content-Type: application/json

{
  "text": "Hello World",
  "selector": "input[name='search']",  // Target input field
  "clear_first": true,                 // Clear field before typing
  "press_enter": false,                // Press Enter after typing
  "delay": 0.045                       // Delay between keystrokes
}

Response:
{
  "status": "success",
  "message": "Typed text: Hello World"
}
Keyboard Navigation
POST /interaction/keyboard
Content-Type: application/json

{
  "key": "Tab"  // Tab, Enter, Escape, ArrowUp, ArrowDown, etc.
}

Response:
{
  "status": "success",
  "message": "Pressed key: Tab"
}
Scroll Page
POST /interaction/scroll
Content-Type: application/json

{
  "direction": "down",           // up, down, left, right
  "pixels": 300,                // Amount to scroll
  "to_element": "footer",        // Or scroll to specific element
  "smooth": true                 // Smooth scrolling animation
}

Response:
{
  "status": "success",
  "message": "Scrolled down by 300px",
  "current_position": {"x": 0, "y": 300}
}
Search Endpoints
Web Search
POST /web_search
Content-Type: application/json

{
  "query": "best laptops 2024",
  "engine": "duckduckgo",  // google, bing, amazon, youtube, etc.
  "site": null             // Optional: specific site
}

Response:
{
  "query": "best laptops 2024",
  "engine": "duckduckgo",
  "results": [
    {
      "title": "Top 10 Laptops of 2024",
      "url": "https://example.com/laptops",
      "domain": "example.com"
    }
  ]
}
Cloudflare & Security Endpoints
Detect Cloudflare Challenge
GET /cloudflare/detect

Response:
{
  "status": "challenge_detected",
  "has_cloudflare": true,
  "has_recaptcha": false,
  "challenge_type": "cloudflare_interactive",
  "indicators": {
    "titleHasCloudflare": true,
    "hasChallengeForm": true
  }
}
Solve Challenge
POST /cloudflare/solve
Content-Type: application/json

{
  "timeout": 15,              // Max time to solve
  "click_delay": 5            // Delay between clicks
}

Response:
{
  "status": "success",
  "message": "Cloudflare challenge solved",
  "type": "cloudflare"
}
Utility Endpoints
Take Screenshot
POST /screenshot
Content-Type: application/json

{
  "selector": "div.content",   // Optional: specific element
  "full_page": false,          // Capture full page
  "format": "png"              // png or jpeg
}

Response:
{
  "status": "success",
  "path": "/tmp/screenshots/screenshot_20240101_120000.png",
  "format": "png"
}
Export Page as Markdown
POST /garbo/page_markdown
Content-Type: application/json

{
  "include_metadata": true,
  "use_trafilatura": true
}

Response:
{
  "status": "success",
  "filename": "20240101_120000_article_title.md",
  "path": "/tmp/exports/20240101_120000_article_title.md",
  "size_bytes": 4567,
  "url": "https://example.com/article",
  "title": "Article Title"
}
Find Elements
POST /interaction/find_elements
Content-Type: application/json

{
  "element_type": "input",      // input, button, link, text, all
  "interactive_only": true,     // Only interactive elements
  "visible_only": true          // Only visible elements
}

Response:
{
  "status": "success",
  "count": 5,
  "elements": [
    {
      "tagName": "input",
      "text": null,
      "id": "search-box",
      "className": "form-control",
      "href": null,
      "position": {
        "x": 100,
        "y": 200,
        "width": 300,
        "height": 40
      }
    }
  ]
}
Cache Management Endpoints
Get Cache Statistics
GET /cache/stats

Response:
{
  "total_pages": 150,
  "total_elements": 500,
  "total_workflows": 25,
  "avg_tokens_saved": 1250.5,
  "cache_size_mb": 45.2,
  "oldest_entry": "2024-01-01T00:00:00Z",
  "newest_entry": "2024-01-01T12:00:00Z"
}
Clear Expired Cache
DELETE /cache/expired

Response:
{
  "pages_deleted": 10,
  "workflows_deleted": 5,
  "selectors_deleted": 20
}
Health & Monitoring
Health Check
GET /health

Response:
{
  "status": "healthy",
  "browser_running": true,
  "database_healthy": true,
  "timestamp": "2024-01-01T12:00:00Z"
}
Service Info
GET /

Response:
{
  "service": "Zendriver Browser Automation API",
  "version": "4.0.0",
  "status": "ready",
  "features": [
    "navigation",
    "clicking",
    "typing",
    "scrolling",
    "element_discovery",
    "extraction",
    "cloudflare_bypass"
  ]
}
🛠️ Tools Available
Browser Control
    • NavigateBrowserTool - Navigate to URLs 
    • ClickElementTool - Click elements 
    • TypeTextTool - Type text into inputs 
    • ScrollPageTool - Scroll pages 
    • KeyboardNavigationTool - Press keyboard keys 
Content Extraction
    • ExtractContentTool - Extract page content 
    • ParallelExtractionTool - Extract from multiple selectors 
    • GarboPageMarkdownTool - Export page as Markdown 
Utility Tools
    • WebSearchTool - Search various search engines 
    • ScreenshotTool - Capture screenshots 
    • CloudflareBypassTool - Handle anti-bot challenges 
    • GetCurrentURLTool - Get current page URL 
    • SearchHistoryTool - Access cached searches 
EOF
