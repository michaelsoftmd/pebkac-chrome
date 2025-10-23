"""
Agent chat and management routes
"""

import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import logging

from app.services.agent_manager import AgentManager
from app.api.dependencies import get_agent_manager, get_database_manager
from app.core.database import DatabaseManager

logger = logging.getLogger(__name__)

router = APIRouter()


# ===========================
# Request/Response Models
# ===========================

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = []

class ChatResponse(BaseModel):
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None


# ===========================
# Chat API for SmolAgents Integration
# ===========================

@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Chat endpoint with streaming agent execution

    Request body:
    {
        "message": "user message",
        "history": [{"role": "user", "content": "..."}, ...]
    }
    """

    if not request.message:
        raise HTTPException(status_code=400, detail="No message provided")

    async def event_generator():
        """Generate Server-Sent Events"""
        try:
            agent_manager = get_agent_manager()

            async for event in agent_manager.run_agent_streaming(
                request.message,
                request.history
            ):
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            logger.error(f"Chat streaming error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'data': ''})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@router.get("/api/agent/info")
async def agent_info():
    """Get information about the agent and available tools"""
    try:
        agent_manager = get_agent_manager()
        return agent_manager.get_tool_info()
    except Exception as e:
        logger.error(f"Failed to get agent info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/agent/last-result")
async def get_last_result():
    """
    Get the last completed agent result if available

    Useful for reconnecting after page refresh or disconnect
    Returns result only if it's less than 5 minutes old
    """
    try:
        agent_manager = get_agent_manager()
        result = agent_manager.get_last_result(max_age_seconds=300)

        if result:
            return {
                "status": "success",
                "has_result": True,
                **result
            }
        else:
            return {
                "status": "success",
                "has_result": False
            }
    except Exception as e:
        logger.error(f"Failed to get last result: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/agent/history")
async def get_execution_history(limit: int = 20, workflow_id: Optional[str] = None):
    """
    Get execution history from research sessions

    Query params:
    - limit: Number of recent executions to return (default: 20, max: 100)
    - workflow_id: Optional specific workflow ID to retrieve

    Returns:
    - List of execution records with query, result, step count, and timestamps
    """
    try:
        db_manager = get_database_manager()

        # Limit maximum to prevent large responses
        limit = min(limit, 100)

        sessions = db_manager.get_research_sessions(
            workflow_id=workflow_id,
            limit=limit
        )

        return {
            "status": "success",
            "count": len(sessions),
            "sessions": sessions
        }
    except Exception as e:
        logger.error(f"Failed to get execution history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
