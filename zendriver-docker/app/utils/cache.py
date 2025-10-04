import json
import time
import hashlib
import pickle
import asyncio
import logging
from typing import Optional, Any, Dict
from functools import wraps
from app.utils.memory_manager import BoundedLRUCache

logger = logging.getLogger(__name__)

class CacheManager:
    """Cache manager with memory limits"""

    def __init__(self, settings):
        self.settings = settings
        self.memory_cache = BoundedLRUCache(
            max_items=getattr(settings, 'cache_max_items', 5000),
            max_memory_mb=getattr(settings, 'cache_max_memory_mb', 200)
        )
        self.redis_client = None
        self._cleanup_task = None
        self._cleanup_started = False

        if settings.redis_url:
            try:
                import redis.asyncio as redis
                self.redis_client = redis.from_url(settings.redis_url, decode_responses=False)
                logger.info(f"Redis cache connected: {settings.redis_url}")
            except Exception as e:
                logger.warning(f"Redis not available ({e}), using memory cache")

        # Don't start cleanup task here - do it lazily

    async def ensure_cleanup_running(self):
        """Start cleanup task if not already running"""
        if not self._cleanup_started:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            self._cleanup_started = True
    
    def _make_key(self, prefix: str, params: dict) -> str:
        """Create cache key from prefix and parameters"""
        param_str = json.dumps(params, sort_keys=True)
        hash_str = hashlib.md5(param_str.encode()).hexdigest()
        return f"{prefix}:{hash_str}"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        await self.ensure_cleanup_running()  # Ensure cleanup is running

        if self.redis_client:
            try:
                value = await self.redis_client.get(key)
                if value:
                    return pickle.loads(value)
            except:
                pass

        return await self.memory_cache.get(key)
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set value in cache"""
        await self.ensure_cleanup_running()  # Ensure cleanup is running

        ttl = ttl or self.settings.cache_ttl

        if self.redis_client:
            try:
                await self.redis_client.setex(key, ttl, pickle.dumps(value))
            except:
                pass

        await self.memory_cache.set(key, value, ttl)
    
    async def delete(self, key: str):
        """Delete from cache"""
        if self.redis_client:
            try:
                await self.redis_client.delete(key)
            except:
                pass
        
        if key in self.memory_cache:
            del self.memory_cache[key]
    
    async def clear_pattern(self, pattern: str):
        """Clear all keys matching pattern"""
        if self.redis_client:
            try:
                cursor = 0
                while True:
                    cursor, keys = await self.redis_client.scan(
                        cursor, match=pattern
                    )
                    if keys:
                        await self.redis_client.delete(*keys)
                    if cursor == 0:
                        break
            except:
                pass
        
        # Clear from memory cache
        keys_to_delete = [
            k for k in self.memory_cache.cache.keys()
            if pattern.replace('*', '') in k
        ]
        for key in keys_to_delete:
            await self.memory_cache.set(key, None, 0)

    async def _periodic_cleanup(self):
        """Clean up expired entries every 5 minutes with proper error handling"""
        while True:
            await asyncio.sleep(300)
            try:
                await self.memory_cache.clear_expired()
                stats = self.memory_cache.get_stats()
                # Only log if there's something to report
                if stats.get('items_count', 0) > 0:
                    logger.info(f"Cache cleanup completed: {stats}")
                else:
                    logger.debug(f"Cache cleanup completed: {stats}")
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")
                # Continue running even if cleanup fails to prevent total breakdown

def cached(prefix: str, ttl: Optional[int] = None):
    """Decorator for caching function results"""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Get cache manager from self (assumes it's a class method)
            cache = getattr(self, 'cache', None)
            if not cache or not cache.settings.cache_enabled:
                return await func(self, *args, **kwargs)
            
            # Create cache key
            cache_key = cache._make_key(
                prefix,
                {"args": args, "kwargs": kwargs}
            )
            
            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute function and cache result
            result = await func(self, *args, **kwargs)
            await cache.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator
