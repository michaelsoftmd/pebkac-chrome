# app/core/browser.py
import os
import asyncio
import logging
import uuid
import shutil
from typing import Optional, Dict, Any
from pathlib import Path
import zendriver as zd
from app.core.timeouts import TIMEOUTS

logger = logging.getLogger(__name__)

class BrowserManager:
    """Browser manager with unique profile directories to prevent locks"""
    def __init__(self, settings):
        self.settings = settings
        self.browser = None
        self.current_tab = None
        self.lock = asyncio.Lock()
        # Add profile management
        self.profile_dir = None
        self.temp_profiles = []  # Track for cleanup
    
    async def _check_profile_lock(self, profile_path: Path) -> bool:
        """Check if profile is locked by another process"""
        lock_file = profile_path / "SingletonLock"
        if lock_file.exists():
            try:
                # Try to remove stale lock
                lock_file.unlink()
                logger.warning(f"Removed stale lock file: {lock_file}")
                return False
            except PermissionError:
                # Lock is active
                return True
        return False
    
    async def warmup_pool(self):
        """Fixed warmup with unique profile"""
        async with self.lock:
            if not self.browser:
                try:
                    logger.info("Initializing persistent browser instance...")
                    
                    # Create unique profile directory
                    self.profile_dir = Path(f"{self.settings.profiles_dir}/session_{uuid.uuid4().hex[:8]}")
                    self.profile_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Docker-compatible browser args
                    enhanced_args = self.settings.browser_args.copy()
                    enhanced_args.extend([
                        "--no-sandbox",  # Required in Docker
                        "--disable-setuid-sandbox",  # Also for Docker
                        "--disable-dev-shm-usage",  # Prevent /dev/shm issues
                        "--disable-gpu-sandbox",  # GPU sandbox issues in container
                        "--disable-features=site-per-process",  # Reduce process count
                    ])
                    
                    self.browser = await zd.start(
                        headless=self.settings.browser_headless,
                        browser_args=enhanced_args,
                        user_data_dir=str(self.profile_dir)
                    )
                    
                    self.current_tab = await self.browser.get("about:blank")
                    logger.info(f"Browser initialized with profile: {self.profile_dir}")
                    
                except Exception as e:
                    logger.error(f"Browser initialization failed: {e}")
                    # Clean up profile on failure
                    if self.profile_dir and self.profile_dir.exists():
                        shutil.rmtree(self.profile_dir, ignore_errors=True)
                    self.browser = None
                    self.current_tab = None
                    self.profile_dir = None

    async def get_browser(self):
        """Get browser with lock checking"""
        async with self.lock:
            if not self.browser:
                # Check for stale browser processes
                if self.profile_dir:
                    if await self._check_profile_lock(self.profile_dir):
                        logger.warning("Profile locked, creating new one")
                        self.profile_dir = None
                
                # Create browser with fresh profile if needed
                if not self.profile_dir:
                    self.profile_dir = Path(f"{self.settings.profiles_dir}/session_{uuid.uuid4().hex[:8]}")
                    self.profile_dir.mkdir(parents=True, exist_ok=True)
                
                logger.info(f"Creating browser instance with profile: {self.profile_dir}")
                
                # Enhanced browser args for Docker environment
                enhanced_args = self.settings.browser_args.copy()
                enhanced_args.extend([
                    "--no-sandbox",
                    "--disable-setuid-sandbox", 
                    "--disable-dev-shm-usage",
                    "--disable-gpu-sandbox",
                    "--disable-features=site-per-process",
                ])
                
                self.browser = await zd.start(
                    headless=self.settings.browser_headless,
                    browser_args=enhanced_args,
                    user_data_dir=str(self.profile_dir)
                )
                
                # Create initial tab
                self.current_tab = await self.browser.get("about:blank")
                logger.info("Browser created successfully")
                
            return self.browser
    
    async def navigate(self, url: str, wait_for: Optional[str] = None, 
                      wait_timeout: int = TIMEOUTS.element_find) -> Dict[str, Any]:
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
        """Close browser and clean up profile directory"""
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
            
            # Clean up profile directory
            if self.profile_dir and self.profile_dir.exists():
                try:
                    shutil.rmtree(self.profile_dir, ignore_errors=True)
                    logger.info(f"Cleaned up profile: {self.profile_dir}")
                except Exception as e:
                    logger.error(f"Failed to clean profile: {e}")
                finally:
                    self.profile_dir = None
