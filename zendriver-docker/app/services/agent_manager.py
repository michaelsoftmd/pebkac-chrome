"""
Agent manager for SmolAgents integration with basic streaming support
"""

import os
import logging
import asyncio
import json
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
    GarboPageMarkdownTool,
    WebSearchTool,
    SearchHistoryTool,
    VisitWebpageTool,
    CloudflareBypassTool,
    ScreenshotTool,
    GetElementPositionTool,
    InterceptNetworkTool
)

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages SmolAgents CodeAgent instances with llama.cpp integration"""

    def __init__(self, llama_cpp_url: str = None):
        self.llama_cpp_url = llama_cpp_url or os.getenv("ACTIVE_OPENAI_URL", "http://llama-cpp-server:8080/v1")
        # Tools call localhost since AgentManager runs inside zendriver container
        self.zendriver_api_url = os.getenv("ZENDRIVER_API_URL", "http://localhost:8080")
        self.duckdb_url = os.getenv("DUCKDB_URL", "http://duckdb-cache:9001")
        self.max_steps = int(os.getenv("SMOLAGENTS_MAX_STEPS", "10"))

        # Track active tasks for cancellation
        self.active_tasks: Dict[str, asyncio.Task] = {}

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
            GarboPageMarkdownTool(self.zendriver_api_url),

            # Search and navigation
            WebSearchTool(self.zendriver_api_url),
            SearchHistoryTool(self.duckdb_url),
            VisitWebpageTool(self.zendriver_api_url),

            # Security
            CloudflareBypassTool(self.zendriver_api_url),

            # Utilities
            ScreenshotTool(self.zendriver_api_url),
            GetElementPositionTool(self.zendriver_api_url),
            InterceptNetworkTool(self.zendriver_api_url)
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
                use_structured_outputs_internally=False
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

            # Extract result from agent response
            if isinstance(result, str):
                formatted_result = result
            elif hasattr(result, 'final_answer') and result.final_answer:
                formatted_result = result.final_answer
            elif hasattr(result, 'logs') and result.logs:
                formatted_result = result.logs[-1] if result.logs else "Task completed"
            else:
                formatted_result = str(result).replace('\\n', '\n').replace('\\t', '\t')

            # Format dicts/lists as readable JSON
            if isinstance(formatted_result, (dict, list)):
                formatted_result = json.dumps(formatted_result, indent=2, ensure_ascii=False)
            elif not isinstance(formatted_result, str):
                formatted_result = str(formatted_result)

            chunk_size = 100
            for i in range(0, len(formatted_result), chunk_size):
                chunk = formatted_result[i:i+chunk_size]
                yield {"type": "content", "data": chunk}
                await asyncio.sleep(0.02)

            yield {"type": "done", "data": ""}
            logger.info("Agent completed successfully")

        except asyncio.CancelledError:
            logger.info(f"Agent streaming cancelled for request: {request_id}")
            if task and not task.done():
                task.cancel()
            yield {"type": "error", "data": "Request cancelled"}

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