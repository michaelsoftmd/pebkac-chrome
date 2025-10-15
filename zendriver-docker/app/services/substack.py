from typing import Optional, Dict, Any
from app.core.browser import BrowserManager
from app.core.exceptions import ElementNotFoundError
from app.services.element import ElementService

class SubstackService:
    """Specialized service for Substack operations"""
    
    SELECTORS = {
        "subscribe": [
            'button[class*="subscribe-button"]',
            'button:has-text("Subscribe")',
            'button:has-text("Sign up")',
        ],
        "like": [
            'button[aria-label*="Like"]',
            'button:has-text("Like")',
            '.like-button',
        ],
        "comment": [
            'button:has-text("Comment")',
            'button[aria-label*="Comment"]',
            '.comment-button'
        ],
        "share": [
            'button[aria-label*="Share"]',
            'button:has-text("Share")',
            '.share-button'
        ]
    }
    
    def __init__(self, browser_manager: BrowserManager, db):
        self.browser_manager = browser_manager
        self.db = db
        self.element_service = ElementService(browser_manager)
    
    async def subscribe_to_publication(self, publication_url: str) -> Dict[str, Any]:
        """Subscribe to a Substack publication"""
        # Navigate to publication
        result = await self.browser_manager.navigate(publication_url)
        
        # Try to find and click subscribe button
        for selector in self.SELECTORS["subscribe"]:
            try:
                element = await self.element_service.find_element(selector=selector, timeout=3)
                if element:
                    button_text = await element.text
                    
                    if "Subscribed" in button_text or "Following" in button_text:
                        return {
                            "status": "already_subscribed",
                            "message": "Already subscribed or following"
                        }
                    
                    await self.element_service.click_element(selector=selector)
                    return {
                        "status": "success",
                        "message": f"Clicked {button_text} button"
                    }
            except ElementNotFoundError:
                continue
        
        raise ElementNotFoundError("Subscribe button not found")
    
    async def interact_with_post(self, action: str, comment_text: Optional[str] = None):
        """Interact with a Substack post"""
        selectors = self.SELECTORS.get(action, [])
        
        for selector in selectors:
            try:
                element = await self.element_service.find_element(selector=selector, timeout=3)
                if element:
                    await self.element_service.click_element(selector=selector)
                    
                    # Handle comment text if provided
                    if action == "comment" and comment_text:
                        await self._post_comment(comment_text)
                    
                    return {"status": "success", "action": action}
            except ElementNotFoundError:
                continue
        
        raise ElementNotFoundError(f"Could not find {action} button")
    
    async def _post_comment(self, comment_text: str):
        """Post a comment"""
        comment_selectors = [
            'div[role="textbox"][contenteditable="true"]',
            'textarea[placeholder*="comment"]',
            '.comment-input'
        ]
        
        for selector in comment_selectors:
            try:
                element = await self.element_service.find_element(selector=selector, timeout=3)
                if element:
                    await element.click()
                    await element.send_keys(comment_text)
                    
                    # Find and click post button
                    post_btn = await self.element_service.find_element(
                        text="Post", timeout=3
                    )
                    if post_btn:
                        await post_btn.click()
                    break
            except ElementNotFoundError:
                continue
