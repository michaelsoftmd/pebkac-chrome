# app/services/element.py
import asyncio
from typing import Optional, Dict, Any
from app.core.browser import BrowserManager
from app.core.exceptions import ElementNotFoundError, BrowserError
from app.core.timeouts import TIMEOUTS
from app.utils.browser_utils import safe_evaluate

class ElementService:
    """Service for element operations with correct zendriver API usage"""
    
    def __init__(self, browser_manager: BrowserManager):
        self.browser_manager = browser_manager
    
    async def find_element(self, selector: Optional[str] = None, text: Optional[str] = None, 
                          timeout: int = TIMEOUTS.element_find):
        """Find element with comprehensive error handling"""
        tab = await self.browser_manager.get_tab()
        
        try:
            if selector:
                element = await tab.find(selector, timeout=timeout)
            elif text:
                element = await tab.find(text, best_match=True, timeout=timeout)
            else:
                raise ValueError("Either selector or text must be provided")
            
            if not element:
                raise ElementNotFoundError(f"Element not found: {selector or text}")
            
            return element
            
        except asyncio.TimeoutError:
            raise ElementNotFoundError(f"Timeout finding element: {selector or text}")
        except Exception as e:
            if "Element not found" in str(e):
                raise ElementNotFoundError(f"Element not found: {selector or text}")
            raise BrowserError(f"Error finding element: {str(e)}")
    
    async def click_element(self, selector: Optional[str] = None, 
                           text: Optional[str] = None, wait_after: float = 1.0):
        """Click an element"""
        tab = await self.browser_manager.get_tab()
        
        try:
            # Find the element
            if selector:
                element = await tab.find(selector, timeout=TIMEOUTS.element_find)
            elif text:
                element = await tab.find(text, best_match=True, timeout=TIMEOUTS.element_find)
            else:
                raise ValueError("Either selector or text must be provided")
            
            if not element:
                raise ElementNotFoundError(f"Element not found: {selector or text}")
            
            # Click the element
            await element.click()
            
            # Wait after clicking
            await asyncio.sleep(wait_after)
            
            return True
            
        except asyncio.TimeoutError:
            raise ElementNotFoundError(f"Timeout finding element: {selector or text}")
        except Exception as e:
            if "Element not found" in str(e):
                raise ElementNotFoundError(f"Element not found: {selector or text}")
            raise BrowserError(f"Error clicking element: {str(e)}")
    
    async def type_text(self, element, text: str, clear_first: bool = True,
                    delay: float = 0.14, press_enter: bool = False):
        """Type text into element with optional delay between keystrokes"""
        try:
            if clear_first:
                await element.clear()
                await asyncio.sleep(0.1)

            if delay > 0:
                # Simulate human typing with delays
                for char in text:
                    await element.send_keys(char)
                    await asyncio.sleep(delay)
            else:
                # Send all at once (faster)
                await element.send_keys(text)

            if press_enter:
                await element.send_keys("\n")
                await asyncio.sleep(1)
        except Exception as e:
            raise BrowserError(f"Error typing text: {str(e)}")

