from pydantic import BaseModel, Field, field_validator, HttpUrl
from typing import Optional, List, Dict, Any
import re
from app.core.timeouts import TIMEOUTS
from app.utils.validators import validate_css_selector

class NavigationRequest(BaseModel):
    """Navigation request with validation"""
    url: HttpUrl | str
    wait_for: Optional[str] = Field(None, max_length=500)
    wait_timeout: int = Field(TIMEOUTS.element_find, ge=1, le=350)

    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        # Block potentially dangerous URLs
        blocked_patterns = [
            r'javascript:',
            r'data:',
            r'file://',
            r'chrome://',
            r'about:config'
        ]

        url_str = str(v).lower()
        for pattern in blocked_patterns:
            if re.match(pattern, url_str):
                raise ValueError(f"Blocked URL pattern: {pattern}")

        # Add https if no protocol
        if isinstance(v, str) and not v.startswith(('http://', 'https://')):
            v = f'https://{v}'

        return v

    @field_validator('wait_for')
    @classmethod
    def validate_wait_for(cls, v):
        if v and not validate_css_selector(v):
            raise ValueError(f"Invalid or unsafe selector: {v}")
        return v

class ClickRequest(BaseModel):
    """Click request model"""
    selector: Optional[str] = Field(None, max_length=500)
    text: Optional[str] = Field(None, max_length=500)
    wait_after: float = Field(1.0, ge=0, le=10)

    @field_validator('selector')
    @classmethod
    def validate_selector(cls, v):
        if v and not validate_css_selector(v):
            raise ValueError(f"Invalid or unsafe selector: {v}")
        return v

class ExtractionRequest(BaseModel):
    """Extraction request with metadata support"""
    selector: Optional[str] = Field(None, max_length=500, description="CSS selector")
    extract_text: bool = Field(True, description="Extract text content")
    extract_href: bool = Field(False, description="Extract href attributes")
    extract_all: bool = Field(False, description="Extract from all matching elements")
    extract_attributes: Optional[List[str]] = Field(None, description="List of attributes to extract")

    # New fields for extraction
    extraction_strategy: Optional[str] = Field(
        "auto",
        description="Extraction strategy: auto|visible|all|js",
        pattern="^(auto|visible|all|js)$"
    )
    include_metadata: Optional[bool] = Field(
        False,
        description="Include element metadata (tag, classes, position)"
    )
    max_depth: Optional[int] = Field(
        None,
        description="Max depth for recursive extraction",
        ge=1,
        le=60
    )
    timeout: Optional[int] = Field(
        300,
        description="Timeout for element finding in seconds",
        ge=1,
        le=350
    )
    force_refresh: Optional[bool] = Field(
        False,
        description="Bypass cache and force fresh extraction"
    )
    return_html: Optional[bool] = Field(
        False,
        description="Return HTML in addition to text"
    )

class ExtractionRequestComplete(BaseModel):
    """Complete extraction request model for unified extraction endpoint"""
    selector: Optional[str] = Field(None, max_length=500, description="CSS selector")
    xpath: Optional[str] = Field(None, max_length=500, description="XPath selector")
    extract_all: bool = Field(False, description="Extract from all matching elements")
    extract_text: bool = Field(True, description="Extract text content")
    extract_href: bool = Field(False, description="Extract href attributes")
    force_refresh: bool = Field(False, description="Bypass cache and force fresh extraction")
    use_cache: bool = Field(True, description="Use caching for extraction")
    include_metadata: bool = Field(True, description="Include element metadata")
    format_style: str = Field("compact", description="Output format: compact|full|structured")

    @field_validator('selector')
    @classmethod
    def validate_selector(cls, v):
        if v and not validate_css_selector(v):
            raise ValueError(f"Invalid or unsafe selector: {v}")
        return v

    @field_validator('xpath')
    @classmethod
    def validate_xpath(cls, v):
        if v:
            # XPath validation and XSS prevention
            dangerous_patterns = [
                'javascript:', '<script', 'onerror=', 'onclick=',
                'onload=', '<iframe', 'data:', 'vbscript:'
            ]
            for pattern in dangerous_patterns:
                if pattern in v.lower():
                    raise ValueError(f"Invalid xpath: XSS attempt blocked - {pattern}")
        return v

class SubstackRequest(BaseModel):
    """Substack-specific request validation"""
    publication_url: HttpUrl
    max_posts: int = Field(20, ge=1, le=100)

    @field_validator('publication_url')
    @classmethod
    def validate_substack_url(cls, v):
        url_str = str(v)
        if 'substack.com' not in url_str:
            raise ValueError("Must be a Substack URL")
        return v

class SubstackPublicationRequest(BaseModel):
    """Substack publication request"""
    publication_url: HttpUrl

    @field_validator('publication_url')
    @classmethod
    def validate_substack_url(cls, v):
        url_str = str(v)
        if 'substack.com' not in url_str:
            raise ValueError("Must be a Substack URL")
        return v

class TypeRequest(BaseModel):
    """Type text request with content validation"""
    text: str = Field(..., min_length=1, max_length=10000)
    selector: Optional[str] = Field(None, max_length=500)
    clear_first: bool = True
    press_enter: bool = False
    delay: float = Field(0.14, ge=0, le=1)

    @field_validator('text')
    @classmethod
    def validate_text_content(cls, v):
        # Prevent injection of control characters
        control_chars = ['\x00', '\x1b', '\x7f']
        for char in control_chars:
            if char in v:
                raise ValueError("Text contains invalid control characters")
        return v

    @field_validator('selector')
    @classmethod
    def validate_selector(cls, v):
        if v and not validate_css_selector(v):
            raise ValueError(f"Invalid or unsafe selector: {v}")
        return v