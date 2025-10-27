"""
Agent manager for SmolAgents integration with basic streaming support
"""

import os
import logging
import asyncio
import json
import time
from typing import Dict, Optional, AsyncGenerator, Any, List
from smolagents import OpenAIServerModel
from openai import OpenAI
from app.services.safe_code_agent import SafeCodeAgent

# Import tools
from app.tools import (
    NavigateBrowserTool,
    GetCurrentURLTool,
    ClickElementTool,
    TypeTextTool,
    KeyboardNavigationTool,
    ExtractContentTool,
    ParallelExtractionTool,
    CapturePageMarkdownTool,
    WebSearchTool,
    SearchHistoryTool,
    VisitWebpageTool,
    CloudflareBypassTool,
    ScreenshotTool,
    GetElementPositionTool,
    CaptureAPIResponseTool,
    OpenBackgroundTabTool,
    ListTabsTool,
    CloseTabTool
)

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages SmolAgents CodeAgent instances with llama.cpp integration"""

    def __init__(self, llama_cpp_url: str = None, database_manager = None):
        self.llama_cpp_url = llama_cpp_url or os.getenv("ACTIVE_OPENAI_URL", "http://llama-cpp-server:8080/v1")
        # Tools call localhost since AgentManager runs inside zendriver container
        self.zendriver_api_url = os.getenv("ZENDRIVER_API_URL", "http://localhost:8080")
        self.duckdb_url = os.getenv("DUCKDB_URL", "http://duckdb-cache:9001")
        self.max_steps = int(os.getenv("SMOLAGENTS_MAX_STEPS", "10"))

        # Track active tasks for cancellation
        self.active_tasks: Dict[str, asyncio.Task] = {}

        # Store last completed result for reconnection (single-user system)
        self.last_result: Optional[str] = None
        self.last_result_time: Optional[float] = None
        self.last_query: Optional[str] = None

        # Stream configuration
        self.stream_chunk_size = int(os.getenv("AGENT_STREAM_CHUNK_SIZE", "75"))

        # Database manager for execution history
        self.db_manager = database_manager

        # Create OpenAI client pointing to llama.cpp
        self.openai_client = OpenAI(
            base_url=self.llama_cpp_url,
            api_key="dummy"  # llama.cpp doesn't need real key
        )

        # Initialize tools
        self.tools = self._initialize_tools()
        logger.info(f"AgentManager initialized with {len(self.tools)} tools")

    def _initialize_tools(self) -> List:
        """Initialize all browser automation tools with API URLs"""
        return [
            # Browser control
            NavigateBrowserTool(self.zendriver_api_url),
            GetCurrentURLTool(self.zendriver_api_url),
            ClickElementTool(self.zendriver_api_url),
            TypeTextTool(self.zendriver_api_url),
            KeyboardNavigationTool(self.zendriver_api_url),

            # Content extraction
            ExtractContentTool(self.zendriver_api_url),
            ParallelExtractionTool(self.zendriver_api_url),
            CapturePageMarkdownTool(self.zendriver_api_url),

            # Search and navigation
            WebSearchTool(self.zendriver_api_url),
            SearchHistoryTool(self.duckdb_url),
            VisitWebpageTool(self.zendriver_api_url),

            # Security
            CloudflareBypassTool(self.zendriver_api_url),

            # Utilities
            ScreenshotTool(self.zendriver_api_url),
            GetElementPositionTool(self.zendriver_api_url),
            CaptureAPIResponseTool(self.zendriver_api_url),

            # Tab management
            OpenBackgroundTabTool(self.zendriver_api_url),
            ListTabsTool(self.zendriver_api_url),
            CloseTabTool(self.zendriver_api_url)
        ]

    def create_agent(self) -> SafeCodeAgent:
        """Create a new SafeCodeAgent instance"""
        try:
            model = OpenAIServerModel(
                model_id="local-model",
                client=self.openai_client
            )

            agent = SafeCodeAgent(
                tools=self.tools,
                model=model,
                max_steps=self.max_steps,
                additional_authorized_imports=["json", "time", "re"],
                use_structured_outputs_internally=False,
                return_full_result=True  # Get full result object for better inspection
            )

            logger.info(f"Created SafeCodeAgent with {len(self.tools)} tools, max_steps={self.max_steps}")
            return agent

        except Exception as e:
            logger.error(f"Failed to create agent: {e}")
            raise

    async def run_agent_streaming(
        self,
        query: str,
        conversation_history: List[Dict] = None,
        request_id: str = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run agent with streaming progress indicators

        Yields dictionaries with:
        - type: 'status' | 'content' | 'error' | 'done'
        - data: status info or content chunk

        Args:
            query: User query to process
            conversation_history: Past conversation context
            request_id: Unique ID for this request (for cancellation support)
        """

        logger.info(f"Agent query: {query[:50]}...")
        task = None

        try:
            yield {"type": "status", "data": "Initializing agent..."}

            agent = self.create_agent()
            yield {"type": "status", "data": "Agent ready, processing query..."}

            context = self._build_context(conversation_history) if conversation_history else ""
            full_query = f"{context}\n\nUser: {query}" if context else query

            yield {"type": "status", "data": "Running agent..."}

            task = asyncio.create_task(asyncio.to_thread(agent.run, full_query))

            # Track task if request_id provided
            if request_id:
                self.active_tasks[request_id] = task

            while not task.done():
                try:
                    result = await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
                    break
                except asyncio.TimeoutError:
                    yield {"type": "status", "data": "Agent working..."}
                except asyncio.CancelledError:
                    logger.info(f"Agent task cancelled for request: {request_id}")
                    yield {"type": "error", "data": "Request cancelled"}
                    return

            yield {"type": "status", "data": "Processing results..."}

            # Extract result from agent response (with return_full_result=True, we get a result object)
            # Check for final_answer attribute first (the successful completion case)
            if hasattr(result, 'output') and result.output is not None:
                # Result object with output attribute (successful final_answer call)
                formatted_result = result.output
                logger.info(f"Agent completed with final_answer: {str(formatted_result)[:100]}")
            elif hasattr(result, 'final_answer') and result.final_answer:
                # Alternative attribute name
                formatted_result = result.final_answer
                logger.info(f"Agent completed with final_answer attribute: {str(formatted_result)[:100]}")
            elif isinstance(result, str):
                # Direct string return (shouldn't happen with return_full_result=True)
                formatted_result = result
                logger.warning(f"Got unexpected string result: {formatted_result[:100]}")
            else:
                # Agent didn't complete with final_answer - extract from logs or error
                logger.warning(f"Agent did not call final_answer(). Result type: {type(result)}")
                if hasattr(result, 'logs') and result.logs:
                    formatted_result = f"Agent reached max_steps without final_answer. Last step: {result.logs[-1]}"
                else:
                    formatted_result = f"Agent failed to complete task. Result: {str(result)[:200]}"

            # Smart formatting: search results → markdown, other dicts → JSON
            if isinstance(formatted_result, dict) and "results" in formatted_result and "query" in formatted_result:
                # Auto-format search results as beautiful markdown
                md = f"### Search: {formatted_result['query']}\n\n"
                results = formatted_result['results']
                for i, r in enumerate(results[:10], 1):  # Limit to 10 for display
                    title = r.get('title', 'Untitled')
                    url = r.get('url', '#')
                    domain = r.get('domain', '')
                    md += f"{i}. **[{title}]({url})** `{domain}`\n"
                if len(results) > 10:
                    md += f"\n*...and {len(results) - 10} more results*\n"
                formatted_result = md
            elif isinstance(formatted_result, (dict, list)):
                # Other dicts/lists stay as JSON
                formatted_result = json.dumps(formatted_result, indent=2, ensure_ascii=False)
            elif not isinstance(formatted_result, str):
                formatted_result = str(formatted_result)

            # Store result for potential reconnection
            self.last_result = formatted_result
            self.last_result_time = time.time()
            self.last_query = query

            # Save execution history to SQLite
            if self.db_manager:
                try:
                    step_count = len(result.logs) if hasattr(result, 'logs') else 0
                    execution_data = {
                        "query": query,
                        "result": formatted_result[:1000],  # Truncate to 1000 chars for storage
                        "step_count": step_count,
                        "completed_at": time.time(),
                        "status": "completed" if hasattr(result, 'output') and result.output else "incomplete"
                    }

                    workflow_id = request_id or f"exec_{int(time.time())}"
                    topic = query[:200] if len(query) > 200 else query

                    self.db_manager.save_research_session(
                        workflow_id=workflow_id,
                        topic=topic,
                        data=execution_data
                    )
                    logger.info(f"Saved execution to research sessions: {workflow_id}")
                except Exception as e:
                    logger.warning(f"Failed to save research session: {e}")  # Non-critical

            for i in range(0, len(formatted_result), self.stream_chunk_size):
                chunk = formatted_result[i:i+self.stream_chunk_size]
                yield {"type": "content", "data": chunk}
                await asyncio.sleep(0.02)

            yield {"type": "done", "data": ""}
            logger.info("Agent completed successfully")

        except asyncio.CancelledError:
            logger.info(f"Client disconnected for request: {request_id}, task will continue in background")
            # Don't cancel task - let it complete in background
            # Task will store result in self.last_result when done
            return  # Stop yielding, but task continues

        except Exception as e:
            logger.error(f"AGENT_MANAGER: Exception in run_agent_streaming: {e}", exc_info=True)
            yield {
                "type": "error",
                "data": f"Agent error: {str(e)}"
            }

        finally:
            # Clean up task tracking
            if request_id and request_id in self.active_tasks:
                del self.active_tasks[request_id]

    def _build_context(self, history: List[Dict]) -> str:
        """Build conversation context from history"""
        if not history:
            return ""

        context_lines = []
        for msg in history[-6:]:  # Last 6 messages
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if content:  # Only add non-empty messages
                context_lines.append(f"{role.title()}: {content}")

        return "\n".join(context_lines) if context_lines else ""

    async def cancel_agent(self, request_id: str) -> bool:
        """
        Cancel a running agent task

        Args:
            request_id: Request ID to cancel

        Returns:
            True if task was found and cancelled, False otherwise
        """
        if request_id in self.active_tasks:
            task = self.active_tasks[request_id]
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled agent task: {request_id}")
                return True
        return False

    def get_last_result(self, max_age_seconds: int = 300) -> Optional[Dict[str, Any]]:
        """
        Get the last completed agent result if it's recent enough

        Args:
            max_age_seconds: Maximum age of result in seconds (default 5 minutes)

        Returns:
            Dict with result data or None if no recent result
        """
        if not self.last_result or not self.last_result_time:
            return None

        age = time.time() - self.last_result_time
        if age > max_age_seconds:
            return None

        return {
            "result": self.last_result,
            "query": self.last_query,
            "timestamp": self.last_result_time,
            "age_seconds": int(age)
        }

    def get_tool_info(self) -> Dict[str, Any]:
        """Get information about available tools"""
        return {
            "tool_count": len(self.tools),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description
                }
                for tool in self.tools
            ],
            "config": {
                "max_steps": self.max_steps,
                "llama_url": self.llama_cpp_url,
                "zendriver_url": self.zendriver_api_url
            }
        }