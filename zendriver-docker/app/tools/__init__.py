"""
Browser automation tools for SmolAgents integration - copied from openapi-server/main.py
"""

from .browser_tools import NavigateBrowserTool, GetCurrentURLTool, ClickElementTool, TypeTextTool, KeyboardNavigationTool
from .extraction_tools import ExtractContentTool, ParallelExtractionTool, GarboPageMarkdownTool
from .search_tools import WebSearchTool, SearchHistoryTool, VisitWebpageTool
from .cloudflare_tools import CloudflareBypassTool
from .utility_tools import ScreenshotTool, GetElementPositionTool, InterceptNetworkTool

__all__ = [
    # Browser control
    'NavigateBrowserTool',
    'GetCurrentURLTool',
    'ClickElementTool',
    'TypeTextTool',
    'KeyboardNavigationTool',

    # Content extraction
    'ExtractContentTool',
    'ParallelExtractionTool',
    'GarboPageMarkdownTool',

    # Search and navigation
    'WebSearchTool',
    'SearchHistoryTool',
    'VisitWebpageTool',

    # Security
    'CloudflareBypassTool',

    # Utilities
    'ScreenshotTool',
    'GetElementPositionTool',
    'InterceptNetworkTool'
]