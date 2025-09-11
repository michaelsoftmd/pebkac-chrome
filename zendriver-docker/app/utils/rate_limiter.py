import time
import asyncio
from typing import Dict, Optional
from collections import defaultdict, deque
from datetime import datetime, timedelta
import hashlib

class RateLimiter:
    """Advanced rate limiter with multiple strategies"""
    
    def __init__(self, settings):
        self.settings = settings
        self.enabled = settings.rate_limit_enabled
        
        # Per-domain rate limiting
        self.domain_last_request: Dict[str, float] = {}
        
        # Per-client rate limiting (token bucket)
        self.client_requests: Dict[str, deque] = defaultdict(deque)
        
        # Global rate limiting
        self.global_requests = deque(maxlen=100)
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or parsed.path
    
    def _get_client_id(self, client_info: Optional[Dict] = None) -> str:
        """Get client identifier"""
        if not client_info:
            return "default"
        
        # Create hash from client info
        info_str = f"{client_info.get('ip', '')}:{client_info.get('user_agent', '')}"
        return hashlib.md5(info_str.encode()).hexdigest()[:8]
    
    async def check_rate_limit(self, url: str, client_info: Optional[Dict] = None):
        """Check if request should be rate limited"""
        if not self.enabled:
            return
        
        domain = self._get_domain(url)
        client_id = self._get_client_id(client_info)
        now = time.time()
        
        # 1. Domain-based rate limiting
        if domain in self.domain_last_request:
            time_since_last = now - self.domain_last_request[domain]
            if time_since_last < self.settings.rate_limit_delay:
                wait_time = self.settings.rate_limit_delay - time_since_last
                await asyncio.sleep(wait_time)
        
        self.domain_last_request[domain] = time.time()
        
        # 2. Per-client rate limiting (requests per minute)
        client_queue = self.client_requests[client_id]
        
        # Remove old requests (older than 1 minute)
        cutoff_time = now - 60
        while client_queue and client_queue[0] < cutoff_time:
            client_queue.popleft()
        
        # Check if limit exceeded
        if len(client_queue) >= self.settings.rate_limit_per_minute:
            # Calculate wait time
            oldest_request = client_queue[0]
            wait_time = 60 - (now - oldest_request) + 0.1
            
            if wait_time > 0:
                raise RateLimitExceeded(
                    f"Rate limit exceeded. Please wait {wait_time:.1f} seconds."
                )
        
        # Add current request
        client_queue.append(now)
        
        # 3. Global rate limiting (circuit breaker)
        self.global_requests.append(now)
        
        # Check if system is overloaded
        if len(self.global_requests) == 100:
            time_span = now - self.global_requests[0]
            if time_span < 10:  # 100 requests in 10 seconds
                # System overloaded, add delay
                await asyncio.sleep(0.5)
    
    def get_stats(self, client_info: Optional[Dict] = None) -> Dict:
        """Get rate limiting statistics"""
        client_id = self._get_client_id(client_info)
        client_queue = self.client_requests[client_id]
        
        return {
            "requests_in_last_minute": len(client_queue),
            "limit_per_minute": self.settings.rate_limit_per_minute,
            "domains_tracked": len(self.domain_last_request),
            "global_requests_tracked": len(self.global_requests)
        }

class RateLimitExceeded(Exception):
    """Rate limit exceeded exception"""
    pass

# Decorator for rate limiting
def rate_limited(calls: int = 10, period: int = 60):
    """Decorator to rate limit function calls"""
    def decorator(func):
        call_times = deque(maxlen=calls)
        
        async def wrapper(*args, **kwargs):
            now = time.time()
            
            # Remove old calls
            while call_times and call_times[0] < now - period:
                call_times.popleft()
            
            # Check rate limit
            if len(call_times) >= calls:
                wait_time = period - (now - call_times[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            
            call_times.append(now)
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator
