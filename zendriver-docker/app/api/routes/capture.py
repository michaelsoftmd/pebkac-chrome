"""
Page capture and screenshot routes
"""

import os
import re
from typing import Annotated, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Body, Depends
import logging

from app.core.config import Settings, get_settings
from app.core.browser import BrowserManager
from app.core.exceptions import ElementNotFoundError
from app.core.timeouts import TIMEOUTS
from app.api.dependencies import get_browser_manager
from app.services.extraction import UnifiedExtractionService
from app.utils.browser_utils import safe_evaluate

logger = logging.getLogger(__name__)

router = APIRouter()


# ===========================
# Export Operations
# ===========================

@router.post("/capture/page_markdown")
async def capture_page_as_markdown(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    settings: Annotated[Settings, Depends(get_settings)],
    include_metadata: bool = Body(True, description="Include page metadata"),
    use_trafilatura: bool = Body(True, description="Use Trafilatura for better extraction")
):
    """Capture current page content as markdown"""
    tab = await browser_manager.get_tab()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Get page URL and title
    current_url = await safe_evaluate(tab, "window.location.href")
    page_title = await safe_evaluate(tab, "document.title")

    # Extract content
    if use_trafilatura:
        # Use Trafilatura for high-quality extraction
        from app.services.extraction import UnifiedExtractionService
        extraction_service = UnifiedExtractionService(browser_manager, None)
        result = await extraction_service.extract_with_trafilatura(tab)

        if result and result.get("status") == "success":
            content = result["content"]["main_text"]
            metadata = result["metadata"]
        else:
            # Fallback to basic extraction
            content = await safe_evaluate(tab, "document.body.innerText")
            metadata = {"title": page_title, "url": current_url}
    else:
        # Basic extraction
        content = await safe_evaluate(tab, "document.body.innerText")
        metadata = {"title": page_title, "url": current_url}

    # Build markdown
    md_content = f"# {metadata.get('title', 'Untitled')}\n\n"

    if include_metadata:
        md_content += f"**URL:** {metadata.get('url', current_url)}\n"
        md_content += f"**Exported:** {datetime.now().isoformat()}\n"
        if metadata.get('author'):
            md_content += f"**Author:** {metadata['author']}\n"
        if metadata.get('date'):
            md_content += f"**Date:** {metadata['date']}\n"
        if metadata.get('description'):
            md_content += f"**Description:** {metadata['description']}\n"
        md_content += "\n---\n\n"

    # Add main content
    md_content += content if content else "No content extracted"

    # Save file to tmp directory (same pattern as screenshots)
    exports_dir = '/tmp/exports'
    os.makedirs(exports_dir, exist_ok=True)

    # Clean filename from title
    safe_title = re.sub(r'[^\w\s-]', '', page_title or 'page')[:50]
    filename = f"{timestamp}_{safe_title}.md"
    filepath = os.path.join(exports_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md_content)

    return {
        "status": "success",
        "filename": filename,
        "path": filepath,
        "size_bytes": len(md_content.encode('utf-8')),
        "url": current_url,
        "title": page_title
    }

@router.post("/screenshot")
async def take_screenshot(
    browser_manager: Annotated[BrowserManager, Depends(get_browser_manager)],
    selector: Optional[str] = Body(None, description="CSS selector of element to screenshot"),
    full_page: bool = Body(False, description="Capture full page"),
    format: str = Body("png", description="jpeg or png")
):
    """Take screenshot of page or element"""
    tab = await browser_manager.get_tab()

    try:
        # Screenshot directory - use system /tmp (always writable)
        screenshot_dir = '/tmp/screenshots'
        os.makedirs(screenshot_dir, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        screenshot_filename = f"screenshot_{timestamp}.{format}"
        screenshot_path = os.path.join(screenshot_dir, screenshot_filename)

        # Take screenshot
        if selector:
            element = await tab.find(selector, timeout=TIMEOUTS.element_find)
            if not element:
                raise ElementNotFoundError(f"Element not found: {selector}")
            filename = await element.save_screenshot(filename=screenshot_path, format=format)
        else:
            filename = await tab.save_screenshot(filename=screenshot_path, format=format, full_page=full_page)

        return {
            "status": "success",
            "path": filename,
            "format": format
        }
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
