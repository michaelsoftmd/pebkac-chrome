import asyncio
import sys
import time
import logging
from collections import OrderedDict
from typing import Any, Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger(__name__)

class BoundedLRUCache:
    """Thread-safe LRU cache with memory limits"""

    def __init__(self, max_items: int = 10000, max_memory_mb: int = 500):
        self.cache = OrderedDict()
        self.max_items = max_items
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.current_size_bytes = 0
        self._lock = asyncio.Lock()

    def _get_size(self, obj: Any) -> int:
        """Estimate memory size of object"""
        try:
            return sys.getsizeof(obj)
        except TypeError:
            if isinstance(obj, dict):
                return sum(self._get_size(k) + self._get_size(v) for k, v in obj.items())
            elif isinstance(obj, (list, tuple)):
                return sum(self._get_size(item) for item in obj)
            else:
                return 256

    async def get(self, key: str) -> Optional[Any]:
        """Get item and move to end (most recently used)"""
        async with self._lock:
            if key not in self.cache:
                return None

            self.cache.move_to_end(key)
            value, timestamp = self.cache[key]
            return value

    async def set(self, key: str, value: Any, ttl: int = 3600):
        """Set item with automatic eviction if needed"""
        async with self._lock:
            size = self._get_size(value)

            while (len(self.cache) >= self.max_items or
                   self.current_size_bytes + size > self.max_memory_bytes):
                if not self.cache:
                    break

                oldest_key, (oldest_val, _) = self.cache.popitem(last=False)
                self.current_size_bytes -= self._get_size(oldest_val)
                logger.debug(f"Evicted cache key: {oldest_key}")

            self.cache[key] = (value, time.time())
            self.current_size_bytes += size

            if self.current_size_bytes > self.max_memory_bytes * 0.8:
                logger.warning(f"Cache using {self.current_size_bytes / 1024 / 1024:.1f}MB (80% of limit)")

    async def clear_expired(self):
        """Remove expired entries"""
        async with self._lock:
            now = time.time()
            expired_keys = []

            for key, (value, timestamp) in self.cache.items():
                if now - timestamp > 3600:
                    expired_keys.append(key)

            for key in expired_keys:
                value, _ = self.cache.pop(key)
                self.current_size_bytes -= self._get_size(value)

    def get_stats(self) -> dict:
        """Get cache statistics"""
        stats = {
            "items_count": len(self.cache),
            "size_bytes": self.current_size_bytes,
            "size_mb": self.current_size_bytes / 1024 / 1024,
            "max_items": self.max_items,
            "max_memory_mb": self.max_memory_bytes / 1024 / 1024,
        }

        if HAS_PSUTIL:
            try:
                process = psutil.Process()
                stats["process_memory_mb"] = process.memory_info().rss / 1024 / 1024
            except Exception:
                stats["process_memory_mb"] = "unavailable"
        else:
            stats["process_memory_mb"] = "psutil not installed"

        return stats