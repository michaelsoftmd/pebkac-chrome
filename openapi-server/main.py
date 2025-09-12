"""
OpenAPI Tools Server for SmolAgents with Browser Automation
"""

import os
import logging
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
import httpx
from smolagents import CodeAgent, OpenAIServerModel, Tool
import json
from openai import OpenAI
import time
import sys
from io import StringIO

# Timeout configuration
class TIMEOUTS:
    http_request = int(os.getenv("TIMEOUT_HTTP_REQUEST", "5"))
    http_extraction = int(os.getenv("TIMEOUT_HTTP_EXTRACTION", "8"))
    page_load = int(os.getenv("TIMEOUT_PAGE_LOAD", "10"))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SafeCodeAgent implementation
class SafeCodeAgent(CodeAgent):
    """
    Enhanced CodeAgent that handles multiple final_answer calls and 
    ensures complete code execution.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.execution_log = []
        self.partial_results = []
        self.last_code = None
        self.original_task = None
        self._in_recovery = False
        self.error_buffer = []  # Store errors instead of returning them immediately
        self.suppress_intermediate_errors = True  # Control error suppression
        self.max_recovery_attempts = 3  # Prevent infinite recovery loops
        self.recovery_attempts = 0
    
    def run(self, task: str, **kwargs) -> Any:
        """Enhanced run that ensures final_answer is always provided."""
        self.original_task = task
        self.error_buffer = []  # Clear error buffer for new run
        self.recovery_attempts = 0  # Reset recovery counter
        
        try:
            # First attempt with standard execution
            result = super().run(task, **kwargs)
            
            # Check if we got a final answer
            if not self._has_final_answer(result):
                result = self._ensure_final_answer(result)
            
            # Reset suppression flag on successful completion
            self.suppress_intermediate_errors = True
            
            return result
            
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            # Always provide a final answer even on failure
            return self._create_error_final_answer(str(e))
    
    def _detect_incomplete_execution(self, result: Any) -> bool:
        """Detect if execution was terminated prematurely."""
        if hasattr(self, 'last_code') and self.last_code:
            code_lines = self.last_code.split('\n')
            
            # Check for multiple final_answer calls
            final_answer_count = sum(1 for line in code_lines if 'final_answer' in line)
            if final_answer_count > 1:
                return True
            
            # Check if final_answer appears before important operations
            final_answer_line = -1
            important_operations = [
                'extract', 'navigate', 'click', 'type_text', 'search',
                'visit_webpage', 'cloudflare_bypass', 'find_elements',
                'scroll', 'screenshot', 'parallel_extraction'
            ]
            
            for i, line in enumerate(code_lines):
                if 'final_answer' in line:
                    final_answer_line = i
                    break
            
            if final_answer_line >= 0:
                for i in range(final_answer_line + 1, len(code_lines)):
                    if any(op in code_lines[i] for op in important_operations):
                        return True
        
        return False
    
    def _recover_execution(self, task: str, partial_result: Any) -> Any:
        """Attempt to recover from incomplete execution."""
        # Check if we've exceeded max recovery attempts
        if self.recovery_attempts >= self.max_recovery_attempts:
            logger.warning(f"Max recovery attempts ({self.max_recovery_attempts}) reached")
            return partial_result
        
        self.recovery_attempts += 1
        logger.info(f"Recovery attempt {self.recovery_attempts}/{self.max_recovery_attempts}")
        
        modified_task = f"""
        {task}
        
        IMPORTANT INSTRUCTIONS:
        1. Execute ALL necessary steps before providing the final answer
        2. Do not call final_answer until all operations are complete
        3. If you need to perform multiple operations, do them sequentially
        4. Only call final_answer ONCE at the very end
        """
        
        try:
            self._in_recovery = True
            original_max_steps = self.max_steps
            self.max_steps = min(self.max_steps * 2, 30)
            
            result = super().run(modified_task)
            
            self.max_steps = original_max_steps
            self._in_recovery = False
            return result
        except Exception as e:
            logger.error(f"Recovery failed: {e}")
            self._in_recovery = False
            return partial_result
    
    def _fallback_execution(self, task: str, error: str) -> Any:
        """Fallback execution with simplified approach."""
        simplified_task = f"""
        Complete this task step by step: {task}
        
        Previous attempt failed with error: {error}
        
        Instructions:
        1. Break this into simple, sequential operations
        2. Execute each operation completely before moving to the next
        3. Only provide the final answer after all steps are done
        """
        
        try:
            return super().run(simplified_task, max_steps=15)
        except Exception as e:
            return f"Task failed after recovery attempts: {str(e)}"
    
    def execute(self, code: str, state: Optional[Dict] = None) -> Any:
        """Override execute to capture errors without sending them to output."""
        # Store the code for analysis
        self.last_code = code
        
        # Check for multiple final_answer patterns before execution
        if code.count('final_answer') > 1:
            logger.warning(f"Multiple final_answer calls detected, restructuring code")
            code = self._restructure_code(code)
        
        # Capture stdout/stderr to prevent intermediate outputs
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured_output = StringIO()
        
        try:
            if self.suppress_intermediate_errors:
                sys.stdout = captured_output
                sys.stderr = captured_output
            
            # Execute the code
            result = super().execute(code, state)
            
            # Only store successful results
            if result is not None and "error" not in str(result).lower():
                self.partial_results.append(result)
            
            return result
            
        except Exception as e:
            # Buffer the error instead of raising it immediately
            error_msg = str(e)
            self.error_buffer.append({
                'type': type(e).__name__,
                'message': error_msg,
                'code_snippet': code[:200] if code else None,
                'timestamp': time.time()
            })
            
            # Limit error buffer size to prevent memory issues
            if len(self.error_buffer) > 50:
                self.error_buffer = self.error_buffer[-50:]
            
            logger.error(f"Buffered error: {error_msg}")
            
            # Return a placeholder instead of raising and TRACK IT
            if "timeout" in error_msg.lower():
                placeholder = {"type": "timeout", "message": "Operation timed out", "partial": True, "details": error_msg[:100]}
                self.partial_results.append(placeholder)
                return placeholder
            elif "not found" in error_msg.lower():
                placeholder = {"type": "not_found", "message": "Element not found", "partial": True, "details": error_msg[:100]}
                self.partial_results.append(placeholder)
                return placeholder
            else:
                placeholder = {"type": "error", "message": f"Error occurred: {error_msg[:50]}", "partial": True, "details": error_msg[:100]}
                self.partial_results.append(placeholder)
                return placeholder
                
        finally:
            # Restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            
            # Log captured output for debugging
            output = captured_output.getvalue()
            if output:
                logger.debug(f"Captured output: {output[:500]}")
    
    def _restructure_code(self, code: str) -> str:
        """Restructure code to ensure single final_answer at the end."""
        lines = code.split('\n')
        final_answer_lines = []
        other_lines = []
        
        for line in lines:
            if 'final_answer' in line and not line.strip().startswith('#'):
                final_answer_lines.append(line)
            else:
                other_lines.append(line)
        
        if len(final_answer_lines) > 1:
            logger.info(f"Restructuring: keeping last of {len(final_answer_lines)} final_answer calls")
            restructured = '\n'.join(other_lines)
            if final_answer_lines:
                restructured += '\n' + final_answer_lines[-1]
            return restructured
        
        return code
    
    def get_execution_history(self) -> List[Dict]:
        """Get the execution history for debugging."""
        return self.execution_log
    
    def _has_final_answer(self, result: Any) -> bool:
        """Check if result contains a proper final answer."""
        if result is None:
            return False
        
        result_str = str(result)
        # Check for patterns that indicate a final answer was provided
        return any([
            "final_answer" in result_str.lower(),
            isinstance(result, dict) and 'final_answer' in result
        ])
    
    def _ensure_final_answer(self, partial_result: Any) -> str:
        """Ensure a final answer is provided even with errors."""
        # Compile information from partial results and errors
        response_parts = []
        
        # Add any successful partial results
        if self.partial_results:
            response_parts.append("Completed operations:")
            for i, result in enumerate(self.partial_results[-3:], 1):  # Last 3 results
                if isinstance(result, dict) and result.get('partial'):
                    # It's a placeholder/error result
                    response_parts.append(f"{i}. {result.get('message', 'Unknown operation')}")
                elif result and str(result).strip():
                    response_parts.append(f"{i}. {str(result)[:150]}")
        
        # Add error summary if any
        if self.error_buffer:
            response_parts.append("\nEncountered issues:")
            unique_errors = {}
            for error in self.error_buffer:
                error_type = error['type']
                if error_type not in unique_errors:
                    unique_errors[error_type] = error['message']
            
            for error_type, message in unique_errors.items():
                if "timeout" in message.lower():
                    response_parts.append(f"- Some operations timed out")
                elif "not found" in message.lower():
                    response_parts.append(f"- Some elements were not found")
                else:
                    response_parts.append(f"- {error_type}: {message[:100]}")
        
        # Create final answer
        if response_parts:
            return "\n".join(response_parts)
        else:
            return "Task completed with limited results due to errors."
    
    def _create_error_final_answer(self, error: str) -> str:
        """Create a final answer when the entire execution fails."""
        if self.partial_results:
            # We have some results despite the failure
            results_summary = "\n".join([str(r)[:100] for r in self.partial_results[:3]])
            return f"Task partially completed. Results:\n{results_summary}\n\nError: {error[:200]}"
        else:
            # Complete failure - provide informative response
            if "timeout" in error.lower():
                return "The operation timed out. Please try with a shorter task or increase timeout limits."
            elif "context" in error.lower():
                return "The task exceeded available resources. Please try a simpler query."
            else:
                return f"Unable to complete task due to: {error[:200]}"

    def clear_history(self):
        """Clear execution history and partial results."""
        self.execution_log = []
        self.partial_results = []
        self.last_code = None
        self._in_recovery = False
        self.error_buffer = []
        self.recovery_attempts = 0
        self.suppress_intermediate_errors = True  # Reset to default state

# Configuration from environment
ACTIVE_OPENAI_URL = os.getenv("ACTIVE_OPENAI_URL", "http://llama-cpp-server:8080/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "dummy")
ZENDRIVER_API_URL = os.getenv("ZENDRIVER_API_URL")
REDIS_URL = os.getenv("REDIS_URL")
DUCKDB_URL = os.getenv("DUCKDB_URL")
USE_CACHE = os.getenv("USE_CACHE", "true").lower() == "true"
SMOLAGENTS_MAX_STEPS = int(os.getenv("SMOLAGENTS_MAX_STEPS", "15"))

# Request/Response models
class AgentRequest(BaseModel):
    query: str
    max_steps: Optional[int] = SMOLAGENTS_MAX_STEPS

class AgentResponse(BaseModel):
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None

# Browser tools for SmolAgents
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
        }
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
                return "Navigation failed, unable to load page"
                
        except httpx.TimeoutException:
            return f"Navigation timed out for {url}, page may be slow or unavailable"
        except Exception as e:
            logger.warning(f"Navigation error: {e}")
            return "Navigation failed"

class GetCurrentURLTool(Tool):
    name = "get_current_url"
    description = "Get the current URL of the browser tab"
    inputs = {}
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

class CloudflareBypassTool(Tool):
    """Tool to detect and bypass Cloudflare or reCAPTCHA challenges"""
    name = "cloudflare_bypass"
    description = "Detect and solve Cloudflare or reCAPTCHA challenges on the current page. Use this if you encounter 'Checking your browser', 'Just a moment', Cloudflare messages, or reCAPTCHA checkboxes ('I'm not a robot')."
    inputs = {
        "action": {
            "type": "string",
            "description": "Action to perform: 'detect' to check for challenges, 'solve' to solve challenges, or 'auto' to detect and solve if needed",
            "default": "auto",
            "nullable": True
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum time in seconds to wait for solving the challenge",
            "default": 15,
            "nullable": True
        },
        "wait_after": {
            "type": "integer", 
            "description": "Seconds to wait after solving before continuing",
            "default": 3,
            "nullable": True
        }
    }
    output_type = "string"
    
    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)
    
    def forward(self, action: str = "auto", timeout: int = 15, wait_after: int = 3) -> str:
        """Detect and/or solve Cloudflare challenges"""
        try:
            # First, always detect
            detect_response = self.client.get(f"{self.api_url}/cloudflare/detect")
            
            if detect_response.status_code != 200:
                return f"Failed to check for Cloudflare: {detect_response.text}"
            
            detect_data = detect_response.json()
            has_cloudflare = detect_data.get("has_cloudflare", False)
            has_challenge = detect_data.get("has_challenge", False)
            indicators = detect_data.get("indicators", {})
            
            # If just detecting, return the result
            if action == "detect":
                if has_challenge:
                    return f"Cloudflare interactive challenge detected. Use 'solve' action to bypass it."
                elif has_cloudflare:
                    return f"Cloudflare detected but no active challenge. Page indicators: {indicators}"
                else:
                    return "No Cloudflare detected on this page."
            
            # If no challenge, nothing to solve
            if not has_challenge and not has_cloudflare:
                return "No Cloudflare challenge found. Page is accessible."
            
            # If action is 'solve' or 'auto', attempt to solve
            if has_challenge or (has_cloudflare and action in ["solve", "auto"]):
                # Attempt to solve the challenge
                solve_response = self.client.post(
                    f"{self.api_url}/cloudflare/solve",
                    json={
                        "timeout": timeout,
                        "click_delay": 5
                    }
                )
                
                if solve_response.status_code != 200:
                    return f"Failed to solve Cloudflare challenge: {solve_response.text}"
                
                solve_data = solve_response.json()
                
                if solve_data.get("status") == "success":
                    challenge_type = solve_data.get("type", "unknown")
                    message = solve_data.get("message", "")
                    
                    # Wait for page to stabilize after solving
                    time.sleep(wait_after)
                    
                    # Verify the challenge is gone
                    verify_response = self.client.get(f"{self.api_url}/cloudflare/detect")
                    if verify_response.status_code == 200:
                        verify_data = verify_response.json()
                        if not verify_data.get("has_challenge"):
                            if challenge_type == "cloudflare":
                                return "Successfully bypassed Cloudflare challenge! Page is now accessible."
                            elif challenge_type == "recaptcha":
                                return f"Successfully clicked reCAPTCHA checkbox! {message}"
                            else:
                                return "Challenge solved successfully! Page is now accessible."
                        else:
                            if challenge_type == "recaptcha":
                                return f"reCAPTCHA checkbox clicked: {message}"
                            else:
                                return "Challenge was processed but may still be active. Try again or wait longer."
                    
                    return f"Challenge solving completed ({challenge_type}). Page should be accessible."
                    
                elif solve_data.get("status") == "timeout":
                    return f"Timeout while solving challenge. The challenge may be too complex or require manual intervention."
                elif solve_data.get("status") == "no_challenge":
                    return "No challenge found to solve."
                else:
                    error_msg = solve_data.get('error', solve_data.get('message', 'Unknown error'))
                    challenge_type = solve_data.get('type', 'challenge')
                    return f"Failed to solve {challenge_type}: {error_msg}"
            
            return "Challenge detected but no active challenge to solve."
            
        except Exception as e:
            logger.error(f"Cloudflare bypass error: {e}")
            return f"Error during Cloudflare bypass: {str(e)}"

class ClickElementTool(Tool):
    name = "click_element"
    description = "Click an element on the page"
    inputs = {
        "selector": {
            "type": "string",
            "description": "CSS selector or text to click",
            "nullable": True
        }
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
                }
            )
            
            if response.status_code == 200:
                return f"Successfully clicked element: {selector}"
            else:
                return f"Failed to click: {response.text}"
                
        except Exception as e:
            logger.error(f"Click error: {e}")
            return f"Click failed: {str(e)}"

class ExtractContentTool(Tool):
    name = "extract_content"
    description = "Extract content from the current page"
    inputs = {
        "selector": {
            "type": "string", 
            "description": "CSS selector to extract from (leave empty for universal extraction)", 
            "default": None,
            "nullable": True
        }
    }
    output_type = "string"
    
    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)
    
    def forward(self, selector: str = None) -> str:
        """Extract content with timeout handling"""
        try:
            response = self.client.post(
                f"{self.api_url}/extraction/extract",
                json={
                    "selector": selector,  # Pass selector directly, None triggers universal extraction
                    "extract_text": True,
                    "extract_all": False
                },
                timeout=TIMEOUTS.http_extraction
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
                    if content and isinstance(content, dict):
                        text = content.get('text', '')[:600]  # Limit content
                        title = content.get('title', 'Unknown')[:50]
                        return f"Title: {title}\n\n{text}"
                    return "Content extracted but no details available"
                else:
                    return "Extraction failed, no content available"
            else:
                return "Unable to extract content at this time"
                
        except httpx.TimeoutException:
            # Return placeholder instead of raising
            return "Extraction timed out, skipping this content"
        except Exception as e:
            # Generic error handling
            logger.warning(f"Extraction error: {e}")
            return "Content unavailable"

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
    
    def forward(self, text: str, selector: Optional[str] = None) -> str:
        """Type text using synchronous httpx"""
        try:
            response = self.client.post(
                f"{self.api_url}/interaction/type",
                json={
                    "text": text,
                    "selector": selector,
                    "clear_first": True,
                }
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
    """A helper for all TYPETEXT and SEARCH tools. Press Enter, Tab, Escape, Arrow Keys"""
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

class WebSearchTool(Tool):
    name = "web_search"
    description = """Search the web using various search engines OR search within specific sites. Returns JSON with results array.
    Examples:
    - 'laptops' -> searches DuckDuckGo for laptops
    - 'search google for laptops' -> searches Google for laptops  
    - 'laptops on amazon' -> searches within Amazon for laptops
    - Returns: JSON string with 'results' array containing objects with 'title', 'url', 'domain' fields
    - Access results like: import json; data = json.loads(search_result); urls = [r['url'] for r in data['results']]
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
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)
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
        import re
        
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
        # Just ignore the site parameter - it's redundant with engine
        # The LLM sometimes provides both, but we only need engine
        
        try:
            # Use explicit engine parameter if provided, otherwise parse intent from query
            if engine and engine != "duckduckgo":
                # Use the explicitly provided engine
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
            
            # Format output as JSON string for agent parsing
            from datetime import datetime
            from urllib.parse import urlparse
            import json
            
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
                extract_response = self.client.post(
                    f"{self.api_url}/extraction/extract", 
                    json={
                        "selector": None,
                        "extract_text": True,
                        "extract_all": False
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

class ExportPageMarkdownTool(Tool):
    name = "export_page_markdown"
    description = "Export the current browser page content as a markdown file"
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
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)
    
    def forward(self, include_metadata: bool = True) -> str:
        """Export current page as markdown"""
        try:
            response = self.client.post(
                f"{self.api_url}/export/page_markdown",
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
            return f"Export failed: {str(e)}"
            
class ScreenshotTool(Tool):
    name = "take_screenshot"
    description = "Take a screenshot of the current page or a specific element"
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
        """Take screenshot and return base64"""
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
    description = "Intercept and modify network requests"
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
        self.client = httpx.Client(timeout=TIMEOUTS.http_request)
    
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


# Application lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting OpenAPI Tools Server...")
    yield
    # Shutdown
    logger.info("Shutting down OpenAPI Tools Server...")

# Create FastAPI app
app = FastAPI(
    title="OpenAPI Tools Server",
    description="SmolAgents integration with browser automation",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
async def root():
    """Service information"""
    return {
        "service": "OpenAPI Tools Server",
        "version": "1.0.0",
        "zendriver_api": ZENDRIVER_API_URL,
        "cache_enabled": USE_CACHE
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Use synchronous client for health check
        with httpx.Client() as client:
            zendriver_response = client.get(f"{ZENDRIVER_API_URL}/health")
            zendriver_healthy = zendriver_response.status_code == 200
        
        return {
            "status": "healthy" if zendriver_healthy else "degraded",
            "zendriver": zendriver_healthy,
            "cache_enabled": USE_CACHE
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

@app.get("/openapi.json")
async def get_openapi():
    """Return OpenAPI schema"""
    return app.openapi()

@app.post("/agent/run", response_model=AgentResponse)
async def run_agent(request: AgentRequest):
    """Run agent with browser tools - Fixed to use synchronous tools"""
    try:
        logger.info(f"Running agent with query: {request.query}")
        
        # Create browser tools (they're synchronous now)
        tools = [
            GetCurrentURLTool(ZENDRIVER_API_URL),
            NavigateBrowserTool(ZENDRIVER_API_URL),
            VisitWebpageTool(ZENDRIVER_API_URL),
            CloudflareBypassTool(ZENDRIVER_API_URL),
            ClickElementTool(ZENDRIVER_API_URL),
            ExtractContentTool(ZENDRIVER_API_URL),
            TypeTextTool(ZENDRIVER_API_URL),
            KeyboardNavigationTool(ZENDRIVER_API_URL),
            WebSearchTool(ZENDRIVER_API_URL),
            SearchHistoryTool(DUCKDB_URL),
            ExportPageMarkdownTool(ZENDRIVER_API_URL),
            ScreenshotTool(ZENDRIVER_API_URL),
            GetElementPositionTool(ZENDRIVER_API_URL),
            InterceptNetworkTool(ZENDRIVER_API_URL),
            ParallelExtractionTool(ZENDRIVER_API_URL)
        ]
        
        # Create OpenAI client with proper base_url
        client = OpenAI(
            base_url=ACTIVE_OPENAI_URL,
            api_key=OPENAI_API_KEY
        )

        # Create model using the client
        model = OpenAIServerModel(
            model_id="local-model",
            client=client
        )
        
        # Create and run agent with error buffering
        agent = SafeCodeAgent(
            tools=tools,
            model=model,
            max_steps=request.max_steps or SMOLAGENTS_MAX_STEPS,
            additional_authorized_imports=["json"]
        )
        
        # Enable error suppression for intermediate outputs
        agent.suppress_intermediate_errors = True
        
        logger.info("Created CodeAgent")
        logger.info(f"Available tools: {[tool.name for tool in tools]}")
        
        # Run the agent (this is synchronous)
        result = agent.run(request.query)
        
        # Format the result properly for Open WebUI
        if isinstance(result, str):
            formatted_result = result
        elif hasattr(result, 'final_answer') and result.final_answer:
            # SmolAgents CodeAgent returns object with final_answer attribute
            formatted_result = result.final_answer
        elif hasattr(result, 'logs') and result.logs:
            # If no final_answer, use the last log entry
            formatted_result = result.logs[-1] if result.logs else "Task completed"
        else:
            # Fallback to string conversion but clean it up
            formatted_result = str(result).replace('\\n', '\n').replace('\\t', '\t')
        
        # Ensure result is a clean string for Open WebUI
        if not isinstance(formatted_result, str):
            formatted_result = str(formatted_result)
        
        # Ensure we always have a result
        if not formatted_result:
            formatted_result = "Task completed but no specific output was generated."
        
        return AgentResponse(
            status="success",
            result=formatted_result.strip()  # Clean whitespace
        )
        
    except Exception as e:
        logger.error(f"Agent error: {e}")
        # Always return a valid response instead of error status
        return AgentResponse(
            status="completed_with_errors", 
            result=f"Task attempted. Some operations may have failed: {str(e)[:200]}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")
