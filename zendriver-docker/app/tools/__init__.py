"""
Browser automation tools for SmolAgents integration - copied from openapi-server/main.py
"""

from .browser_tools import NavigateBrowserTool, GetCurrentURLTool, ClickElementTool, TypeTextTool, KeyboardNavigationTool
from .extraction_tools import ExtractContentTool, ParallelExtractionTool, CapturePageMarkdownTool
from .search_tools import WebSearchTool, SearchHistoryTool, VisitWebpageTool
from .cloudflare_tools import CloudflareBypassTool
from .utility_tools import ScreenshotTool, GetElementPositionTool, CaptureAPIResponseTool
from .tab_tools import OpenBackgroundTabTool, ListTabsTool, CloseTabTool

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
    'CapturePageMarkdownTool',

    # Search and navigation
    'WebSearchTool',
    'SearchHistoryTool',
    'VisitWebpageTool',

    # Security
    'CloudflareBypassTool',

    # Utilities
    'ScreenshotTool',
    'GetElementPositionTool',
    'CaptureAPIResponseTool',

    # Tab management
    'OpenBackgroundTabTool',
    'ListTabsTool',
    'CloseTabTool'
]