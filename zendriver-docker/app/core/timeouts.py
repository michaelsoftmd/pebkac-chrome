"""
Centralized timeout configuration for all browser operations.
Short timeouts prevent context overflow by failing fast.
"""

import os

class TIMEOUTS:
    """Centralized timeout values in seconds"""
    
    # Element finding operations (was 300s)
    element_find = int(os.getenv("TIMEOUT_ELEMENT_FIND", "3"))
    
    # HTTP requests to zendriver API (was 30s)
    http_request = int(os.getenv("TIMEOUT_HTTP_REQUEST", "5"))
    
    # Content extraction operations (was 10s) 
    http_extraction = int(os.getenv("TIMEOUT_HTTP_EXTRACTION", "8"))
    
    # Page load operations (was 15s)
    page_load = int(os.getenv("TIMEOUT_PAGE_LOAD", "10"))