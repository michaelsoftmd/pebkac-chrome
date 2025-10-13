"""
Cloudflare bypass tools - copied from openapi-server/main.py
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


class CloudflareBypassTool(Tool):
    """Tool to detect and bypass Cloudflare challenges"""
    name = "cloudflare_bypass"
    description = """Detect and solve Cloudflare anti-bot challenges on the current page.

WHEN TO USE:
- Page shows "Checking your browser" message
- "Just a moment..." loading screen
- Cloudflare protection blocking access
- 403/503 errors from Cloudflare

ACTIONS:
- auto (default): Detect and solve if challenge found
- detect: Check for challenges without solving
- solve: Attempt to bypass detected challenge

TYPICAL WORKFLOW:
1. Navigate to protected page
2. Call cloudflare_bypass() with default 'auto' action
3. Wait for bypass completion (up to 15 seconds)
4. Continue with normal extraction/interaction

Returns success status and challenge type solved."""
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
        },
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
                    },
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
                            return "Successfully bypassed Cloudflare challenge! Page is now accessible."
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
                    raise Exception(f"Failed to solve {challenge_type}: {error_msg}")

            return "Challenge detected but no active challenge to solve."

        except Exception as e:
            logger.error(f"Cloudflare bypass error: {e}")
            return f"Error during Cloudflare bypass: {str(e)}"