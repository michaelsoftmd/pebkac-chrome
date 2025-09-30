# app/core/browser.py - COMPLETE REPLACEMENT

import os
import asyncio
import logging
import shutil
import subprocess
import tempfile
import hashlib
from typing import Optional, Dict, Any
from pathlib import Path
import zendriver as zd
from zendriver import cdp
from app.core.timeouts import TIMEOUTS
from app.utils.tab_manager import TabPool

logger = logging.getLogger(__name__)

# MODULE-LEVEL: Single browser instance
_browser = None
_browser_tab = None
_browser_lock = asyncio.Lock()
_tab_creation_lock = asyncio.Lock()  # Separate lock for tab operations

async def is_browser_alive(browser_or_tab) -> tuple[bool, str]:
    """Centralized browser/tab health check with detailed error reporting"""
    try:
        if hasattr(browser_or_tab, 'evaluate'):
            await browser_or_tab.evaluate("1")
        else:
            _ = browser_or_tab.tabs
        return True, "healthy"
    except Exception as e:
        error_msg = f"Browser health check failed: {e}"
        logger.warning(error_msg)  # Changed from debug to warning for better visibility
        return False, error_msg

async def find_element_safe(tab, selector: str, timeout: int = TIMEOUTS.element_find, raise_on_missing: bool = True):
    """Standardized element finding with consistent error handling"""
    try:
        element = await tab.find(selector, timeout=timeout)
        if not element and raise_on_missing:
            raise ElementNotFoundError(f"Element not found: {selector}")
        return element
    except asyncio.TimeoutError:
        if raise_on_missing:
            raise ElementNotFoundError(f"Timeout finding element: {selector}")
        return None

class ElementNotFoundError(Exception):
    """Element not found during browser operations"""
    pass

class SecurityError(Exception):
    """Security violation detected"""
    pass

class BrowserManager:
    """Manager for single persistent browser instance"""

    def __init__(self, settings):
        self.settings = settings
        self.tab_pool = None
        self._session_restore_failed = False

        self.secure_base = self._create_secure_base_dir()

        profile_id = hashlib.sha256(f"main_profile_{os.getpid()}".encode()).hexdigest()[:16]
        self.profile_dir = self.secure_base / f"profile_{profile_id}"

        self._safe_mkdir(self.profile_dir)

        self.session_data_dir = self.secure_base / "session-data"
        self._safe_mkdir(self.session_data_dir)

    def _create_secure_base_dir(self) -> Path:
        """Create a secure base directory that can't be escaped"""
        base_dir = Path(tempfile.gettempdir()) / "zenbot_profiles"
        base_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return base_dir.resolve()

    def _safe_mkdir(self, target_path: Path):
        """Safely create directory with validation"""
        abs_path = target_path.resolve()

        try:
            abs_path.relative_to(self.secure_base)
        except ValueError:
            raise SecurityError(f"Path traversal detected: {target_path}")

        if abs_path.is_symlink():
            raise SecurityError(f"Symlink detected: {abs_path}")

        for parent in abs_path.parents:
            if parent.is_symlink():
                raise SecurityError(f"Symlink in path: {parent}")
            if parent == self.secure_base:
                break

        abs_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return abs_path

    def _validate_path(self, path: Path) -> Path:
        """Validate any path before use"""
        abs_path = path.resolve()

        try:
            abs_path.relative_to(self.secure_base)
        except ValueError:
            raise SecurityError(f"Path outside secure directory: {path}")

        if abs_path.is_symlink() or any(p.is_symlink() for p in abs_path.parents):
            raise SecurityError(f"Symlink detected in path: {path}")

        return abs_path

    async def get_browser(self):
        """Get the single browser instance"""
        global _browser, _browser_tab, _browser_lock

        async with _browser_lock:
            # Check if browser exists and is alive
            if _browser:
                is_alive, health_msg = await is_browser_alive(_browser)
                if is_alive:
                    logger.debug("Browser instance is alive")
                    return _browser
                else:
                    logger.warning(f"Browser health check failed: {health_msg}")

            # Browser is dead or missing, clean up
            if _browser:
                logger.warning("Browser appears dead, recreating...")
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
        """Get the current tab - ALWAYS reuse the same one with race condition protection"""
        global _browser_tab

        # Quick check without lock (double-checked locking pattern)
        if _browser_tab:
            is_alive, health_msg = await is_browser_alive(_browser_tab)
            if is_alive:
                return _browser_tab
            else:
                logger.warning(f"Tab health check failed: {health_msg}")

        # Now acquire lock for creation/validation
        async with _tab_creation_lock:  # Use separate lock, not _browser_lock
            # Re-check after acquiring lock
            if _browser_tab:
                is_alive, health_msg = await is_browser_alive(_browser_tab)
                if is_alive:
                    return _browser_tab
                else:
                    logger.warning(f"Tab health check failed after lock: {health_msg}")
            _browser_tab = None

            # Get or create tab
            browser = await self.get_browser()

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
        # Kill old Chrome processes more selectively (only oldest ones)
        try:
            subprocess.run(
                ["pkill", "-f", "-o", "chrome.*zenbot_profiles"],
                capture_output=True,
                timeout=5
            )
            await asyncio.sleep(0.5)  # Give it time to die
        except (subprocess.SubprocessError, OSError, asyncio.TimeoutError):
            pass

        # Ensure directories exist
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.session_data_dir.mkdir(parents=True, exist_ok=True)

        # Restore session data if exists
        await self._restore_session_data()

        # Wait for files to be fully written
        await asyncio.sleep(1)

        # Browser arguments for Docker environment
        browser_args = self.settings.browser_args.copy()
        browser_args.extend([
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu-sandbox",
            "--disable-features=site-per-process",
            "--password-store=basic",  # Store passwords in profile
            "--restore-last-session",  # Restore previous session
            "--disable-features=PrivacySandboxSettings4",  # Prevent cookie clearing
            "--disable-features=ClearDataOnExit",  # Prevent data clearing
        ])

        # Start browser with persistent profile
        browser = await zd.start(
            headless=self.settings.browser_headless,
            browser_args=browser_args,
            user_data_dir=str(self.profile_dir)
        )


        logger.info(f"Browser started with profile: {self.profile_dir}")
        return browser

    async def _restore_session_data(self):
        """Restore cookies and key data from persistent storage"""
        try:
            if not self.session_data_dir.exists():
                logger.warning("No session data directory found")
                return

            restored_files = []
            total_size = 0

            preserve_files = [
                "Cookies",
                "Cookies-journal",
                "Login Data",
                "Login Data-journal",
                "Web Data",
                "Web Data-journal",
                "Extension Cookies",
                "Extension State",
                "Secure Preferences",
                "Preferences",
                "Local Storage/",
                "Session Storage/",
                "IndexedDB/",
                "Service Worker/",
            ]

            logger.info(f"Restoring session from {self.session_data_dir}")

            # Try restoring to both locations (root and Default/)
            restore_dirs = [
                self.profile_dir,
                self.profile_dir / "Default",
            ]

            for restore_dir in restore_dirs:
                restore_dir.mkdir(parents=True, exist_ok=True)

                for file_pattern in preserve_files:
                    source = self.session_data_dir / file_pattern
                    dest = restore_dir / file_pattern

                    if source.exists():
                        if source.is_dir():
                            shutil.copytree(source, dest, dirs_exist_ok=True)
                            size = sum(f.stat().st_size for f in source.rglob('*') if f.is_file())
                        else:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, dest)
                            size = source.stat().st_size

                        restored_files.append(f"{restore_dir.name}/{file_pattern}")
                        total_size += size
                        logger.debug(f"Restored to {restore_dir.name}: {file_pattern} ({size} bytes)")

            logger.info(f"Session restored: {len(restored_files)} files, {total_size/1024:.1f}KB total")

            # Verify critical files in both locations
            for check_dir in restore_dirs:
                cookies_file = check_dir / "Cookies"
                if cookies_file.exists():
                    logger.info(f"✓ Cookies file found at: {cookies_file} ({cookies_file.stat().st_size} bytes)")
                    return  # Found cookies, we're good

            logger.warning("✗ Cookies file NOT found in any restore location")

        except Exception as e:
            logger.error(f"Session restore failed: {e}")
            # Set flag to indicate session restore failure for health monitoring
            self._session_restore_failed = True
            # Could implement retry logic here in the future

    async def save_session_data(self):
        """Save session data to persistent storage"""
        try:
            # First, find where Chrome actually put the files
            profile_dirs = [
                self.profile_dir,
                self.profile_dir / "Default",  # Chrome often uses this
            ]

            source_dir = None
            for profile_dir in profile_dirs:
                cookies_file = profile_dir / "Cookies"
                if cookies_file.exists():
                    logger.info(f"Found Cookies at: {cookies_file}")
                    source_dir = profile_dir
                    break

            if not source_dir:
                logger.error("Could not find Cookies file in any expected location!")
                return

            preserve_files = [
                "Cookies",
                "Cookies-journal",
                "Login Data",
                "Login Data-journal",
                "Web Data",
                "Web Data-journal",
                "Extension Cookies",
                "Extension State",
                "Secure Preferences",
                "Preferences",
                "Local Storage/",
                "Session Storage/",
                "IndexedDB/",
                "Service Worker/",
            ]

            saved_files = []
            total_size = 0

            # Copy from actual Chrome location to persistent storage
            for file_pattern in preserve_files:
                source = source_dir / file_pattern
                dest = self.session_data_dir / file_pattern

                if source.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_dir():
                        shutil.copytree(source, dest, dirs_exist_ok=True)
                        size = sum(f.stat().st_size for f in source.rglob('*') if f.is_file())
                    else:
                        shutil.copy2(source, dest)
                        size = source.stat().st_size

                    saved_files.append(file_pattern)
                    total_size += size
                    logger.debug(f"Saved: {file_pattern} ({size} bytes)")

            logger.info(f"Session saved: {len(saved_files)} files, {total_size/1024:.1f}KB total from {source_dir}")

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
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"Wait element not found: {wait_for} - {e}")

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
                # Explicitly clean up global references
                _browser = None
                _browser_tab = None

                # Force garbage collection of browser resources
                import gc
                gc.collect()