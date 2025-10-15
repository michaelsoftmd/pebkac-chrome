"""
HTTP client for DuckDB cache service
"""

import httpx
import hashlib
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class DuckDBClient:
    """Client for interacting with DuckDB cache service via HTTP"""

    def __init__(self, duckdb_url: str):
        self.duckdb_url = duckdb_url.rstrip('/')
        self.client = httpx.Client(timeout=10.0)
        logger.info(f"DuckDB client initialized: {self.duckdb_url}")

    def close(self):
        """Close HTTP client"""
        self.client.close()

    # Page cache operations

    def get_cached_page(self, cache_key: str) -> Optional[Dict]:
        """
        Get cached page from DuckDB L2

        Returns:
            Dict with 'data' key containing cached extraction result
            None if not found or expired
        """
        try:
            response = self.client.get(f"{self.duckdb_url}/cache/page/{cache_key}")
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"L2 cache hit: {cache_key}")
                return {
                    'data': {
                        'status': 'success',
                        'data': data.get('content'),
                        'metadata': {
                            'url': data.get('url'),
                            'title': data.get('title'),
                            'word_count': data.get('word_count'),
                            'content_hash': data.get('content_hash'),
                        },
                        'cached': True,
                        'cache_layer': 'L2_duckdb'
                    },
                    'ttl': 3600,  # Default TTL when promoting to L1
                    'access_count': 1  # Placeholder
                }
            elif response.status_code == 404:
                logger.debug(f"L2 cache miss: {cache_key}")
                return None
            else:
                logger.warning(f"L2 cache error for {cache_key}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"DuckDB get_cached_page error: {e}")
            return None

    def store_cached_page(
        self,
        cache_key: str,
        url: str,
        data: Any,
        ttl: int,
        metadata: Dict
    ) -> bool:
        """
        Store page in DuckDB L2 for persistence

        Args:
            cache_key: Cache key
            url: Original URL
            data: Extraction result (dict or string)
            ttl: TTL in seconds
            metadata: Additional metadata (title, selector, etc.)

        Returns:
            True if stored successfully
        """
        try:
            # Extract content from data
            if isinstance(data, dict):
                content = data.get('data', '') or data.get('text', '') or str(data)
            else:
                content = str(data)

            # Calculate content hash
            content_hash = hashlib.md5(content.encode()).hexdigest()
            word_count = len(content.split())

            payload = {
                "cache_key": cache_key,
                "url": url,
                "title": metadata.get('title', ''),
                "content": content,
                "content_hash": content_hash,
                "word_count": word_count,
                "summary": None,  # Could add summarization later
                "key_points": None,
                "entities": None,
                "selector_used": metadata.get('selector', ''),
                "extraction_method": metadata.get('extraction_method', 'unknown'),
                "ttl_seconds": ttl
            }

            response = self.client.post(
                f"{self.duckdb_url}/cache/page",
                json=payload
            )

            if response.status_code == 200:
                logger.debug(f"L2 stored: {cache_key} (TTL: {ttl}s)")
                return True
            else:
                logger.warning(f"L2 store failed for {cache_key}: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"DuckDB store_cached_page error: {e}")
            return False

    # Selector operations

    def store_selector_performance(
        self,
        domain: str,
        selector: str,
        element_type: str,
        success: bool,
        find_time_ms: Optional[float] = None
    ) -> bool:
        """
        Store selector performance in DuckDB for long-term memory

        This provides persistent storage beyond Redis TTL
        """
        try:
            payload = {
                "domain": domain,
                "element_type": element_type,
                "selector": selector,
                "success": success,
                "find_time_ms": find_time_ms
            }

            response = self.client.post(
                f"{self.duckdb_url}/cache/element",
                json=payload
            )

            if response.status_code == 200:
                return True
            else:
                logger.warning(f"DuckDB selector store failed: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"DuckDB store_selector_performance error: {e}")
            return False

    def get_best_selectors(
        self,
        domain: str,
        element_type: str = "general"
    ) -> List[Dict]:
        """
        Get best performing selectors for domain from DuckDB

        Returns:
            List of selector dicts with success_rate, selector, etc.
        """
        try:
            response = self.client.get(
                f"{self.duckdb_url}/cache/element/{domain}/{element_type}"
            )

            if response.status_code == 200:
                data = response.json()
                return data.get('selectors', [])
            elif response.status_code == 404:
                return []
            else:
                logger.warning(f"DuckDB get_best_selectors failed: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"DuckDB get_best_selectors error: {e}")
            return []

    # Stats operations

    def get_stats(self) -> Dict[str, Any]:
        """
        Get DuckDB cache statistics

        Returns:
            Dict with page_count, total_size_mb, oldest_entry_days, etc.
        """
        try:
            response = self.client.get(f"{self.duckdb_url}/cache/stats")

            if response.status_code == 200:
                stats = response.json()

                # Calculate oldest entry age
                oldest_entry = stats.get('oldest_entry')
                oldest_entry_days = None
                if oldest_entry:
                    try:
                        oldest_dt = datetime.fromisoformat(oldest_entry.replace('Z', '+00:00'))
                        oldest_entry_days = (datetime.now() - oldest_dt).days
                    except:
                        pass

                return {
                    'page_count': stats.get('total_pages', 0),
                    'element_count': stats.get('total_elements', 0),
                    'workflow_count': stats.get('total_workflows', 0),
                    'total_size_mb': stats.get('cache_size_mb', 0),
                    'oldest_entry_days': oldest_entry_days,
                    'avg_tokens_saved': stats.get('avg_tokens_saved', 0)
                }
            else:
                logger.warning(f"DuckDB stats failed: {response.status_code}")
                return {
                    'page_count': 0,
                    'element_count': 0,
                    'workflow_count': 0,
                    'total_size_mb': 0,
                    'oldest_entry_days': None,
                    'avg_tokens_saved': 0
                }

        except Exception as e:
            logger.error(f"DuckDB get_stats error: {e}")
            return {
                'page_count': 0,
                'element_count': 0,
                'workflow_count': 0,
                'total_size_mb': 0,
                'oldest_entry_days': None,
                'avg_tokens_saved': 0,
                'error': str(e)
            }

    # Cleanup operations

    def cleanup_expired(self) -> Dict[str, int]:
        """
        Trigger DuckDB cleanup of expired entries

        Returns:
            Dict with counts of deleted pages, workflows, selectors
        """
        try:
            response = self.client.delete(f"{self.duckdb_url}/cache/expired")

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"DuckDB cleanup failed: {response.status_code}")
                return {'pages_deleted': 0, 'workflows_deleted': 0, 'selectors_deleted': 0}

        except Exception as e:
            logger.error(f"DuckDB cleanup_expired error: {e}")
            return {'pages_deleted': 0, 'workflows_deleted': 0, 'selectors_deleted': 0, 'error': str(e)}
