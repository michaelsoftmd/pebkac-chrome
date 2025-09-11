import json
import time
import hashlib
import pickle
from typing import Optional, Any, Dict
from functools import wraps
import asyncio

class CacheManager:
    """Flexible cache manager supporting memory and Redis"""
    
    def __init__(self, settings):
        self.settings = settings
        self.memory_cache: Dict[str, tuple] = {}
        self.redis_client = None
        
        if settings.redis_url:
            try:
                import redis.asyncio as redis
                self.redis_client = redis.from_url(settings.redis_url, decode_responses=False)
                print(f"Redis cache connected: {settings.redis_url}")
            except Exception as e:
                print(f"Redis not available ({e}), using memory cache")
    
    def _make_key(self, prefix: str, params: dict) -> str:
        """Create cache key from prefix and parameters"""
        param_str = json.dumps(params, sort_keys=True)
        hash_str = hashlib.md5(param_str.encode()).hexdigest()
        return f"{prefix}:{hash_str}"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        # Try Redis first
        if self.redis_client:
            try:
                value = await self.redis_client.get(key)
                if value:
                    return pickle.loads(value)
            except:
                pass
        
        # Fall back to memory cache
        if key in self.memory_cache:
            value, timestamp = self.memory_cache[key]
            if time.time() - timestamp < self.settings.cache_ttl:
                return value
            else:
                del self.memory_cache[key]
        
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set value in cache"""
        ttl = ttl or self.settings.cache_ttl
        
        # Set in Redis if available
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    key, 
                    ttl, 
                    pickle.dumps(value)
                )
            except:
                pass
        
        # Also set in memory cache
        self.memory_cache[key] = (value, time.time())
    
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
            k for k in self.memory_cache.keys() 
            if pattern.replace('*', '') in k
        ]
        for key in keys_to_delete:
            del self.memory_cache[key]

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
