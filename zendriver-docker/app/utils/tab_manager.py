import asyncio
import time
import uuid
import logging
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

class TabPool:
    """Manage multiple browser tabs with automatic cleanup"""

    def __init__(self, browser, max_tabs: int = 10):
        self.browser = browser
        self.max_tabs = max_tabs
        self.active_tabs: Dict[str, Any] = {}
        self.available_tabs: List[Any] = []
        self._lock = asyncio.Lock()

    async def get_new_tab(self, session_id: Optional[str] = None) -> Tuple[str, Any]:
        """Get a tab for a new session - reuse available tabs when possible"""
        async with self._lock:
            if not session_id:
                session_id = str(uuid.uuid4())

            # Try to reuse an available tab first
            if self.available_tabs:
                tab = self.available_tabs.pop(0)
                await tab.get("about:blank")  # Reset tab to blank page
                self.active_tabs[session_id] = {
                    'tab': tab,
                    'created_at': time.time(),
                    'last_used': time.time()
                }
                logger.info(f"Reused existing tab for session {session_id}")
                return session_id, tab

            # Create new tab if needed and under limit
            if len(self.active_tabs) >= self.max_tabs:
                await self._cleanup_oldest_tab()

            tab = await self.browser.new_tab("about:blank")
            self.active_tabs[session_id] = {
                'tab': tab,
                'created_at': time.time(),
                'last_used': time.time()
            }

            logger.info(f"Created new tab for session {session_id}")
            return session_id, tab

    async def get_tab(self, session_id: str) -> Optional[Any]:
        """Get existing tab by session ID"""
        async with self._lock:
            if session_id in self.active_tabs:
                tab_info = self.active_tabs[session_id]
                tab_info['last_used'] = time.time()

                if await self._is_tab_alive(tab_info['tab']):
                    return tab_info['tab']
                else:
                    del self.active_tabs[session_id]
                    return None
            return None

    async def release_tab(self, session_id: str):
        """Release a tab when done - keep tab open, just mark as available"""
        async with self._lock:
            if session_id in self.active_tabs:
                tab_info = self.active_tabs.pop(session_id)
                self.available_tabs.append(tab_info['tab'])
                logger.info(f"Released tab for session {session_id} - kept open")

    async def _cleanup_oldest_tab(self):
        """Move oldest tab to available pool instead of closing"""
        if not self.active_tabs:
            return

        oldest_session = min(
            self.active_tabs.items(),
            key=lambda x: x[1]['last_used']
        )[0]

        await self.release_tab(oldest_session)

    async def _is_tab_alive(self, tab) -> bool:
        """Check if tab is still responsive"""
        try:
            await tab.evaluate("1")
            return True
        except:
            return False

    async def cleanup_all(self):
        """Clean up all tabs"""
        sessions = list(self.active_tabs.keys())
        for session_id in sessions:
            await self.release_tab(session_id)