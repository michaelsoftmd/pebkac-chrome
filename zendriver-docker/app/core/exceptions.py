from typing import Any, Optional, Dict
from fastapi import HTTPException, status

class BrowserError(Exception):
    """Base exception for browser operations"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

class ElementNotFoundError(BrowserError):
    """Element not found on page"""
    pass

class NavigationError(BrowserError):
    """Navigation failed"""
    pass

class TimeoutError(BrowserError):
    """YOU TIMED OUT MUTHAFUCKA"""
    pass

# HTTP exceptions with standard format
def element_not_found(selector: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": "element_not_found",
            "message": f"Element not found: {selector}",
            "selector": selector
        }
    )

def navigation_failed(url: str, reason: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error": "navigation_failed", 
            "message": f"Failed to navigate to {url}",
            "url": url,
            "reason": reason
        }
    )
