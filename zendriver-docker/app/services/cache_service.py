# app/services/cache_service.py
import hashlib
import json
import time
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse
from app.utils.cache import CacheManager
import logging
logger = logging.getLogger(__name__)

class ExtractorCacheService:
    """Cache service for extraction operations"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        # Store reverse mapping for selector optimization
        self._selector_reverse_map: Dict[str, str] = {}
    
    def _make_url_key(self, url: str, selector: Optional[str] = None, context: str = "") -> str:
        """Create cache key for URL + selector + context"""
        key_data = f"{url}:{selector or 'body'}:{context}"
        return f"extract:{hashlib.md5(key_data.encode()).hexdigest()}"
    
    def _make_selector_key(self, domain: str, selector: str, success: bool) -> str:
        """Cache key for selector performance"""
        status = "works" if success else "fails"
        selector_hash = hashlib.md5(selector.encode()).hexdigest()
        # Store reverse mapping
        self._selector_reverse_map[selector_hash] = selector
        return f"selector:{domain}:{status}:{selector_hash}"
    
    async def get_cached_extraction(self, url: str, selector: Optional[str] = None, context: str = "") -> Optional[Dict]:
        """Get cached extraction result"""
        # Don't return cache for search operations
        if self.should_bypass_cache(url, selector or "", context):
            return None
            
        key = self._make_url_key(url, selector, context)
        return await self.cache.get(key)
    
    async def cache_extraction(self, url: str, selector: Optional[str], data: Dict, ttl: int = 3600, context: str = ""):
        """Cache extraction result with intelligent TTL"""
        # Use smart TTL based on selector type and context
        smart_ttl = self.get_cache_ttl(url, selector or "", context)
        if smart_ttl == 0:
            return  # Don't cache
            
        key = self._make_url_key(url, selector, context)
        await self.cache.set(key, data, smart_ttl)
    
    async def track_selector_performance(self, domain: str, selector: str, success: bool):
        """Track which selectors work/fail for domains"""
        key = self._make_selector_key(domain, selector, success)
        count = await self.cache.get(key) or 0
        await self.cache.set(key, count + 1, ttl=86400)  # 24 hours
    
    async def get_working_selectors(self, domain: str) -> Dict[str, int]:
        """Get selectors that work for this domain"""
        if self.cache.redis_client:
            try:
                pattern = f"selector:{domain}:works:*"
                cursor = 0
                selectors = {}
                
                # Scan Redis for matching keys
                while True:
                    cursor, keys = await self.cache.redis_client.scan(
                        cursor, match=pattern, count=100
                    )
                    
                    for key in keys:
                        # Get the count for this selector
                        count = await self.cache.redis_client.get(key)
                        
                        # Extract selector hash from key
                        # Key format: "selector:domain:works:hash"
                        key_str = str(key) if hasattr(key, 'decode') else key
                        if hasattr(key_str, 'decode'):
                            key_str = key_str.decode('utf-8')
                        selector_hash = key_str.split(':')[-1]
                        selectors[selector_hash] = int(count) if count else 0
                    
                    if cursor == 0:
                        break
                
                return selectors
            except Exception as e:
                logger.error(f"Error getting working selectors: {e}")
                return {}
        
        # Fallback to memory cache scan (less efficient)
        selectors = {}
        prefix = f"selector:{domain}:works:"
        for key in self.cache.memory_cache.keys():
            if key.startswith(prefix):
                value, _ = self.cache.memory_cache[key]
                selector_hash = key.replace(prefix, '')
                selectors[selector_hash] = value
        
        return selectors
    
    async def get_failed_selectors(self, domain: str) -> Dict[str, int]:
        """Get selectors that fail for this domain"""
        if self.cache.redis_client:
            try:
                pattern = f"selector:{domain}:fails:*"
                cursor = 0
                selectors = {}
                
                # Scan Redis for matching keys
                while True:
                    cursor, keys = await self.cache.redis_client.scan(
                        cursor, match=pattern, count=100
                    )
                    
                    for key in keys:
                        # Get the count for this selector
                        count = await self.cache.redis_client.get(key)
                        
                        # Extract selector hash from key
                        # Key format: "selector:domain:fails:hash"
                        key_str = str(key) if hasattr(key, 'decode') else key
                        if hasattr(key_str, 'decode'):
                            key_str = key_str.decode('utf-8')
                        selector_hash = key_str.split(':')[-1]
                        selectors[selector_hash] = int(count) if count else 0
                    
                    if cursor == 0:
                        break
                
                return selectors
            except Exception as e:
                logger.error(f"Error getting failed selectors: {e}")
                return {}
        
        # Fallback to memory cache scan (less efficient)
        selectors = {}
        prefix = f"selector:{domain}:fails:"
        for key in self.cache.memory_cache.keys():
            if key.startswith(prefix):
                value, _ = self.cache.memory_cache[key]
                selector_hash = key.replace(prefix, '')
                selectors[selector_hash] = value
        
        return selectors

    async def get_best_selectors(self, domain: str) -> List[Dict[str, Any]]:
        """Get best performing selectors for a domain"""
        working = await self.get_working_selectors(domain)
        failed = await self.get_failed_selectors(domain)
        
        # Calculate success rates
        selector_stats = []
        all_hashes = set(working.keys()) | set(failed.keys())
        
        for selector_hash in all_hashes:
            works = working.get(selector_hash, 0)
            fails = failed.get(selector_hash, 0)
            total = works + fails
            
            if total > 0:
                success_rate = works / total
                selector_stats.append({
                    "hash": selector_hash,
                    "success_rate": success_rate,
                    "success_count": works,
                    "fail_count": fails,
                    "total_attempts": total
                })
        
        # Sort by success rate, then by total attempts (more attempts = more reliable)
        selector_stats.sort(key=lambda x: (x['success_rate'], x['total_attempts']), reverse=True)
        
        return selector_stats[:10]  # Return top 10

    def _sanitize_value(self, value: Any) -> str:
        """Handle RemoteObject and other types consistently"""
        if hasattr(value, 'value'):  # RemoteObject
            return str(value.value) if value.value is not None else ""
        if isinstance(value, tuple) and len(value) >= 1:
            return self._sanitize_value(value[0])
        return str(value) if value is not None else ""

    def should_bypass_cache(self, url: str, selector: str, context: Any) -> bool:
        """Determine if caching should be bypassed based on URL/context patterns"""

        # Use centralized sanitization for RemoteObject handling
        url = self._sanitize_value(url)
        selector = self._sanitize_value(selector)
        context = self._sanitize_value(context)

        # 1. Search operations - never cache
        if "search" in context.lower() or any(engine in url.lower() for engine in [
            "duckduckgo.com", "google.com", "bing.com", "search"
        ]):
            return True

        # 2. Real-time data URLs - bypass cache
        realtime_patterns = ["/api/", "/live/", "/current/", "/now/", "/realtime/"]
        if any(pattern in url.lower() for pattern in realtime_patterns):
            return True
        
        return False

    def should_cache_content(self, url: str, selector: str, context: str) -> bool:
        """Determine if content should be cached based on patterns"""

        # Use centralized sanitization for RemoteObject handling
        url = self._sanitize_value(url)
        selector = self._sanitize_value(selector)
        context = self._sanitize_value(context)
        
        # Never cache if should bypass
        if self.should_bypass_cache(url, selector, context):
            return False
        
        # Never cache dynamic content selectors
        dynamic_selectors = [".price", ".stock", ".timestamp", ".live", ".current", ".now"]
        if any(sel in selector.lower() for sel in dynamic_selectors):
            return False
            
        return True

    def get_cache_ttl(self, url: str, selector: str, context: str) -> int:
        """Get appropriate TTL based on selector type and context"""

        # Use centralized sanitization for RemoteObject handling
        url = self._sanitize_value(url)
        selector = self._sanitize_value(selector)
        context = self._sanitize_value(context)
        
        # Search context or bypass patterns - no cache
        if self.should_bypass_cache(url, selector, context):
            return 0  # Don't cache
            
        # Dynamic content selectors - no cache
        dynamic_patterns = [".price", ".stock", ".timestamp", ".live", ".current", ".now"]  
        if any(dyn in selector.lower() for dyn in dynamic_patterns):
            return 0  # Don't cache dynamic content
            
        # Structural elements (nav, form, header) - cache long  
        structural_patterns = ["nav", "header", "footer", "menu", "form", "input[", "button[", "[role"]
        if any(struct in selector.lower() for struct in structural_patterns):
            return 86400  # 24 hours
            
        # Text-based selectors (no CSS syntax) - medium cache
        if not any(css in selector for css in [".", "#", "[", ":", ">"]):
            return 1800  # 30 minutes
            
        return 3600  # 1 hour default

    async def get_optimized_selector(self, url: str, element_type: str = "general") -> Optional[str]:
        """Get best performing selector for this domain/element type"""
        from urllib.parse import urlparse
        
        try:
            domain = urlparse(url).netloc
            if not domain:
                return None
                
            # Get best selectors for this domain
            best_selectors = await self.get_best_selectors(domain)
            
            # Filter by element type if specified
            type_filters = {
                "navigation": ["nav", "header", "footer", "menu"],
                "content": ["article", "main", ".content", "p"],
                "forms": ["form", "input", "button", "select"],
                "links": ["a", "link"],
                "general": []  # No filter for general
            }
            
            filters = type_filters.get(element_type, [])
            
            for selector_info in best_selectors:
                if selector_info['success_rate'] > 0.8:  # 80% success threshold
                    selector_hash = selector_info['hash']
                    selector = self._selector_reverse_map.get(selector_hash)
                    
                    if selector:
                        # If no filters or selector matches filter
                        if not filters or any(f in selector.lower() for f in filters):
                            return selector
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting optimized selector: {e}")
            return None

    async def learn_selector_performance(self, url: str, selector: str, success: bool, response_data: Optional[Dict] = None):
        """Learn from selector performance for future optimization"""
        from urllib.parse import urlparse
        
        try:
            domain = urlparse(url).netloc
            if domain:
                await self.track_selector_performance(domain, selector, success)
                
                # Store additional metadata for better learning
                if response_data and success:
                    content_length = response_data.get("metadata", {}).get("content_length", 0)
                    # Only track selectors that return substantial content
                    if content_length > 50:
                        key = f"selector_quality:{domain}:{hashlib.md5(selector.encode()).hexdigest()}"
                        await self.cache.set(key, {
                            "content_length": content_length,
                            "success_rate": 1.0,  # Will be updated with running average
                            "last_used": time.time()
                        }, ttl=86400)
        
        except Exception as e:
            logger.error(f"Error learning selector performance: {e}")


class CacheInvalidationService:
    """
    Smart cache invalidation with content-aware strategies.
    Tracks invalidation history and patterns.
    """
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.invalidation_rules = self._initialize_rules()
        self.invalidation_history = []
        self.max_history = 1000
    
    def _initialize_rules(self) -> Dict[str, Dict]:
        """Define invalidation rules per content type."""
        return {
            'news': {
                'ttl': 3600,  # 1 hour
                'check_frequency': 300,  # Check every 5 minutes
                'content_change_threshold': 0.1,  # 10% change triggers invalidation
                'priority': 'high'
            },
            'product': {
                'ttl': 1800,  # 30 minutes for price changes
                'check_frequency': 600,
                'content_change_threshold': 0.05,  # 5% change (price sensitive)
                'priority': 'high'
            },
            'static': {
                'ttl': 86400,  # 24 hours
                'check_frequency': 3600,
                'content_change_threshold': 0.2,  # 20% change
                'priority': 'low'
            },
            'search': {
                'ttl': 0,  # Never cache
                'check_frequency': 0,
                'content_change_threshold': 0,
                'priority': 'skip'
            },
            'forum': {
                'ttl': 900,  # 15 minutes
                'check_frequency': 300,
                'content_change_threshold': 0.15,
                'priority': 'medium'
            }
        }
    
    async def should_invalidate(
        self,
        cache_key: str,
        url: str,
        cached_data: Dict,
        current_content: Optional[str] = None,
        force_check: bool = False
    ) -> Tuple[bool, str]:
        """
        Determine if cache should be invalidated using multiple strategies.
        """
        # Check if enough time has passed since last check
        if not force_check and not self._should_check_now(cached_data):
            return False, "check_frequency_not_met"
        
        # Priority 1: Check TTL expiration
        if self._is_expired(cached_data):
            self._record_invalidation(cache_key, url, 'ttl_expired')
            return True, "ttl_expired"
        
        # Priority 2: Check content changes if fresh content provided
        if current_content:
            has_changed, change_ratio = self._has_significant_change(cached_data, current_content)
            if has_changed:
                self._record_invalidation(cache_key, url, f'content_changed_{change_ratio:.2f}')
                return True, f"content_changed_{change_ratio:.2f}"
        
        # Priority 3: Check invalidation patterns
        if self._matches_invalidation_pattern(url):
            self._record_invalidation(cache_key, url, 'pattern_match')
            return True, "pattern_match"
        
        return False, "valid"
    
    def _should_check_now(self, cached_data: Dict) -> bool:
        """Determine if we should check for invalidation based on frequency rules."""
        last_check = cached_data.get('last_invalidation_check', 0)
        content_type = self._detect_content_type(cached_data.get('metadata', {}))
        check_frequency = self.invalidation_rules[content_type]['check_frequency']
        
        if check_frequency == 0:  # Never check
            return False
        
        return time.time() - last_check > check_frequency
    
    def _is_expired(self, cached_data: Dict) -> bool:
        """Check if cache entry is expired based on TTL."""
        # Check for explicit TTL in cache metadata
        cache_metadata = cached_data.get('cache_metadata', {})
        if cache_metadata:
            cached_time = cache_metadata.get('cached_at', 0)
            ttl = cache_metadata.get('ttl', 3600)
        else:
            # Fallback to older format
            cached_time = cached_data.get('timestamp', 0)
            ttl = cached_data.get('ttl', 3600)
        
        if not cached_time:
            return True  # No timestamp, consider expired
        
        return time.time() - cached_time > ttl
    
    def _has_significant_change(
        self,
        cached_data: Dict,
        current_content: str
    ) -> Tuple[bool, float]:
        """Detect significant content changes using multiple metrics."""
        cached_content = self._extract_cached_content(cached_data)
        if not cached_content:
            return True, 1.0  # No cached content, consider fully changed
        
        # Quick check: exact match via hash
        cached_hash = hashlib.md5(cached_content.encode()).hexdigest()
        current_hash = hashlib.md5(current_content.encode()).hexdigest()
        
        if cached_hash == current_hash:
            return False, 0.0
        
        # Calculate similarity using multiple metrics
        similarity = self._calculate_similarity(cached_content, current_content)
        change_ratio = 1 - similarity
        
        # Determine content type and threshold
        content_type = self._detect_content_type(cached_data.get('metadata', {}))
        threshold = self.invalidation_rules[content_type]['content_change_threshold']
        
        return change_ratio > threshold, change_ratio
    
    def _extract_cached_content(self, cached_data: Dict) -> str:
        """Extract text content from cached data, handling different formats."""
        # Try different data structures
        if 'data' in cached_data:
            data = cached_data['data']
            if isinstance(data, dict):
                return data.get('text', '') or data.get('main_text', '') or str(data)
            elif isinstance(data, str):
                return data
            elif isinstance(data, list):
                texts = []
                for item in data:
                    if isinstance(item, dict):
                        texts.append(item.get('text', ''))
                    elif isinstance(item, str):
                        texts.append(item)
                return ' '.join(texts)
        
        return cached_data.get('content', '') or cached_data.get('text', '')
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity using multiple metrics."""
        if not text1 or not text2:
            return 0.0
        
        # Word-based Jaccard similarity
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if words1 or words2:
            intersection = words1 & words2
            union = words1 | words2
            jaccard = len(intersection) / len(union) if union else 0.0
        else:
            jaccard = 0.0
        
        # Length ratio
        len_ratio = min(len(text1), len(text2)) / max(len(text1), len(text2)) if max(len(text1), len(text2)) > 0 else 0
        
        # Weighted average
        return (jaccard * 0.7) + (len_ratio * 0.3)
    
    def _detect_content_type(self, metadata: Dict) -> str:
        """Detect content type from metadata and URL patterns."""
        url = metadata.get('url', '')
        
        # Search engines - never cache
        search_domains = ['google.', 'bing.', 'duckduckgo.', 'yahoo.', 'baidu.']
        if any(domain in url.lower() for domain in search_domains):
            return 'search'
        
        # E-commerce/product pages
        product_indicators = ['/product', '/item', '/p/', 'amazon.', 'ebay.', 'alibaba.', 'shopify.']
        if any(indicator in url.lower() for indicator in product_indicators):
            return 'product'
        
        # News sites (check metadata)
        if metadata.get('pagetype') == 'article' or metadata.get('date'):
            return 'news'
        
        # Forum/discussion sites
        forum_indicators = ['forum', 'discuss', 'reddit.', 'discourse', '/t/', 'community']
        if any(indicator in url.lower() for indicator in forum_indicators):
            return 'forum'
        
        # Default to static
        return 'static'
    
    def _matches_invalidation_pattern(self, url: str) -> bool:
        """Check if URL matches known invalidation patterns."""
        invalidation_patterns = [
            '/api/', '/ajax/', '/live/', '/stream/', '/realtime/',
            '/ws/', '.json', '.xml', '/feed/', '/rss/'
        ]
        
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in invalidation_patterns)
    
    def _record_invalidation(self, cache_key: str, url: str, reason: str):
        """Record invalidation event for analysis."""
        event = {
            'timestamp': time.time(),
            'cache_key': cache_key,
            'url': url,
            'reason': reason,
            'domain': urlparse(url).netloc if url else 'unknown'
        }
        
        self.invalidation_history.append(event)
        
        # Trim history if too large
        if len(self.invalidation_history) > self.max_history:
            self.invalidation_history = self.invalidation_history[-self.max_history:]
        
        logger.info(f"Cache invalidated: {reason} for {url[:50]}...")
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all cache entries matching a pattern."""
        try:
            if self.cache and hasattr(self.cache, 'clear_pattern'):
                await self.cache.clear_pattern(pattern)
                logger.info(f"Invalidated cache pattern: {pattern}")
                return -1  # Unknown count
        except Exception as e:
            logger.error(f"Failed to invalidate pattern {pattern}: {e}")
        
        return 0
    
    async def smart_refresh(self, url: str, force: bool = False) -> Dict[str, Any]:
        """Smart refresh that considers content type and history."""
        # Generate cache key (simplified version)
        cache_key = f"extract:{hashlib.md5(url.encode()).hexdigest()}"
        
        # Get cached data
        cached = await self.cache.get(cache_key)
        
        if not cached and not force:
            return {
                'status': 'not_cached',
                'action': 'none',
                'url': url
            }
        
        if force:
            # Force invalidation
            if self.cache and hasattr(self.cache, 'delete'):
                await self.cache.delete(cache_key)
            self._record_invalidation(cache_key, url, 'forced_refresh')
            return {
                'status': 'invalidated',
                'reason': 'forced_refresh',
                'url': url
            }
        
        # Check if should invalidate
        should_invalidate, reason = await self.should_invalidate(
            cache_key,
            url,
            cached,
            force_check=True
        )
        
        if should_invalidate:
            if self.cache and hasattr(self.cache, 'delete'):
                await self.cache.delete(cache_key)
            return {
                'status': 'invalidated',
                'reason': reason,
                'url': url,
                'previous_cache_age': time.time() - cached.get('timestamp', 0) if cached else 0
            }
        
        return {
            'status': 'valid',
            'cached_data': cached,
            'url': url,
            'cache_age': time.time() - cached.get('timestamp', 0) if cached else 0
        }
    
    def get_invalidation_stats(self) -> Dict[str, Any]:
        """Get statistics about cache invalidations."""
        if not self.invalidation_history:
            return {
                'total_invalidations': 0,
                'recent_invalidations': [],
                'top_reasons': {},
                'top_domains': {}
            }
        
        # Analyze invalidation history
        reasons = {}
        domains = {}
        
        for event in self.invalidation_history:
            # Count reasons
            reason = event['reason']
            reasons[reason] = reasons.get(reason, 0) + 1
            
            # Count domains
            domain = event['domain']
            domains[domain] = domains.get(domain, 0) + 1
        
        # Sort by frequency
        top_reasons = dict(sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:5])
        top_domains = dict(sorted(domains.items(), key=lambda x: x[1], reverse=True)[:5])
        
        return {
            'total_invalidations': len(self.invalidation_history),
            'recent_invalidations': self.invalidation_history[-10:],
            'top_reasons': top_reasons,
            'top_domains': top_domains,
            'invalidation_rate': len(self.invalidation_history) / max(1, time.time() - self.invalidation_history[0]['timestamp']) if self.invalidation_history else 0
        }

