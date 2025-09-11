import hashlib
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote, unquote
from typing import Optional, List, Dict, Set

class CacheKeyGenerator:
    """
    Advanced cache key generation with URL normalization.
    Handles edge cases and provides consistent keys.
    """
    
    # Query parameters to always exclude from cache keys
    EXCLUDED_PARAMS = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'fbclid', 'gclid', 'dclid', 'msclkid',
        'ref', 'referrer', 'source',
        '_ga', '_gid', '_gac',
        'timestamp', 'ts', 't',
        'session', 'sessionid', 'sid'
    }
    
    # Domains where query parameters are significant (don't normalize)
    PARAM_SENSITIVE_DOMAINS = {
        'youtube.com', 'youtu.be',  # Video IDs in params
        'amazon.com',  # Product variations
        'github.com',  # File paths and refs
    }
    
    @staticmethod
    def normalize_url(url: str, preserve_params: Optional[List[str]] = None) -> str:
        """
        Normalize URL for consistent cache keys.
        
        Handles:
        - Protocol normalization (http/https)
        - Domain case normalization
        - Path normalization
        - Query parameter handling
        - Fragment removal
        - Trailing slash normalization
        - Port normalization
        - Percent encoding normalization
        """
        if not url:
            return ''
        
        # Handle URLs without protocol
        if not url.startswith(('http://', 'https://', '//')):
            url = 'https://' + url
        
        # Parse URL
        try:
            parsed = urlparse(url)
        except Exception:
            # If parsing fails, return cleaned version
            return url.lower().strip()
        
        # Normalize scheme
        scheme = (parsed.scheme or 'https').lower()
        
        # Normalize domain (netloc)
        netloc = (parsed.netloc or '').lower()
        
        # If no netloc, return early with cleaned URL
        if not netloc:
            return url.lower().strip()
        
        # Remove default ports
        if ':80' in netloc and scheme == 'http':
            netloc = netloc.replace(':80', '')
        elif ':443' in netloc and scheme == 'https':
            netloc = netloc.replace(':443', '')
        
        # Normalize path
        path = parsed.path or '/'
        
        # Remove duplicate slashes
        path = re.sub(r'/+', '/', path)
        
        # Normalize percent encoding in path
        path = quote(unquote(path), safe='/:@!$&\'()*+,;=')
        
        # Handle trailing slash
        if path != '/' and path.endswith('/'):
            # Remove trailing slash except for root
            path = path[:-1]
        
        # Handle query parameters
        normalized_query = ''
        if parsed.query:
            normalized_query = CacheKeyGenerator._normalize_query_params(
                parsed.query,
                netloc,
                preserve_params
            )
        
        # Rebuild URL without fragment
        normalized = urlunparse((
            scheme,
            netloc,
            path,
            '',  # params (obsolete)
            normalized_query,
            ''   # no fragment
        ))
        
        return normalized
    
    @staticmethod
    def _normalize_query_params(
        query_string: str,
        domain: str,
        preserve_params: Optional[List[str]] = None
    ) -> str:
        """Normalize query parameters."""
        # Check if domain is parameter-sensitive
        is_sensitive = any(d in domain for d in CacheKeyGenerator.PARAM_SENSITIVE_DOMAINS)
        
        # Parse query parameters
        params = parse_qs(query_string, keep_blank_values=True)
        
        # Filter parameters
        filtered_params = {}
        for key, values in params.items():
            key_lower = key.lower()
            
            # Skip excluded params unless explicitly preserved
            if not is_sensitive and key_lower in CacheKeyGenerator.EXCLUDED_PARAMS:
                if not preserve_params or key not in preserve_params:
                    continue
            
            # Sort values for consistency
            if isinstance(values, list):
                values = sorted(values)
            
            filtered_params[key] = values
        
        # Sort parameters alphabetically
        sorted_params = sorted(filtered_params.items())
        
        # Rebuild query string
        if sorted_params:
            return urlencode(sorted_params, doseq=True)
        
        return ''
    
    @staticmethod
    def generate_cache_key(
        url: str,
        selector: Optional[str] = None,
        context: Optional[str] = None,
        include_params: bool = True,
        namespace: str = 'cache'
    ) -> str:
        """
        Generate consistent cache key with proper namespacing.
        """
        # Normalize URL
        normalized_url = CacheKeyGenerator.normalize_url(url)
        
        # Optionally remove all query parameters
        if not include_params:
            parsed = urlparse(normalized_url)
            normalized_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                '', '', ''
            ))
        
        # Build key components
        key_parts = [normalized_url]
        
        # Add selector if provided
        if selector:
            # Normalize selector
            selector_normalized = CacheKeyGenerator._normalize_selector(selector)
            key_parts.append(selector_normalized)
        
        # Add context if provided
        if context:
            # Ensure context is string and lowercase
            context_str = str(context).lower().strip()
            if context_str:
                key_parts.append(context_str)
        
        # Generate hash from components
        key_string = '|'.join(key_parts)
        key_hash = hashlib.sha256(key_string.encode()).hexdigest()
        
        # Create structured key with namespace and domain
        try:
            domain = urlparse(normalized_url).netloc or 'unknown'
            domain = domain.replace('.', '_').replace(':', '_')
            
            # Limit domain length for key
            if len(domain) > 30:
                domain = domain[:30]
        except Exception:
            domain = 'unknown'
        
        # Use first 16 chars of hash for reasonable length
        short_hash = key_hash[:16]
        
        return f"{namespace}:{domain}:{short_hash}"
    
    @staticmethod
    def _normalize_selector(selector: str) -> str:
        """Normalize CSS selector for consistent caching."""
        if not selector:
            return ''
        
        # Remove extra whitespace
        selector = ' '.join(selector.split())
        
        # Lowercase for consistency
        selector = selector.lower()
        
        # Remove quotes around attribute values (they're optional)
        selector = re.sub(r'\[([^=]+)=["\']([^"\']+)["\']\]', r'[\1=\2]', selector)
        
        # Sort multiple selectors if comma-separated
        if ',' in selector:
            parts = [s.strip() for s in selector.split(',')]
            selector = ','.join(sorted(parts))
        
        return selector
    
    @staticmethod
    def extract_cache_components(cache_key: str) -> Dict[str, str]:
        """Extract components from a cache key for debugging."""
        parts = cache_key.split(':', 2)
        
        if len(parts) >= 3:
            return {
                'namespace': parts[0],
                'domain': parts[1],
                'hash': parts[2]
            }
        
        return {
            'namespace': 'unknown',
            'domain': 'unknown',
            'hash': cache_key
        }
    
    @staticmethod
    def generate_pattern(domain: Optional[str] = None, namespace: str = 'cache') -> str:
        """Generate a pattern for cache invalidation."""
        if domain:
            # Normalize domain for pattern
            domain_normalized = domain.replace('.', '_').replace(':', '_')
            return f"{namespace}:{domain_normalized}:*"
        
        return f"{namespace}:*"