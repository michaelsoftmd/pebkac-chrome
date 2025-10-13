import re

CSS_SELECTOR_PATTERN = re.compile(
    r'^[a-zA-Z0-9\s\-_\.#\[\]=\'"~\*\^\$\|:,>+()]+$'
)

FORBIDDEN_PATTERNS = [
    r'javascript:', r'<script', r'onerror\s*=', r'onclick\s*=',
    r'onload\s*=', r'<iframe', r'data:', r'vbscript:'
]

def validate_css_selector(selector: str) -> bool:
    """Validate CSS selector for safety and format"""
    if not selector or len(selector) > 500:
        return False

    # Check against forbidden patterns
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, selector, re.IGNORECASE):
            return False

    # CSS selector validation
    return bool(CSS_SELECTOR_PATTERN.match(selector))