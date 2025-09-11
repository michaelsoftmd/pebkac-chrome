from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List, Union
from datetime import datetime

class BaseResponse(BaseModel):
    """Base response model"""
    status: str = Field(..., description="Status: success or error")
    message: str = Field(..., description="Human-readable message")
    data: Optional[Any] = Field(None, description="Response data")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class NavigationResponse(BaseModel):
    """Navigation response"""
    url: str
    title: str
    status: str = "success"

class ClickResponse(BaseModel):
    """Click response"""
    status: str = "success"
    selector: Optional[str] = None
    text: Optional[str] = None

class ExtractionResult(BaseModel):
    """Standardized extraction result"""
    status: str = Field("success", description="Status: success, partial, or error")
    content: Optional[str] = Field(None, description="Main text content")
    links: Optional[List[Dict[str, str]]] = Field(None, description="Extracted links")
    elements: Optional[List[Dict[str, Any]]] = Field(None, description="Specific elements extracted")
    html: Optional[str] = Field(None, description="Raw HTML if requested")
    extraction_method: str = Field("standard", description="Method used: css, xpath, or auto")
    cached: bool = Field(False, description="Whether result was from cache")
    
class ExtractResponse(BaseModel):
    """Legacy extract response - keep for backward compatibility"""
    status: str = "success"
    count: int
    data: Any
