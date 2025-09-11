# app/services/cache_coordinator.py

import httpx

class CacheCoordinator:
    """Coordinate between memory, Redis, and DuckDB caches"""
    
    def __init__(self):
        self.memory = {}  # Hot cache
        self.redis = None  # Warm cache
        self.duckdb_url = None  # Cold storage
    
    async def get(self, key: str):
        # Check memory first (microseconds)
        if key in self.memory:
            return self.memory[key]
        
        # Check Redis (milliseconds)
        if self.redis:
            value = await self.redis.get(key)
            if value:
                self.memory[key] = value  # Promote to memory
                return value
        
        # Check DuckDB (slower, persistent)
        if self.duckdb_url:
            value = await self._duckdb_get(key)
            if value:
                # Promote to faster caches
                if self.redis:
                    await self.redis.set(key, value, ttl=3600)
                self.memory[key] = value
                return value
        
        return None

    async def _duckdb_get(self, key: str):
        """DuckDB retrieval"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.duckdb_url}/cache/page/{key}"
            )
            if response.status_code == 200:
                return response.json()
                
        return None
