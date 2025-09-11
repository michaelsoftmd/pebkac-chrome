# app/core/browser.py
import os
import asyncio
import logging
from typing import Optional, Dict, Any
import zendriver as zd

logger = logging.getLogger(__name__)

class BrowserManager:
    """Browser manager with warmup pool using Zendriver's native API"""
    def __init__(self, settings):
        self.settings = settings
        self.browser = None
        self.current_tab = None
        self.lock = asyncio.Lock()
        self.warmup_browser = None
        self.warmup_tab = None
        self.warmup_lock = asyncio.Lock()
    
    async def warmup_pool(self):
        """Pre-initialize a single browser instance for zero-latency operations"""
        async with self.warmup_lock:
            if not self.warmup_browser:
                try:
                    logger.info("Pre-warming browser instance...")
                    
                    # Start warmup browser with same settings
                    self.warmup_browser = await zd.start(
                        headless=self.settings.browser_headless,
                        browser_args=self.settings.browser_args
                    )
                    
                    # Create initial tab with about:blank for fast startup
                    self.warmup_tab = await self.warmup_browser.get("about:blank")
                    logger.info("Browser warmup completed - ready for instant use")
                    
                except Exception as e:
                    logger.error(f"Browser warmup failed: {e}")
                    self.warmup_browser = None
                    self.warmup_tab = None

    async def get_browser(self):
        """Get browser instance - use warmed up browser if available"""
        async with self.lock:
            if not self.browser:
                # Try to use warmed up browser first
                async with self.warmup_lock:
                    if self.warmup_browser:
                        logger.info("Using pre-warmed browser instance")
                        self.browser = self.warmup_browser
                        self.current_tab = self.warmup_tab
                        
                        # Clear warmup references
                        self.warmup_browser = None
                        self.warmup_tab = None
                        
                        return self.browser
                
                # Fallback to creating new browser
                logger.info("Starting new browser instance (warmup not available)")
                
                self.browser = await zd.start(
                    headless=self.settings.browser_headless,
                    browser_args=self.settings.browser_args
                )
                
                # Check if browser has any existing tabs
                if self.browser.tabs and len(self.browser.tabs) > 0:
                    self.current_tab = self.browser.tabs[0]
                    logger.info("Using existing tab from browser.tabs")
                else:
                    self.current_tab = await self.browser.get("about:blank")
                    logger.info("Created initial tab")
                
            return self.browser
    
    async def navigate(self, url: str, wait_for: Optional[str] = None, 
                      wait_timeout: int = 350) -> Dict[str, Any]:
        """Navigate to URL using zendriver's native navigation"""
        browser = await self.get_browser()
        
        try:
            # If we have a current tab, navigate in it
            if self.current_tab:
                await self.current_tab.get(url)
                tab = self.current_tab
            else:
                # Use browser.get() which returns a Tab object
                tab = await browser.get(url)
                self.current_tab = tab
            
            # Wait for page to stabilize
            await asyncio.sleep(2)
            
            # Optional wait for specific element
            if wait_for:
                try:
                    await tab.find(wait_for, timeout=wait_timeout)
                    logger.info(f"Found wait_for element: {wait_for}")
                except Exception as e:
                    logger.warning(f"Wait element not found: {wait_for}, continuing anyway")
            
            # Get page info using safe_evaluate
            title = "Unknown"
            try:
                # Import safe_evaluate from utils module
                from app.utils.browser_utils import safe_evaluate
                title_result = await safe_evaluate(tab, "document.title")
                title = str(title_result) if title_result else "Unknown"
            except Exception as e:
                logger.error(f"Could not get page title: {e}")
            
            return {
                "url": url,
                "title": title
            }
            
        except Exception as e:
            logger.error(f"Navigation error: {e}")
            raise
    
    async def get_tab(self, url: Optional[str] = None):
        """Get current tab or navigate to URL if provided"""
        browser = await self.get_browser()
        
        # Ensure we have a tab
        if not self.current_tab:
            # Check browser.tabs first
            if browser.tabs and len(browser.tabs) > 0:
                self.current_tab = browser.tabs[0]
            else:
                # Create a tab by navigating
                if url:
                    self.current_tab = await browser.get(url)
                else:
                    self.current_tab = await browser.get("about:blank")
        elif url:
            # Navigate existing tab to new URL
            await self.current_tab.get(url)
        
        return self.current_tab
    
    async def release_tab(self, tab):
        """Clear tab state without closing it"""
        try:
            # Clear site data to prevent memory buildup
            await tab.send(cdp.storage.clear_data_for_origin(
                origin="*",
                storage_types="all"
            ))
            # Navigate to blank to release resources
            await tab.get("about:blank")
        except:
            pass
    
    async def close_browser(self):
        """Close browser and warmup browser properly"""
        async with self.lock:
            if self.browser:
                logger.info("Shutting down browser")
                try:
                    await self.browser.stop()
                    logger.info("Browser stopped successfully")
                except Exception as e:
                    logger.error(f"Error closing browser: {e}")
                finally:
                    self.browser = None
                    self.current_tab = None
        
        # Also close warmup browser if it exists
        async with self.warmup_lock:
            if self.warmup_browser:
                logger.info("Shutting down warmup browser")
                try:
                    await self.warmup_browser.stop()
                    logger.info("Warmup browser stopped successfully")
                except Exception as e:
                    logger.error(f"Error closing warmup browser: {e}")
                finally:
                    self.warmup_browser = None
                    self.warmup_tab = None
