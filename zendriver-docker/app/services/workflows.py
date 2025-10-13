import asyncio
from typing import List, Dict, Any
from app.core.exceptions import BrowserError
from app.utils.browser_utils import safe_evaluate
import random

class WorkflowService:
    """Service for complex workflows with async optimization"""
    def __init__(self, browser_manager):
        self.browser_manager = browser_manager
    
    async def analyze_multiple_publications(self, urls: List[str]) -> List[Dict]:
        """Analyze multiple publications concurrently"""
        # Create tasks for concurrent execution
        tasks = []
        for url in urls:
            task = self._analyze_with_error_handling(url)
            tasks.append(task)
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        successful_results = []
        failed_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_results.append({
                    "url": urls[i],
                    "error": str(result)
                })
            else:
                successful_results.append(result)
        
        return {
            "successful": successful_results,
            "failed": failed_results,
            "total": len(urls),
            "success_rate": len(successful_results) / len(urls)
        }
    
    async def _analyze_with_error_handling(self, url: str) -> Dict:
        """Analyze single publication with error handling"""
        try:
            return await self._analyze_publication(url)
        except Exception as e:
            # Log error but don't fail entire batch
            return {"url": url, "error": str(e)}
    
    async def parallel_data_extraction(self, page, selectors: List[str]):
        """Extract data from multiple selectors in parallel"""
        tasks = []
        for selector in selectors:
            task = page.find(selector)
            tasks.append(task)
        
        elements = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = {}
        for selector, element in zip(selectors, elements):
            if not isinstance(element, Exception) and element:
                results[selector] = element.text
            else:
                results[selector] = None
        
        return results
    
    async def rate_limited_batch_operation(self, operations: List, rate_limit: float = 1.0):
        """Execute operations with rate limiting"""
        results = []
        
        for i, operation in enumerate(operations):
            # Execute operation
            result = await operation()
            results.append(result)
            
            # Rate limit (except for last item)
            if i < len(operations) - 1:
                await asyncio.sleep(rate_limit)
        
        return results

    async def _retry_with_backoff(self, func, max_retries: int = 3):
        """Simple exponential backoff retry"""
        for attempt in range(max_retries):
            try:
                return await func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(wait_time)

    async def _analyze_publication(self, url: str) -> Dict:
        """Analyze a single publication/website for content structure"""
        from urllib.parse import urlparse
        
        result = {
            "url": url,
            "domain": urlparse(url).netloc,
            "title": None,
            "meta": {},
            "content_structure": {},
            "navigation": [],
            "errors": []
        }
        
        try:
            # Navigate to the URL
            tab = await self.browser_manager.get_tab(url)
            await asyncio.sleep(2)  # Wait for page load
            
            # Get page title
            result["title"] = await safe_evaluate(tab, "() => document.title")
            
            # Extract meta information
            meta_info = await safe_evaluate(tab, """
                () => {
                    const meta = {};
                    // Get meta description
                    const desc = document.querySelector('meta[name="description"]');
                    if (desc) meta.description = desc.content;
                    
                    // Get meta keywords
                    const keywords = document.querySelector('meta[name="keywords"]');
                    if (keywords) meta.keywords = keywords.content;
                    
                    // Get Open Graph data
                    const ogTitle = document.querySelector('meta[property="og:title"]');
                    if (ogTitle) meta.ogTitle = ogTitle.content;
                    
                    const ogDesc = document.querySelector('meta[property="og:description"]');
                    if (ogDesc) meta.ogDescription = ogDesc.content;
                    
                    // Get canonical URL
                    const canonical = document.querySelector('link[rel="canonical"]');
                    if (canonical) meta.canonical = canonical.href;
                    
                    return meta;
                }
            """)
            result["meta"] = meta_info
            
            # Analyze content structure
            structure = await safe_evaluate(tab, """
                () => {
                    return {
                        hasHeader: !!document.querySelector('header'),
                        hasNav: !!document.querySelector('nav'),
                        hasMain: !!document.querySelector('main'),
                        hasFooter: !!document.querySelector('footer'),
                        articleCount: document.querySelectorAll('article').length,
                        headingCount: {
                            h1: document.querySelectorAll('h1').length,
                            h2: document.querySelectorAll('h2').length,
                            h3: document.querySelectorAll('h3').length
                        },
                        linkCount: document.querySelectorAll('a').length,
                        imageCount: document.querySelectorAll('img').length,
                        formCount: document.querySelectorAll('form').length
                    };
                }
            """)
            result["content_structure"] = structure
            
            # Extract main navigation links
            nav_links = await safe_evaluate(tab, """
                () => {
                    const links = [];
                    const navElement = document.querySelector('nav');
                    if (navElement) {
                        const anchors = navElement.querySelectorAll('a');
                        anchors.forEach(a => {
                            if (a.href && a.textContent) {
                                links.push({
                                    text: a.textContent.trim(),
                                    href: a.href
                                });
                            }
                        });
                    }
                    return links.slice(0, 10);  // Limit to 10 main nav items
                }
            """)
            result["navigation"] = nav_links
            
        except Exception as e:
            result["errors"].append(str(e))
            result["status"] = "failed"
        else:
            result["status"] = "success"
        
        return result
