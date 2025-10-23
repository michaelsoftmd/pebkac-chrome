# app/services/cache_service.py
import asyncio
import hashlib
import json
import pickle
import time
import os
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse
from app.utils.cache import CacheManager
from app.utils.cache_utils import CacheKeyGenerator
from app.utils.duckdb_client import DuckDBClient
import logging
logger = logging.getLogger(__name__)

class ExtractorCacheService:
    """Cache service for extraction operations with L1 (Redis) + L2 (DuckDB) tiering"""

    def __init__(self, cache_manager: CacheManager, duckdb_url: Optional[str] = None):
        self.cache = cache_manager

        # Initialize DuckDB L2 cache (optional but recommended)
        self.duckdb = None
        if duckdb_url or os.getenv("DUCKDB_URL"):
            try:
                self.duckdb = DuckDBClient(duckdb_url or os.getenv("DUCKDB_URL"))
                logger.info("DuckDB L2 cache initialized")
            except Exception as e:
                logger.warning(f"DuckDB L2 cache unavailable: {e}")

    def _make_url_key(self, url: str, selector: Optional[str] = None, context: str = "") -> str:
        """Create cache key for URL + selector + context using advanced normalization"""
        return CacheKeyGenerator.generate_cache_key(
            url=url,
            selector=selector,
            context=context,
            namespace='extract'
        )
    
    def _make_selector_key(self, domain: str, selector: str, success: bool) -> str:
        """Cache key for selector performance"""
        status = "works" if success else "fails"
        selector_hash = hashlib.md5(selector.encode()).hexdigest()
        return f"selector:{domain}:{status}:{selector_hash}"
    
    async def get_cached_extraction(self, url: str, selector: Optional[str] = None, context: str = "") -> Optional[Dict]:
        """
        Get cached extraction result with tiered lookup

        Flow:
        1. Check L1 (Redis) - 10ms latency
        2. If miss, check L2 (DuckDB) - 50-100ms latency
        3. If L2 hit, promote to L1 for future fast access
        4. Return None if both miss
        """
        # Don't return cache for search operations
        if self.should_bypass_cache(url, selector or "", context):
            return None

        key = self._make_url_key(url, selector, context)

        # L1 (Redis) lookup
        l1_result = await self.cache.get(key)
        if l1_result:
            logger.debug(f"L1 cache hit: {key[:50]}")
            return l1_result

        # L2 (DuckDB) lookup if available
        if self.duckdb:
            try:
                l2_result = await asyncio.to_thread(self.duckdb.get_cached_page, key)
                if l2_result:
                    logger.info(f"L2 cache hit, promoting to L1: {key[:50]}")
                    # Promote to L1 for future fast access
                    await self.cache.set(
                        key,
                        l2_result['data'],
                        ttl=l2_result.get('ttl', 3600)
                    )
                    return l2_result['data']
            except Exception as e:
                logger.warning(f"L2 cache lookup failed: {e}")

        # Total miss
        logger.debug(f"Cache miss (L1+L2): {key[:50]}")
        return None
    
    async def cache_extraction(self, url: str, selector: Optional[str], data: Dict, ttl: int = 3600, context: str = ""):
        """
        Cache extraction result with intelligent TTL

        Dual-write strategy:
        - L1 (Redis): Always write for fast access
        - L2 (DuckDB): Write if TTL >= 1 hour OR data size >= 10KB (expensive to re-extract)
        """
        # Use smart TTL based on selector type and context
        smart_ttl = self.get_cache_ttl(url, selector or "", context)
        if smart_ttl == 0:
            logger.debug(f"Skipping cache (TTL=0): {url[:50]}, selector={selector}, context={context}")
            return  # Don't cache

        key = self._make_url_key(url, selector, context)

        # Always write to L1 (Redis)
        await self.cache.set(key, data, smart_ttl)

        # Write to L2 (DuckDB) for persistence if:
        # 1. Long TTL (worth persisting)
        # 2. Large data (expensive to re-extract)
        if self.duckdb:
            data_size = len(pickle.dumps(data))

            should_persist = (
                (selector or '') == 'universal' or  # Expensive Trafilatura extractions
                smart_ttl >= 3600 or  # 1+ hour TTL
                data_size > 10_000  # 10KB+ data
            )

            if not should_persist:
                logger.debug(f"Skipping L2 (selector={selector}, TTL={smart_ttl}s, size={data_size}b)")

            if should_persist:
                metadata = {
                    'url': url,
                    'title': data.get('metadata', {}).get('title', ''),
                    'selector': selector or '',
                    'extraction_method': data.get('extraction_method', 'unknown')
                }

                # Run synchronous DuckDB call in thread pool to avoid blocking
                try:
                    await asyncio.to_thread(
                        self.duckdb.store_cached_page,
                        cache_key=key,
                        url=url,
                        data=data,
                        ttl=smart_ttl,
                        metadata=metadata
                    )
                    logger.info(f"Persisted to L2: {key[:50]} (TTL: {smart_ttl}s, Size: {data_size}b)")
                except Exception as e:
                    logger.error(f"L2 cache write failed: {e}")
    
    async def track_selector_performance(self, domain: str, selector: str, success: bool):
        """
        Track which selectors work/fail for domains

        Strategy:
        - Redis: Configurable TTL (default 90 days) for hot access
        - DuckDB: Persistent storage for long-term memory
        """
        key = self._make_selector_key(domain, selector, success)
        count = await self.cache.get(key) or 0

        # Get selector TTL from environment (default 90 days)
        selector_ttl = int(os.getenv("CACHE_TTL_SELECTOR", "7776000"))  # 90 days default
        await self.cache.set(key, count + 1, ttl=selector_ttl)

        # Also sync to DuckDB for persistence
        if self.duckdb:
            try:
                await asyncio.to_thread(
                    self.duckdb.store_selector_performance,
                    domain=domain,
                    selector=selector,
                    element_type="general",  # Could be inferred from selector
                    success=success,
                    find_time_ms=None  # Could track timing if needed
                )
            except Exception as e:
                logger.warning(f"DuckDB selector tracking failed: {e}")

    async def get_best_selectors(self, domain: str, element_type: str = "general") -> List[Dict[str, Any]]:
        """
        Get best performing selectors for a domain from DuckDB.

        DuckDB stores actual selector strings and persists across restarts.
        Returns empty list if DuckDB unavailable.
        """
        if not self.duckdb:
            return []

        try:
            selectors = await asyncio.to_thread(
                self.duckdb.get_best_selectors,
                domain,
                element_type
            )
            logger.debug(f"Got {len(selectors)} best selectors from DuckDB for {domain}")
            return selectors
        except Exception as e:
            logger.error(f"Failed to get best selectors from DuckDB: {e}")
            return []

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

            # Get best selectors for this domain from DuckDB
            best_selectors = await self.get_best_selectors(domain, element_type)

            if not best_selectors:
                return None

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
                if selector_info.get('success_rate', 0) > 0.8:  # 80% success threshold
                    selector = selector_info.get('selector')

                    if selector:
                        # If no filters or selector matches filter
                        if not filters or any(f in selector.lower() for f in filters):
                            logger.info(f"Using optimized selector for {domain}: {selector} (success_rate: {selector_info['success_rate']:.2%})")
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
                        # Use same TTL as selector performance tracking
                        selector_ttl = int(os.getenv("CACHE_TTL_SELECTOR", "7776000"))  # 90 days default
                        key = f"selector_quality:{domain}:{hashlib.md5(selector.encode()).hexdigest()}"
                        await self.cache.set(key, {
                            "content_length": content_length,
                            "success_rate": 1.0,  # Will be updated with running average
                            "last_used": time.time()
                        }, ttl=selector_ttl)

        except Exception as e:
            logger.error(f"Error learning selector performance: {e}")
            # Re-raise for critical performance tracking failures
            raise RuntimeError(f"Failed to learn selector performance for {url}: {e}") from e

    async def get_comprehensive_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics across all layers

        Returns:
            Dict with stats from:
            - L1 (Redis): memory, keys, hit rate, evictions
            - L2 (DuckDB): page count, size, age
            - Selectors: total tracked, top domains
            - Research sessions: execution history stats
        """
        stats = {
            'l1_redis': {
                'available': False,
                'memory_used_mb': 0,
                'memory_limit_mb': 512,
                'memory_usage_percent': 0,
                'keys_count': 0,
                'selector_count': 0,
                'extract_count': 0,
                'keyspace_hits': 0,
                'keyspace_misses': 0,
                'hit_rate_percent': 0,
                'evicted_keys': 0
            },
            'l2_duckdb': {
                'available': False,
                'page_count': 0,
                'element_count': 0,
                'total_size_mb': 0,
                'oldest_entry_days': None
            },
            'selector_memory': {
                'redis_selectors': 0,
                'duckdb_selectors': 0,
                'ttl_days': 90
            },
            'research_sessions': {
                'available': False,
                'total_executions': 0,
                'completed_count': 0,
                'incomplete_count': 0,
                'avg_steps': 0,
                'recent_24h': 0
            }
        }

        # L1 (Redis) stats
        if self.cache.redis_client:
            try:
                # Get Redis INFO for memory and stats
                memory_info = await self.cache.redis_client.info('memory')
                stats_info = await self.cache.redis_client.info('stats')

                stats['l1_redis']['available'] = True

                # Memory stats
                memory_used = int(memory_info.get('used_memory', 0)) / (1024 * 1024)
                stats['l1_redis']['memory_used_mb'] = round(memory_used, 2)
                stats['l1_redis']['memory_usage_percent'] = round((memory_used / 512) * 100, 1)

                # Hit rate stats
                hits = int(stats_info.get('keyspace_hits', 0))
                misses = int(stats_info.get('keyspace_misses', 0))
                total = hits + misses

                stats['l1_redis']['keyspace_hits'] = hits
                stats['l1_redis']['keyspace_misses'] = misses
                stats['l1_redis']['hit_rate_percent'] = round((hits / total * 100), 1) if total > 0 else 0
                stats['l1_redis']['evicted_keys'] = int(stats_info.get('evicted_keys', 0))

                # Count total keys
                dbsize = await self.cache.redis_client.dbsize()
                stats['l1_redis']['keys_count'] = dbsize

                # Count selector keys and extract keys
                selector_count = 0
                extract_count = 0
                cursor = 0
                while True:
                    cursor, keys = await self.cache.redis_client.scan(
                        cursor, match="*:*", count=100
                    )
                    for key in keys:
                        key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                        if key_str.startswith('selector:'):
                            selector_count += 1
                        elif key_str.startswith('extract:'):
                            extract_count += 1
                    if cursor == 0:
                        break

                stats['l1_redis']['selector_count'] = selector_count
                stats['l1_redis']['extract_count'] = extract_count
                stats['selector_memory']['redis_selectors'] = selector_count

            except Exception as e:
                logger.error(f"Redis stats error: {e}")

        # L2 (DuckDB) stats
        if self.duckdb:
            try:
                duckdb_stats = await asyncio.to_thread(self.duckdb.get_stats)
                stats['l2_duckdb']['available'] = True
                stats['l2_duckdb'].update(duckdb_stats)
                stats['selector_memory']['duckdb_selectors'] = duckdb_stats.get('element_count', 0)
            except Exception as e:
                logger.error(f"DuckDB stats error: {e}")

        # Research sessions stats (SQLite)
        try:
            from app.core.database import get_db, ResearchSession
            from datetime import datetime, timedelta

            db = next(get_db())
            try:
                # Total count
                total = db.query(ResearchSession).count()

                # Status counts
                completed = db.query(ResearchSession).filter(
                    ResearchSession.status == 'completed'
                ).count()

                # Recent (24h)
                yesterday = datetime.now() - timedelta(days=1)
                recent = db.query(ResearchSession).filter(
                    ResearchSession.created_at >= yesterday
                ).count()

                # Average steps (from data JSON)
                sessions_with_steps = db.query(ResearchSession).filter(
                    ResearchSession.data.isnot(None)
                ).all()

                total_steps = 0
                step_count = 0
                for session in sessions_with_steps:
                    if session.data and isinstance(session.data, dict):
                        steps = session.data.get('step_count', 0)
                        if steps > 0:
                            total_steps += steps
                            step_count += 1

                avg_steps = round(total_steps / step_count, 1) if step_count > 0 else 0

                stats['research_sessions'] = {
                    'available': True,
                    'total_executions': total,
                    'completed_count': completed,
                    'incomplete_count': total - completed,
                    'avg_steps': avg_steps,
                    'recent_24h': recent
                }
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Research sessions stats error: {e}")

        return stats


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

