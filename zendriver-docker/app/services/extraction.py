# app/services/extraction.py
import asyncio
import logging
import time
import hashlib
import trafilatura
from trafilatura import bare_extraction, baseline, extract_metadata
from typing import Optional, Dict, Any, List
from app.core.exceptions import ElementNotFoundError
from app.utils.browser_utils import safe_evaluate

logger = logging.getLogger(__name__)

class UnifiedExtractionService:
    def __init__(self, browser_manager, cache_service=None):
        self.browser_manager = browser_manager
        self.cache = cache_service
    
    async def extract_with_trafilatura(self, tab) -> Dict[str, Any]:
        """Extract content using Trafilatura with full metadata"""
        try:
            
            # Get HTML and URL using safe_evaluate
            html = await safe_evaluate(tab, "document.documentElement.outerHTML")
            url = await safe_evaluate(tab, "window.location.href")
            
            # Ensure we have strings
            if not html or not isinstance(html, str):
                logger.warning("Could not get HTML content for Trafilatura")
                return None
                
            if not url or not isinstance(url, str):
                url = ""
            
            # Extract structured data (JSON-LD) for product/price information
            structured_data = await safe_evaluate(tab, """
                (() => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    const data = [];
                    scripts.forEach(s => {
                        try {
                            const json = JSON.parse(s.textContent);
                            if (json['@type'] === 'Product' || json.price || 
                                (json.offers && json.offers.price)) {
                                data.push(json);
                            }
                        } catch(e) {}
                    });
                    return data;
                })()
            """)
            
            # Now use trafilatura with proper string inputs
            text_output = trafilatura.extract(
                html,
                url=url,
                favor_precision=False,
                include_comments=False,
                include_tables=True,
                with_metadata=True,
                output_format='json',
            )
            
            if text_output:
                import json
                result = json.loads(text_output)
                
                # Process structured data for price information
                price_info = {}
                if structured_data and isinstance(structured_data, list):
                    for item in structured_data:
                        if isinstance(item, dict):
                            if 'offers' in item and isinstance(item['offers'], dict):
                                price = item['offers'].get('price')
                                currency = item['offers'].get('priceCurrency')
                                if price:
                                    price_info['price'] = price
                                    price_info['currency'] = currency
                                    break
                            elif item.get('price'):
                                price_info['price'] = item.get('price')
                                price_info['currency'] = item.get('priceCurrency')
                                break
                
                metadata = {
                    "title": result.get('title'),
                    "author": result.get('author'),
                    "date": result.get('date'),
                    "description": result.get('description'),
                    "sitename": result.get('sitename'),
                    "hostname": result.get('hostname')
                }
                
                # Add price information if found
                if price_info:
                    metadata.update(price_info)
                
                return {
                    "status": "success",
                    "method": "trafilatura",
                    "content": {
                        "main_text": result.get('text', ''),
                        "comments": result.get('comments', ''),
                        "raw_text": result.get('raw_text', '')
                    },
                    "metadata": metadata
                }
                
            return None
            
        except Exception as e:
            logger.error(f"Trafilatura extraction failed: {e}")
            return None
    
    async def extract_with_bare(self, tab) -> Dict[str, Any]:
        """
        Use bare_extraction for structured Python dict output.
        Perfect for caching as it returns native Python objects.
        """
        try:
            html = await safe_evaluate(tab, "document.documentElement.outerHTML")
            html = str(html) if html else ""
        except Exception as e:
            logger.error(f"Failed to get HTML: {e}")
            html = ""
            
        try:
            url = await safe_evaluate(tab, "window.location.href")
            url = str(url) if url else ""
        except Exception as e:
            logger.error(f"Failed to get URL: {e}")
            url = ""
        
        if not html:
            return {
                'status': 'error',
                'error': 'Could not retrieve HTML from page'
            }
        
        # Use bare_extraction for structured data
        doc_dict = bare_extraction(
            html,
            url=url,
            favor_precision=True,
            include_comments=False,
            include_tables=True,
            deduplicate=True,
            target_language='en'
        )
        
        if doc_dict:
            result = {
                'status': 'success',
                'method': 'bare_extraction',
                'data': {
                    'text': doc_dict.get('text', ''),
                    'title': doc_dict.get('title'),
                    'author': doc_dict.get('author'),
                    'date': doc_dict.get('date'),
                    'sitename': doc_dict.get('sitename'),
                    'description': doc_dict.get('description'),
                    'categories': doc_dict.get('categories', []),
                    'tags': doc_dict.get('tags', []),
                    'license': doc_dict.get('license'),
                    'comments': doc_dict.get('comments', ''),
                    'raw_text': doc_dict.get('raw_text', ''),
                    'language': doc_dict.get('language'),
                    'image': doc_dict.get('image'),
                    'pagetype': doc_dict.get('pagetype')
                },
                'metadata': {
                    'url': url,
                    'hostname': doc_dict.get('hostname'),
                    'fingerprint': doc_dict.get('fingerprint'),
                    'id': doc_dict.get('id'),
                    'extraction_timestamp': time.time()
                },
                'formatted_output': self._format_compact(doc_dict, url)
            }
            
            # Cache if service available
            if self.cache:
                await self._cache_result(url, 'bare_extraction', result)
            
            return result
        
        return {
            'status': 'error',
            'method': 'bare_extraction',
            'error': 'bare_extraction returned no data'
        }
    
    async def extract_with_baseline(self, tab) -> Dict[str, Any]:
        """
        Use baseline for better precision/recall balance.
        Returns structured result with body element, text, and length.
        """
        try:
            html = await safe_evaluate(tab, "document.documentElement.outerHTML")
            html = str(html) if html else ""
        except Exception as e:
            logger.error(f"Failed to get HTML: {e}")
            html = ""
            
        try:
            url = await safe_evaluate(tab, "window.location.href")
            url = str(url) if url else ""
        except Exception as e:
            logger.error(f"Failed to get URL: {e}")
            url = ""
        
        if not html:
            return {
                'status': 'error',
                'error': 'Could not retrieve HTML from page'
            }
        
        try:
            body_element, text, text_length = baseline(html)
        except Exception as e:
            logger.error(f"Baseline extraction failed: {e}")
            return {
                'status': 'error',
                'method': 'baseline',
                'error': str(e)
            }
        
        result = {
            'status': 'success',
            'method': 'baseline',
            'data': {
                'text': text if text else '',
                'text_length': text_length,
                'has_body': body_element is not None
            },
            'metadata': {
                'url': url,
                'precision_focused': True,
                'extraction_quality': self._assess_quality(text_length),
                'extraction_timestamp': time.time()
            },
            'formatted_output': self._format_compact({'text': text}, url)
        }
        
        # Cache if service available
        if self.cache:
            await self._cache_result(url, 'baseline', result)
        
        return result
    
    
    def _assess_quality(self, text_length: int) -> str:
        """Assess extraction quality based on text length."""
        if text_length < 100:
            return 'low'
        elif text_length < 500:
            return 'medium'
        elif text_length < 2000:
            return 'high'
        else:
            return 'very_high'
    
    def _get_first_words(self, text: str, word_limit: int = 200) -> str:
        """Get first N words without truncating mid-sentence"""
        if not text:
            return ""
        
        words = text.split()
        if len(words) <= word_limit:
            return text
        
        # Take first word_limit words
        selected_words = words[:word_limit]
        partial_text = ' '.join(selected_words)
        
        # Find last sentence boundary within our limit
        last_period = partial_text.rfind('. ')
        last_exclamation = partial_text.rfind('! ')
        last_question = partial_text.rfind('? ')
        
        last_sentence = max(last_period, last_exclamation, last_question)
        
        if last_sentence > len(partial_text) * 0.7:  # If we keep 70%+ content
            return partial_text[:last_sentence + 1]
        
        return partial_text  # Return as-is if no good break point
    
    def _format_compact(self, data: Dict, url: str, links: list = None) -> str:
        """Compact formatting with essential metadata only"""

        # Essential metadata
        result = f"URL: {url}\n"

        if data.get('title'):
            result += f"Title: {data['title']}\n"
        if data.get('author'):
            result += f"Author: {data['author']}\n"
        if data.get('date'):
            result += f"Date: {data['date']}\n"
        if data.get('sitename'):
            result += f"Site: {data['sitename']}\n"
        if data.get('description'):
            result += f"Description: {data['description']}\n"

        # Price info if available
        if data.get('price'):
            price_text = f"Price: {data['price']}"
            if data.get('currency'):
                price_text += f" {data['currency']}"
            result += f"{price_text}\n"

        # Content (100-250 words)
        text = data.get('text', '')
        if text:
            content = self._get_first_words(text, word_limit=200)
            result += f"\n{content}"

        # Links if available
        if links:
            result += f"\n\nLinks found: {len(links)}\n"
            for link in links[:10]:  # First 10 links
                if isinstance(link, dict):
                    link_text = link.get('text', '')[:50]
                    link_href = link.get('href', '')
                    if link_text and link_href:
                        result += f"- {link_text}: {link_href}\n"

        return result
    
    def _format_for_openwebui(self, doc_dict: Dict, url: str) -> str:
        """Format extraction results for Open WebUI display."""
        output = f"""# Extracted Content

**URL:** {url}
**Title:** {doc_dict.get('title', 'Unknown')}
**Author:** {doc_dict.get('author', 'Not specified')}
**Date:** {doc_dict.get('date', 'Not specified')}
**Site:** {doc_dict.get('sitename', 'Unknown')}
**Language:** {doc_dict.get('language', 'Unknown')}
**Description:** {doc_dict.get('description', 'None')}
"""
        
        # Add categories and tags if present
        if doc_dict.get('categories'):
            output += f"**Categories:** {', '.join(doc_dict['categories'])}\n"
        if doc_dict.get('tags'):
            output += f"**Tags:** {', '.join(doc_dict['tags'])}\n"
        
        # Add main content
        text = doc_dict.get('text', '')
        if text:
            output += f"""

## Content

{text[:5000]}{"..." if len(text) > 5000 else ""}

## Statistics
- Word Count: {len(text.split())}
- Character Count: {len(text)}
- Reading Time: {len(text.split()) / 200:.1f} minutes
- Extraction Method: Trafilatura (bare_extraction)
"""
        
        # Add comments if present
        comments = doc_dict.get('comments', '')
        if comments:
            output += f"""

## Comments

{comments[:1000]}{"..." if len(comments) > 1000 else ""}
"""
        
        return output
    
    def _format_baseline_output(self, text: str, text_length: int, url: str) -> str:
        """Format baseline extraction results for display."""
        return f"""# Extracted Content (Baseline Method)

**URL:** {url}
**Extraction Method:** Trafilatura Baseline (High Precision)

## Content

{text[:5000] if text else '(No content extracted)'}{"..." if text and len(text) > 5000 else ""}

## Statistics
- Text Length: {text_length} characters
- Word Count: {len(text.split()) if text else 0}
- Reading Time: {(len(text.split()) / 200 if text else 0):.1f} minutes
- Quality Assessment: {self._assess_quality(text_length)}
"""
    
    async def _cache_result(self, url: str, method: str, result: Dict):
        """Cache extraction result with appropriate TTL."""
        try:
            ttl = self._determine_ttl(result)
            cache_key = f"extraction:{method}:{hashlib.md5(url.encode()).hexdigest()}"
            
            result['cache_metadata'] = {
                'cached_at': time.time(),
                'ttl': ttl,
                'method': method
            }
            
            await self.cache.set(cache_key, result, ttl)
            
        except Exception as e:
            logger.warning(f"Failed to cache result: {e}")
    
    def _determine_ttl(self, result: Dict) -> int:
        """Determine appropriate TTL based on content."""
        data = result.get('data', {})
        
        # News/articles with dates - shorter TTL
        if data.get('date'):
            return 3600  # 1 hour
        
        # Pages with comments - medium TTL
        if data.get('comments'):
            return 7200  # 2 hours
        
        # Static content - longer TTL
        return 86400  # 24 hours
    
    async def extract_universal_content(self, tab) -> Dict[str, Any]:
        """Progressive selector fallback extraction"""
        
        # Progressive selectors from most semantic to least
        content_selectors = [
            # Semantic HTML5
            "main article, main section, [role='main']",
            # Common content containers  
            "#content, #main-content, .content, .main-content",
            "#mw-content-text, .mw-parser-output",  # Wikipedia
            # Article containers
            "article, .article, .post, .entry",
            # Generic content areas with explicit exclusions
            "body section:not([class*='nav']):not([class*='menu']):not([class*='sidebar'])",
            "body div[class*='content']:not([class*='nav']):not([class*='menu'])"
        ]
        
        title_selectors = [
            "h1.firstHeading",  # Wikipedia
            "h1",               # Generic
            "title",            # Fallback
            ".title, .headline, .page-title"
        ]
        
        result = {
            "status": "success",
            "method": "progressive_selectors",
            "content": {
                "main_text": "",
                "title": None
            },
            "metadata": {
                "url": None,
                "extraction_method": "none",
                "content_length": 0
            }
        }
        
        try:
            # Get current URL
            current_url = await safe_evaluate(tab, "window.location.href")
            result["metadata"]["url"] = current_url or ""
            
            # Extract title using progressive selectors
            for title_selector in title_selectors:
                try:
                    title_element = await tab.find(title_selector, timeout=2)
                    if title_element and title_element.text.strip():
                        result["content"]["title"] = title_element.text.strip()
                        result["metadata"]["title"] = title_element.text.strip()
                        break
                except:
                    continue
            
            # Extract main content using progressive selectors
            for selector in content_selectors:
                try:
                    element = await tab.find(selector, timeout=3)
                    if element:
                        text_content = element.text
                        # Validate content quality
                        if text_content and len(text_content.strip()) > 100:
                            # Check if content looks like CSS/JS
                            content_lower = text_content.lower().strip()
                            css_indicators = [
                                'var(--', '{', '}', 'color:', 'background:', 'margin:', 'padding:', 
                                '.css', 'stylesheet', '/* copyright', 'font-size:', 'display:', 'font-family:'
                            ]
                            js_indicators = [
                                'function(', 'var ', 'let ', 'const ', 'document.', 'window.'
                            ]
                            
                            # Skip if content looks like CSS or JS
                            if any(indicator in content_lower for indicator in css_indicators + js_indicators):
                                continue
                                
                            # Should contain common text patterns
                            text_indicators = [' the ', ' and ', ' of ', ' to ', ' in ', ' a ']
                            if any(indicator in content_lower for indicator in text_indicators):
                                result["content"]["main_text"] = text_content.strip()
                                result["metadata"]["extraction_method"] = f"selector: {selector}"
                                result["metadata"]["content_length"] = len(text_content)
                                break
                except:
                    continue
            
            # If no good content found, try paragraph aggregation
            if not result["content"]["main_text"]:
                try:
                    paragraphs = await tab.find_all("p", timeout=3)
                    if paragraphs:
                        combined_text = []
                        for p in paragraphs[:20]:  # Get more paragraphs
                            if p.text and len(p.text.strip()) > 50:
                                combined_text.append(p.text.strip())
                        
                        if combined_text:
                            result["content"]["main_text"] = "\n\n".join(combined_text)
                            result["metadata"]["extraction_method"] = "paragraph_aggregation"
                            result["metadata"]["paragraph_count"] = len(combined_text)
                except:
                    pass
            
            return result
            
        except Exception as e:
            result["status"] = "error"
            result["metadata"]["error"] = str(e)
            return result
    
    async def extract(self, 
                     selector: Optional[str] = None,
                     xpath: Optional[str] = None,
                     extract_all: bool = False,
                     extract_text: bool = True,
                     extract_href: bool = True,
                     use_cache: bool = True,
                     include_metadata: bool = True) -> Dict[str, Any]:
        """Main extraction method with metadata for Open WebUI"""
        
        tab = await self.browser_manager.get_tab()
        current_url = await safe_evaluate(tab, "window.location.href")

        # Check for Cloudflare before extraction
        try:
            from app.core.cloudflare import cf_is_interactive_challenge_present
            
            if await cf_is_interactive_challenge_present(tab, timeout=5):
                # Try to solve it
                from app.core.cloudflare import verify_cf
                try:
                    await verify_cf(tab, timeout=15)
                    await asyncio.sleep(2)  # Wait for page to reload
                except TimeoutError:
                    return {
                        'status': 'error',
                        'error': 'Cloudflare challenge could not be solved',
                        'cloudflare_challenge': True
                    }
        except:
            pass  # Continue with extraction even if CF check fails
        
        # Check cache
        if use_cache and self.cache:
            cached = await self.cache.get_cached_extraction(
                current_url, 
                selector or xpath or 'universal'
            )
            if cached:
                cached['cached'] = True
                return cached
        
        # Initialize response with metadata structure
        response = {
            'status': 'success',
            'data': None,
            'formatted_output': '',  # For Open WebUI
            'metadata': {},
            'count': 0,
            'cached': False,
            'extraction_method': 'unknown'
        }

        # Use selector optimization if cache service available and no explicit selector
        if not selector and not xpath and self.cache:
            try:
                optimized_selector = await self.cache.get_optimized_selector(current_url, "general")
                if optimized_selector:
                    logger.info(f"Using optimized selector for {current_url}: {optimized_selector}")
                    selector = optimized_selector
                    response['extraction_method'] = 'optimized_selector'
            except Exception as e:
                logger.warning(f"Selector optimization failed: {e}")

        # No selector = use smart extraction
        if not selector and not xpath:
            # Try Trafilatura first
            trafilatura_result = await self.extract_with_trafilatura(tab)
            
            if trafilatura_result and trafilatura_result.get("status") == "success":
                # Format with metadata for Open WebUI
                text = trafilatura_result["content"]["main_text"]
                metadata = trafilatura_result["metadata"]
                
                response['data'] = {
                    'text': text,
                    'title': metadata.get('title'),
                    'metadata': metadata
                }
                response['metadata'] = metadata
                response['count'] = 1
                response['extraction_method'] = 'trafilatura'
                
                # Compact format for agent context conservation
                response['formatted_output'] = self._format_compact(metadata, current_url)
            else:
                # Fallback to progressive selectors
                fallback_result = await self.extract_universal_content(tab)
                
                text = fallback_result["content"]["main_text"]
                
                response['data'] = {
                    'text': text,
                    'title': fallback_result["content"].get('title'),
                    'metadata': fallback_result.get('metadata', {})
                }
                response['metadata'] = fallback_result.get('metadata', {})
                response['count'] = 1 if text else 0
                response['extraction_method'] = fallback_result.get('metadata', {}).get('extraction_method', 'progressive_selectors')
                
                # Compact format for fallback extraction
                fallback_data = {'text': text, 'title': fallback_result["content"].get('title')}
                response['formatted_output'] = self._format_compact(fallback_data, current_url)
        
        elif selector:
            # CSS selector extraction
            try:
                results = []
                
                if extract_all:
                    elements = await tab.find_all(selector, timeout=5)
                else:
                    element = await tab.find(selector, timeout=5)
                    elements = [element] if element else []
                
                for element in elements:
                    if element:
                        item = {}
                        
                        # Extract text
                        if extract_text and hasattr(element, 'text'):
                            text_content = element.text
                            if text_content:
                                item["text"] = text_content.strip()
                        
                        # Extract href for link elements
                        if extract_href:
                            try:
                                # For <a> elements, Zendriver stores href in element.attrs
                                if hasattr(element, 'attrs'):
                                    href_value = element.attrs.get('href', '')
                                    if href_value:
                                        # Convert relative to absolute URLs
                                        if href_value.startswith('/'):
                                            from urllib.parse import urljoin
                                            base_url = await safe_evaluate(tab, "window.location.origin")
                                            if base_url:
                                                href_value = urljoin(base_url, href_value)
                                        elif not href_value.startswith(('http://', 'https://', 'mailto:', 'tel:')):
                                            # Relative path without leading /
                                            from urllib.parse import urljoin
                                            current = await safe_evaluate(tab, "window.location.href")
                                            if current:
                                                href_value = urljoin(current, href_value)
                                        item["href"] = href_value
                            except Exception as e:
                                logger.warning(f"Failed to extract href from element: {e}")
                                # Continue without href
                        
                        # Only add if we got something
                        if item:
                            results.append(item)
                
                response['extraction_method'] = 'css_selector'
                response['data'] = results if extract_all else (results[0] if results else None)
                response['count'] = len(results)

                # Track selector performance for optimization
                if self.cache:
                    try:
                        from urllib.parse import urlparse
                        domain = urlparse(current_url).netloc
                        if domain:
                            success = len(results) > 0
                            await self.cache.track_selector_performance(domain, selector, success)
                    except Exception as e:
                        logger.warning(f"Failed to track selector performance: {e}")

                # Format response
                if results:
                    # Create text preview for formatted output
                    if extract_href and extract_text:
                        # Mixed data with text and hrefs - show both
                        lines = []
                        for item in results[:10]:
                            if isinstance(item, dict):
                                text = item.get('text', '')[:60]
                                href = item.get('href', '')
                                if text and href:
                                    lines.append(f"- {text}: {href}")
                                elif href:
                                    lines.append(f"- {href}")
                                elif text:
                                    lines.append(f"- {text}")
                        text_preview = '\n'.join(lines)
                    elif extract_href:
                        # Only hrefs
                        text_preview = '\n'.join([f"{item.get('href', '')}" for item in results[:10] if isinstance(item, dict)])
                    elif isinstance(results[0] if results else None, dict):
                        # Text in dict format
                        text_preview = '\n'.join([f"{item.get('text', '')}" for item in results[:10] if isinstance(item, dict)])
                    else:
                        # Legacy string format
                        text_preview = '\n'.join(results[:10])

                    response['formatted_output'] = f"""URL: {current_url}
Selector: {selector or xpath}
Elements: {len(results)}

{text_preview[:1200]}{"..." if len(text_preview) > 1200 else ""}"""
                        
            except Exception as e:
                logger.error(f"Selector extraction failed: {e}")
                response['status'] = 'error'
                response['error'] = str(e)

                # Track failed selector for optimization
                if self.cache:
                    try:
                        from urllib.parse import urlparse
                        domain = urlparse(current_url).netloc
                        if domain:
                            await self.cache.track_selector_performance(domain, selector, False)
                    except Exception as e:
                        logger.warning(f"Failed to track failed selector performance: {e}")
        
        # Cache successful extraction with metadata
        if use_cache and self.cache and response['status'] == 'success' and response.get('data'):
            try:
                await self.cache.cache_extraction(
                    current_url,
                    selector or xpath or 'universal',
                    response
                )
            except Exception as e:
                logger.warning(f"Cache save failed: {e}")
        
        return response
    
    async def extract_parallel(self, 
                              selectors: List[str], 
                              use_cache: bool = True) -> Dict[str, Any]:
        """Extract from multiple selectors in parallel"""
        tab = await self.browser_manager.get_tab()
        current_url = await safe_evaluate(tab, "window.location.href")
        
        # Check cache for each selector
        cache_results = {}
        uncached_selectors = []
        
        if use_cache and self.cache:
            for selector in selectors:
                cached = await self.cache.get_cached_extraction(current_url, selector)
                if cached:
                    cache_results[selector] = cached.get('data')
                else:
                    uncached_selectors.append(selector)
        else:
            uncached_selectors = selectors.copy()
        
        # Extract uncached selectors
        extraction_results = {}
        if uncached_selectors:
            tasks = []
            for selector in uncached_selectors:
                task = self._extract_single_selector(tab, selector)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for selector, result in zip(uncached_selectors, results):
                if not isinstance(result, Exception):
                    extraction_results[selector] = result
                    
                    # Cache successful extractions
                    if use_cache and self.cache and result:
                        try:
                            await self.cache.cache_extraction(
                                current_url, 
                                selector, 
                                {'status': 'success', 'data': result}
                            )
                        except:
                            pass
        
        # Combine results
        final_results = {**cache_results, **extraction_results}
        
        return {
            'status': 'success',
            'data': final_results,
            'count': len(final_results),
            'cached_count': len(cache_results),
            'extracted_count': len(extraction_results),
            'formatted_output': f"""URL: {current_url}
Parallel Extraction - {len(selectors)} selectors
Cached: {len(cache_results)}, Fresh: {len(extraction_results)}

{chr(10).join([f"{sel}: {len(str(final_results.get(sel, '')).split())} words" for sel in selectors[:10]])}"""
        }
    
    async def _extract_single_selector(self, tab, selector: str) -> Optional[str]:
        """Extract text from a single selector"""
        try:
            element = await tab.find(selector, timeout=3)
            if element:
                return element.text.strip()
            return None
        except:
            return None