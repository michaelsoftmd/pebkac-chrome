# app/core/browser.py
import os
import asyncio
import logging
import uuid
from typing import Optional, Dict, Any
from pathlib import Path
import zendriver as zd
from app.core.timeouts import TIMEOUTS

logger = logging.getLogger(__name__)

# MODULE-LEVEL STATE - The key to persistent sessions
_browser_pool: Dict[str, 'BrowserInstance'] = {}
_pool_lock = asyncio.Lock()
_default_browser = None

class BrowserInstance:
    """Wrapper for a browser session"""
    def __init__(self, browser, tab, profile_dir, session_id):
        self.browser = browser
        self.tab = tab
        self.profile_dir = profile_dir
        self.session_id = session_id
        self.last_used = asyncio.get_event_loop().time()

class BrowserManager:
    """Manager that uses the global browser pool"""

    def __init__(self, settings):
        self.settings = settings
        # NO instance-level browser storage!

    async def get_browser(self, session_id: Optional[str] = None):
        """Get or create browser for session"""
        global _browser_pool, _default_browser

        async with _pool_lock:
            # Use default session if no ID provided
            if not session_id:
                if _default_browser and _default_browser.browser:
                    # Test if browser is still alive
                    try:
                        await _default_browser.browser.execute_cdp_cmd("Browser.getVersion", {})
                        logger.info("Reusing default browser instance")
                        return _default_browser.browser
                    except:
                        # Browser is dead, clean up
                        _default_browser = None

                # Create default browser
                logger.info("Creating default browser instance")
                browser = await self._create_browser("default")
                _default_browser = browser
                return browser.browser

            # Check if session exists
            if session_id in _browser_pool:
                instance = _browser_pool[session_id]
                if instance.browser:
                    # Test if browser is still alive
                    try:
                        await instance.browser.execute_cdp_cmd("Browser.getVersion", {})
                        logger.info(f"Reusing browser for session: {session_id}")
                        instance.last_used = asyncio.get_event_loop().time()
                        return instance.browser
                    except:
                        # Browser is dead, clean up
                        logger.warning(f"Browser for session {session_id} is dead, recreating")
                        del _browser_pool[session_id]

            # Create new browser for session
            logger.info(f"Creating new browser for session: {session_id}")
            instance = await self._create_browser(session_id)
            _browser_pool[session_id] = instance
            return instance.browser

    async def get_tab(self, session_id: Optional[str] = None):
        """Get current tab for session"""
        global _browser_pool, _default_browser

        browser = await self.get_browser(session_id)

        # Get the instance to access the tab
        if not session_id:
            instance = _default_browser
        else:
            instance = _browser_pool.get(session_id)

        if instance and instance.tab:
            return instance.tab

        # Create new tab if needed
        tab = await browser.get("about:blank")
        if instance:
            instance.tab = tab
        return tab

    async def _create_browser(self, session_id: str):
        """Create a new browser instance"""
        # Handle session prefix correctly
        if session_id.startswith("session_"):
            profile_name = session_id
        else:
            profile_name = f"session_{session_id}"

        profile_dir = Path(f"{self.settings.profiles_dir}/{profile_name}")
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Clean any stale locks
        await self._clean_stale_locks(profile_dir)

        # Docker-compatible browser args
        enhanced_args = self.settings.browser_args.copy()
        enhanced_args.extend([
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu-sandbox",
            "--disable-features=site-per-process",
        ])

        # Create browser with profile
        browser = await zd.start(
            headless=self.settings.browser_headless,
            browser_args=enhanced_args,
            user_data_dir=str(profile_dir)
        )

        tab = await browser.get("about:blank")

        return BrowserInstance(
            browser=browser,
            tab=tab,
            profile_dir=profile_dir,
            session_id=session_id
        )

    async def _clean_stale_locks(self, profile_path: Path):
        """Clean stale Chrome lock files for container restarts"""
        try:
            lock_files = [
                profile_path / "SingletonLock",
                profile_path / "SingletonSocket",
                profile_path / "SingletonCookie"
            ]

            for lock_file in lock_files:
                if lock_file.exists():
                    try:
                        lock_file.unlink()
                        logger.info(f"Cleaned stale lock file: {lock_file}")
                    except Exception as e:
                        logger.warning(f"Could not remove {lock_file}: {e}")

        except Exception as e:
            logger.warning(f"Error cleaning stale locks: {e}")

    async def navigate(self, url: str, wait_for: Optional[str] = None,
                      wait_timeout: int = TIMEOUTS.element_find,
                      session_id: Optional[str] = None) -> Dict[str, Any]:
        """Navigate to URL using zendriver's native navigation"""
        tab = await self.get_tab(session_id)

        try:
            # Navigate using tab
            await tab.get(url)

            # Wait for specific element if requested
            if wait_for:
                try:
                    await tab.find(wait_for, timeout=wait_timeout)
                    logger.info(f"Found wait_for element: {wait_for}")
                except Exception as e:
                    logger.warning(f"Wait element not found: {wait_for}, continuing anyway")

            # Get final URL after navigation (handles redirects)
            final_url = await tab.evaluate("window.location.href")

            return {
                "status": "success",
                "url": final_url,
                "title": await tab.evaluate("document.title") or "No title"
            }

        except Exception as e:
            logger.error(f"Navigation error: {e}")
            raise

    async def close_session(self, session_id: str):
        """Close and clean up a specific session"""
        global _browser_pool, _default_browser

        async with _pool_lock:
            if session_id == "default" and _default_browser:
                try:
                    if _default_browser.browser:
                        await _default_browser.browser.close()
                except:
                    pass
                _default_browser = None
                logger.info("Closed default browser session")

            elif session_id in _browser_pool:
                instance = _browser_pool[session_id]
                try:
                    if instance.browser:
                        await instance.browser.close()
                except:
                    pass
                del _browser_pool[session_id]
                logger.info(f"Closed browser session: {session_id}")

    async def cleanup_all(self):
        """Clean up all browser sessions"""
        global _browser_pool, _default_browser

        async with _pool_lock:
            # Close default browser
            if _default_browser:
                try:
                    if _default_browser.browser:
                        await _default_browser.browser.close()
                except:
                    pass
                _default_browser = None

            # Close all session browsers
            for session_id, instance in _browser_pool.items():
                try:
                    if instance.browser:
                        await instance.browser.close()
                except:
                    pass

            _browser_pool.clear()
            logger.info("Cleaned up all browser sessions")