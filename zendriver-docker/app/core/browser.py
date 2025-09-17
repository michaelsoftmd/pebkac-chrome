# app/core/browser.py - COMPLETE REPLACEMENT

import os
import asyncio
import logging
import shutil
from typing import Optional, Dict, Any
from pathlib import Path
import zendriver as zd
from zendriver import cdp  # Import CDP for health check
from app.core.timeouts import TIMEOUTS

logger = logging.getLogger(__name__)

# MODULE-LEVEL: Single browser instance
_browser = None
_browser_tab = None
_browser_lock = asyncio.Lock()

class BrowserManager:
    """Manager for single persistent browser instance"""

    def __init__(self, settings):
        self.settings = settings
        self.profile_dir = Path(f"{settings.profiles_dir}/main_profile")
        self.session_data_dir = Path("/app/session-data")

    async def get_browser(self):
        """Get the single browser instance"""
        global _browser, _browser_tab, _browser_lock

        async with _browser_lock:
            # Check if browser exists and is alive
            if _browser:
                try:
                    # Simple health check - try to access tabs property
                    _ = _browser.tabs  # This should work if browser is alive
                    logger.debug("Browser instance is alive")
                    return _browser
                except Exception as e:
                    logger.warning(f"Browser appears dead: {e}, recreating...")
                    try:
                        await _browser.close()
                    except:
                        pass
                    _browser = None
                    _browser_tab = None

            # Create browser if needed
            logger.info("Creating persistent browser instance")
            _browser = await self._create_browser()
            return _browser

    async def get_tab(self):
        """Get the current tab - ALWAYS reuse the same one"""
        global _browser_tab

        browser = await self.get_browser()

        # If we have a tab, use it
        if _browser_tab:
            try:
                await _browser_tab.evaluate("1")
                return _browser_tab
            except:
                logger.debug("Tab reference invalid")
                _browser_tab = None

        # Get the EXISTING tab from browser
        tabs = browser.tabs  # This is a property, not awaitable
        if tabs and len(tabs) > 0:
            _browser_tab = tabs[0]
            logger.info("Using existing browser tab")
            return _browser_tab

        # This should rarely happen - only on first startup
        logger.info("Creating initial tab")
        _browser_tab = await browser.new_tab("about:blank")
        return _browser_tab

    async def _create_browser(self):
        """Create browser with persistent session data"""
        # Kill any zombie Chrome processes first
        try:
            os.system("pkill -f 'chrome.*--user-data-dir=/app/profiles/main_profile' 2>/dev/null")
            await asyncio.sleep(0.5)  # Give it time to die
        except:
            pass

        # Ensure directories exist
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.session_data_dir.mkdir(parents=True, exist_ok=True)

        # Restore session data if exists
        await self._restore_session_data()

        # Browser arguments for Docker environment
        browser_args = self.settings.browser_args.copy()
        browser_args.extend([
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu-sandbox",
            "--disable-features=site-per-process",
            "--password-store=basic",  # Store passwords in profile
        ])

        # Start browser with persistent profile
        browser = await zd.start(
            headless=self.settings.browser_headless,
            browser_args=browser_args,
            user_data_dir=str(self.profile_dir)
        )

        logger.info(f"Browser started with hybrid profile: {self.profile_dir}")
        return browser

    async def _restore_session_data(self):
        """Restore cookies and key data from persistent storage"""
        try:
            # Key files to preserve between restarts
            preserve_files = [
                "Cookies",
                "Cookies-journal",
                "Login Data",
                "Login Data-journal",
                "Web Data",
                "Extension Cookies",
                "Extension State",
                "Preferences",
                "Local Storage/",
                "Session Storage/",
                "IndexedDB/"
            ]

            # Copy from persistent storage to tmpfs profile
            for file_pattern in preserve_files:
                source = self.session_data_dir / file_pattern
                dest = self.profile_dir / file_pattern

                if source.exists():
                    if source.is_dir():
                        shutil.copytree(source, dest, dirs_exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, dest)
                    logger.debug(f"Restored: {file_pattern}")

            logger.info("Session data restored from persistent storage")

        except Exception as e:
            logger.warning(f"Could not restore session data: {e}")

    async def save_session_data(self):
        """Save session data to persistent storage"""
        try:
            # Same files as restore
            preserve_files = [
                "Cookies",
                "Cookies-journal",
                "Login Data",
                "Login Data-journal",
                "Web Data",
                "Extension Cookies",
                "Extension State",
                "Preferences",
                "Local Storage/",
                "Session Storage/",
                "IndexedDB/"
            ]

            # Copy from tmpfs to persistent storage
            for file_pattern in preserve_files:
                source = self.profile_dir / file_pattern
                dest = self.session_data_dir / file_pattern

                if source.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_dir():
                        shutil.copytree(source, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source, dest)
                    logger.debug(f"Saved: {file_pattern}")

            logger.info("Session data saved to persistent storage")

        except Exception as e:
            logger.error(f"Could not save session data: {e}")

    async def navigate(self, url: str, wait_for: Optional[str] = None,
                      wait_timeout: int = TIMEOUTS.element_find) -> Dict[str, Any]:
        """Navigate to URL in the persistent tab"""
        tab = await self.get_tab()

        try:
            await tab.get(url)

            if wait_for:
                try:
                    await tab.find(wait_for, timeout=wait_timeout)
                    logger.info(f"Found wait_for element: {wait_for}")
                except:
                    logger.warning(f"Wait element not found: {wait_for}")

            # Get current state
            current_url = await tab.evaluate("window.location.href")
            title = await tab.evaluate("document.title")

            return {
                "status": "success",
                "url": current_url or url,
                "title": title or "Untitled"
            }

        except Exception as e:
            logger.error(f"Navigation error: {e}")
            raise

    async def cleanup(self):
        """Graceful shutdown - saves session state"""
        global _browser, _browser_tab

        # Save session data before closing
        try:
            await self.save_session_data()
        except Exception as e:
            logger.error(f"Failed to save session data: {e}")

        if _browser:
            try:
                logger.info("Closing browser gracefully...")
                await _browser.close()
            except:
                pass
            finally:
                _browser = None
                _browser_tab = None