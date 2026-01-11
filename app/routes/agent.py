"""API endpoints for AI Agent functionality."""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.agent.engine import AgentEngine, AgentSession, MessageRole
from backend.agent.task_runner import (
    create_task,
    start_background_task,
    get_task_status,
    get_recent_tasks,
    get_session_tasks,
    cancel_task,
    get_events
)
from backend.mcp.tools import get_tool_registry
from backend.agent.policy import get_policy_layer, OutputFilter
from backend.database.database import SessionLocal
from backend.database.models import AgentSession as AgentSessionDB, AgentMessage as AgentMessageDB, AgentTask as AgentTaskDB, SystemSetting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Store active sessions (in production, use a proper session store)
_agent_engine: Optional[AgentEngine] = None
_sessions: Dict[str, AgentSession] = {}


def get_engine() -> AgentEngine:
    """Get or create the agent engine."""
    global _agent_engine
    if _agent_engine is None:
        _agent_engine = AgentEngine()
    return _agent_engine


def get_agent_stream_timeout() -> int:
    """Get the agent stream timeout from system settings.

    Returns:
        Timeout in seconds (default 300, range 60-1800)
    """
    DEFAULT_TIMEOUT = 300  # 5 minutes
    db = SessionLocal()
    try:
        setting = db.query(SystemSetting).filter(
            SystemSetting.key == "agent_stream_timeout"
        ).first()
        if setting and setting.value:
            try:
                timeout = int(setting.value)
                return max(60, min(timeout, 1800))
            except ValueError:
                return DEFAULT_TIMEOUT
        return DEFAULT_TIMEOUT
    finally:
        db.close()


# ============== Request/Response Models ==============

class CreateSessionRequest(BaseModel):
    """Request to create a new agent session."""
    model_name: Optional[str] = Field(None, description="LLM model to use")
    temperature: Optional[float] = Field(0.7, description="Temperature for LLM (0.0-2.0)")


class CreateSessionResponse(BaseModel):
    """Response with session information."""
    session_id: str
    model_name: str
    temperature: float
    status: str


class ChatRequest(BaseModel):
    """Request to send a message to the agent."""
    message: str = Field(..., description="User message")
    session_id: Optional[str] = Field(None, description="Existing session ID (creates new if not provided)")
    model_name: Optional[str] = Field(None, description="LLM model override")
    temperature: Optional[float] = Field(None, description="Temperature override")


class ToolCallInfo(BaseModel):
    """Information about a tool call."""
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None


class MessageInfo(BaseModel):
    """Information about a message in the conversation."""
    role: str
    content: str
    tool_calls: List[ToolCallInfo] = []
    timestamp: str


class ChatResponse(BaseModel):
    """Response from agent chat."""
    session_id: str
    response: str
    status: str
    iteration_count: int
    messages: List[MessageInfo] = []


class ToolInfo(BaseModel):
    """Information about an available tool."""
    name: str
    description: str
    parameters: List[Dict[str, Any]]


class ToolListResponse(BaseModel):
    """Response listing available tools."""
    tools: List[ToolInfo]
    count: int


class ExecuteToolRequest(BaseModel):
    """Request to execute a tool directly."""
    tool_name: str = Field(..., description="Name of the tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class ExecuteToolResponse(BaseModel):
    """Response from tool execution."""
    success: bool
    result: Optional[Any] = None  # Can be Dict, List, or any JSON-serializable value
    error: Optional[str] = None


# ============== Background Task Models ==============

class StartTaskRequest(BaseModel):
    """Request to start a background agent task."""
    message: str = Field(..., description="User message for the agent")
    session_id: Optional[str] = Field(None, description="Session ID (auto-generated if not provided)")
    model_name: Optional[str] = Field(None, description="LLM model to use")
    temperature: Optional[float] = Field(0.7, description="Temperature for LLM (0.0-2.0)")
    max_iterations: Optional[int] = Field(None, description="Maximum iterations (10-99, default from system settings)")


class TaskStatusResponse(BaseModel):
    """Response with task status information."""
    id: int
    session_id: str
    status: str  # pending, running, completed, error, cancelled
    model_name: Optional[str] = None
    user_message: str
    assistant_response: Optional[str] = None
    error_message: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = []
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    session_terminated: bool = False  # True if session was terminated by security guardrail


class TaskListResponse(BaseModel):
    """Response with list of tasks."""
    tasks: List[Dict[str, Any]]
    count: int


# ============== API Endpoints ==============

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """Create a new agent session.

    Creates a new conversation session with the AI agent.
    Returns a session_id that can be used for subsequent chat requests.
    """
    engine = get_engine()
    session = engine.create_session(
        model_name=request.model_name,
        temperature=request.temperature
    )
    _sessions[session.id] = session

    return CreateSessionResponse(
        session_id=session.id,
        model_name=session.model_name,
        temperature=session.temperature,
        status=session.status
    )


@router.get("/sessions/{session_id}", response_model=CreateSessionResponse)
async def get_session(session_id: str):
    """Get information about an existing session."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return CreateSessionResponse(
        session_id=session.id,
        model_name=session.model_name,
        temperature=session.temperature,
        status=session.status
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete an agent session."""
    if session_id in _sessions:
        del _sessions[session_id]
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message to the agent and get a response.

    If session_id is provided, continues the existing conversation.
    Otherwise, creates a new session automatically.

    The agent will:
    1. Process your message
    2. Use tools as needed to gather information or perform actions
    3. Return a helpful response

    Example messages:
    - "プロジェクト一覧を表示して" (Show project list)
    - "プロンプトID 1の詳細を教えて" (Tell me details of prompt ID 1)
    - "テンプレート '{{TEXT}}を翻訳して' のパラメータを分析して" (Analyze template parameters)
    """
    engine = get_engine()

    # Get or create session
    if request.session_id and request.session_id in _sessions:
        session = _sessions[request.session_id]
    else:
        session = engine.create_session(
            model_name=request.model_name,
            temperature=request.temperature
        )
        _sessions[session.id] = session

    # Override model/temperature if provided
    if request.model_name:
        session.model_name = request.model_name
    if request.temperature is not None:
        session.temperature = request.temperature

    # Run agent
    try:
        response = await engine.run(session, request.message)
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    # Build message history for response
    messages = []
    for msg in session.messages:
        if msg.role == MessageRole.SYSTEM:
            continue  # Skip system messages in response

        tool_calls = []
        for tc in msg.tool_calls:
            tool_calls.append(ToolCallInfo(
                id=tc.id,
                name=tc.name,
                arguments=tc.arguments,
                result=tc.result
            ))

        messages.append(MessageInfo(
            role=msg.role.value,
            content=msg.content,
            tool_calls=tool_calls,
            timestamp=msg.timestamp.isoformat()
        ))

    return ChatResponse(
        session_id=session.id,
        response=response,
        status=session.status,
        iteration_count=session.current_iteration,
        messages=messages
    )


@router.get("/tools", response_model=ToolListResponse)
async def list_tools():
    """List all available MCP tools.

    Returns information about each tool including:
    - name: Tool identifier
    - description: What the tool does
    - parameters: Required and optional parameters
    """
    registry = get_tool_registry()
    tools = []

    for tool_def in registry.get_all_tools():
        params = []
        for param in tool_def.parameters:
            params.append({
                "name": param.name,
                "type": param.type,
                "description": param.description,
                "required": param.required,
                "default": param.default
            })

        tools.append(ToolInfo(
            name=tool_def.name,
            description=tool_def.description,
            parameters=params
        ))

    return ToolListResponse(tools=tools, count=len(tools))


@router.post("/tools/execute", response_model=ExecuteToolResponse)
async def execute_tool(request: ExecuteToolRequest):
    """Execute a tool directly without going through the agent.

    Useful for programmatic access to individual tools.

    Example:
    ```json
    {
        "tool_name": "list_projects",
        "arguments": {}
    }
    ```
    """
    registry = get_tool_registry()

    tool = registry.get_tool(request.tool_name)
    if not tool:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{request.tool_name}' not found"
        )

    result = await registry.execute_tool(request.tool_name, request.arguments)

    if result.get("success"):
        return ExecuteToolResponse(
            success=True,
            result=result.get("result")
        )
    else:
        return ExecuteToolResponse(
            success=False,
            error=result.get("error")
        )


@router.get("/tools/{tool_name}")
async def get_tool_info(tool_name: str):
    """Get detailed information about a specific tool."""
    registry = get_tool_registry()
    tool = registry.get_tool(tool_name)

    if not tool:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' not found"
        )

    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": [{
            "name": p.name,
            "type": p.type,
            "description": p.description,
            "required": p.required,
            "default": p.default,
            "enum": p.enum
        } for p in tool.parameters],
        "json_schema": tool.to_json_schema()
    }


# Quick action endpoints for common tasks
@router.post("/quick/analyze-template")
async def quick_analyze_template(template: str):
    """Quick action: Analyze a prompt template.

    Returns parameter definitions extracted from the template.
    """
    registry = get_tool_registry()
    result = await registry.execute_tool("analyze_template", {"template": template})

    if result.get("success"):
        return result.get("result")
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


@router.post("/quick/execute-template")
async def quick_execute_template(
    template: str,
    input_params: Dict[str, Any],
    model_name: Optional[str] = None,
    temperature: float = 0.7
):
    """Quick action: Execute a prompt template directly.

    Example:
    ```json
    {
        "template": "{{TEXT}}を日本語に翻訳して",
        "input_params": {"TEXT": "Hello, world!"},
        "model_name": "claude-3.5-sonnet",
        "temperature": 0.7
    }
    ```
    """
    registry = get_tool_registry()
    args = {
        "template": template,
        "input_params": input_params,
        "temperature": temperature
    }
    if model_name:
        args["model_name"] = model_name

    result = await registry.execute_tool("execute_template", args)

    if result.get("success"):
        return result.get("result")
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


# ============== Background Task Endpoints ==============

@router.post("/tasks", response_model=TaskStatusResponse)
async def start_task(request: StartTaskRequest):
    """Start a background agent task.

    The task will run in the background, allowing you to close the browser
    and check results later using GET /api/agent/tasks/{task_id}.

    Returns immediately with task_id that can be used to poll for results.
    """
    # Generate session ID if not provided
    session_id = request.session_id or f"agent_{int(time.time() * 1000)}"

    # Create task in database
    task = create_task(
        session_id=session_id,
        user_message=request.message,
        model_name=request.model_name
    )

    # Start background execution
    start_background_task(
        task_id=task.id,
        session_id=session_id,
        user_message=request.message,
        model_name=request.model_name,
        temperature=request.temperature or 0.7,
        max_iterations=request.max_iterations
    )

    logger.info(f"Started background task {task.id} for session {session_id}")

    return TaskStatusResponse(
        id=task.id,
        session_id=session_id,
        status="pending",
        model_name=request.model_name,
        user_message=request.message,
        created_at=task.created_at
    )


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(session_id: Optional[str] = None, limit: int = 20):
    """List recent agent tasks.

    Can optionally filter by session_id.
    Returns tasks ordered by creation time (newest first).
    """
    if session_id:
        tasks = get_session_tasks(session_id, limit)
    else:
        tasks = get_recent_tasks(limit)

    return TaskListResponse(tasks=tasks, count=len(tasks))


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: int):
    """Get the status and result of a background task.

    Poll this endpoint to check if a task is complete.

    Status values:
    - pending: Task is queued but not started
    - running: Task is currently executing
    - completed: Task finished successfully (assistant_response available)
    - error: Task failed (error_message available)
    - cancelled: Task was cancelled
    """
    task = get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return TaskStatusResponse(**task)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task_endpoint(task_id: int):
    """Cancel a running task.

    Only tasks in 'pending' or 'running' status can be cancelled.
    """
    task = get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task["status"] in ["completed", "error", "cancelled"]:
        return {
            "task_id": task_id,
            "cancelled": False,
            "message": f"Task is already {task['status']}"
        }

    success = cancel_task(task_id)
    return {
        "task_id": task_id,
        "cancelled": success,
        "message": "Cancel signal sent" if success else "Task not currently running"
    }


@router.get("/tasks/{task_id}/stream")
async def stream_task_events(task_id: int, since: int = 0):
    """Stream task execution events using Server-Sent Events (SSE).

    This endpoint provides real-time updates about task execution progress.
    Connect to this endpoint immediately after starting a task to receive
    live updates about tool executions, LLM responses, and status changes.

    Args:
        task_id: ID of the task to stream
        since: Event index to start from (for resuming streams)

    Returns:
        SSE stream with events in the format:
        data: {"type": "tool_start", "message": "...", "data": {...}}
    """

    # Get stream timeout from system settings (called outside generator for efficiency)
    max_wait_seconds = get_agent_stream_timeout()

    async def event_generator():
        """Generate SSE events for the task."""
        last_index = since
        start_time = time.time()

        while True:
            # Check if we've exceeded max stream time
            if time.time() - start_time > max_wait_seconds:
                yield f"data: {json.dumps({'type': 'timeout', 'message': 'ストリーム時間が上限に達しました'})}\n\n"
                break

            # Get task status
            task = get_task_status(task_id)
            if not task:
                yield f"data: {json.dumps({'type': 'error', 'message': 'タスクが見つかりません'})}\n\n"
                break

            # Get new events
            new_events = get_events(task_id, last_index)
            for event in new_events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                last_index += 1

            # Check if task is complete
            if task["status"] in ["completed", "error", "cancelled"]:
                # Send final status event
                final_event = {
                    "type": "task_complete",
                    "message": f"タスク{task['status']}",
                    "data": {
                        "status": task["status"],
                        "response": task.get("assistant_response", ""),
                        "error": task.get("error_message", "")
                    }
                }
                yield f"data: {json.dumps(final_event, ensure_ascii=False)}\n\n"
                break

            # Wait before checking again
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.get("/tasks/{task_id}/events")
async def get_task_events(task_id: int, since: int = 0):
    """Get task execution events (non-streaming, for polling fallback).

    Args:
        task_id: ID of the task
        since: Event index to start from

    Returns:
        List of events since the given index
    """
    task = get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    events = get_events(task_id, since)
    return {
        "task_id": task_id,
        "events": events,
        "next_index": since + len(events),
        "status": task["status"],
        "is_complete": task["status"] in ["completed", "error", "cancelled"]
    }


# ============== Session History Endpoints (SQLite) ==============

class SessionHistoryItem(BaseModel):
    """Session history item for list response."""
    id: str
    title: Optional[str] = None
    model_name: Optional[str] = None
    created_at: str
    updated_at: str
    message_count: int = 0
    task_status: Optional[str] = None  # pending, running, completed, error, cancelled
    task_id: Optional[int] = None  # Latest task ID for this session


class SessionHistoryListResponse(BaseModel):
    """Response with session history list."""
    sessions: List[SessionHistoryItem]
    count: int


class SessionMessageItem(BaseModel):
    """Message item in session history."""
    id: int
    role: str
    content: str
    created_at: str


class SessionDetailResponse(BaseModel):
    """Response with session detail including messages."""
    id: str
    title: Optional[str] = None
    model_name: Optional[str] = None
    created_at: str
    updated_at: str
    messages: List[SessionMessageItem]


class SaveMessageRequest(BaseModel):
    """Request to save a message to session history."""
    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")


@router.get("/history", response_model=SessionHistoryListResponse)
async def list_session_history(limit: int = 50):
    """List all agent session history from SQLite.

    Returns sessions ordered by updated_at (newest first).
    Includes task status information for each session.
    """
    db = SessionLocal()
    try:
        sessions = db.query(AgentSessionDB).order_by(
            AgentSessionDB.updated_at.desc()
        ).limit(limit).all()

        items = []
        for session in sessions:
            msg_count = db.query(AgentMessageDB).filter(
                AgentMessageDB.session_id == session.id
            ).count()

            # Get the latest task for this session
            latest_task = db.query(AgentTaskDB).filter(
                AgentTaskDB.session_id == session.id
            ).order_by(AgentTaskDB.created_at.desc()).first()

            task_status = latest_task.status if latest_task else None
            task_id = latest_task.id if latest_task else None
            # Prefer task's model_name over session's (more accurate)
            model_name = (latest_task.model_name if latest_task and latest_task.model_name
                         else session.model_name)

            items.append(SessionHistoryItem(
                id=session.id,
                title=session.title,
                model_name=model_name,
                created_at=session.created_at,
                updated_at=session.updated_at,
                message_count=msg_count,
                task_status=task_status,
                task_id=task_id
            ))

        return SessionHistoryListResponse(sessions=items, count=len(items))
    finally:
        db.close()


@router.get("/history/{session_id}", response_model=SessionDetailResponse)
async def get_session_history(session_id: str):
    """Get a specific session with all messages."""
    db = SessionLocal()
    try:
        session = db.query(AgentSessionDB).filter(
            AgentSessionDB.id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        messages = db.query(AgentMessageDB).filter(
            AgentMessageDB.session_id == session_id
        ).order_by(AgentMessageDB.created_at).all()

        return SessionDetailResponse(
            id=session.id,
            title=session.title,
            model_name=session.model_name,
            created_at=session.created_at,
            updated_at=session.updated_at,
            messages=[
                SessionMessageItem(
                    id=msg.id,
                    role=msg.role,
                    content=msg.content,
                    created_at=msg.created_at
                ) for msg in messages
            ]
        )
    finally:
        db.close()


@router.post("/history/{session_id}/messages")
async def save_session_message(session_id: str, request: SaveMessageRequest):
    """Save a message to session history.

    Creates the session if it doesn't exist.
    """
    db = SessionLocal()
    try:
        # Get or create session
        session = db.query(AgentSessionDB).filter(
            AgentSessionDB.id == session_id
        ).first()

        now = datetime.utcnow().isoformat() + 'Z'  # Append Z for UTC timezone

        if not session:
            # Create new session
            session = AgentSessionDB(
                id=session_id,
                title=request.content[:50] + "..." if len(request.content) > 50 else request.content,
                created_at=now,
                updated_at=now
            )
            db.add(session)
        else:
            # Update session timestamp
            session.updated_at = now

        # Add message
        message = AgentMessageDB(
            session_id=session_id,
            role=request.role,
            content=request.content,
            created_at=now
        )
        db.add(message)
        db.commit()

        return {"status": "saved", "session_id": session_id, "message_id": message.id}
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving message: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/history/{session_id}")
async def delete_session_history(session_id: str):
    """Delete a specific session and all its messages."""
    db = SessionLocal()
    try:
        session = db.query(AgentSessionDB).filter(
            AgentSessionDB.id == session_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        # Delete session (messages cascade deleted)
        db.delete(session)
        db.commit()

        return {"status": "deleted", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/history")
async def delete_all_session_history():
    """Delete all session history."""
    db = SessionLocal()
    try:
        count = db.query(AgentSessionDB).count()
        db.query(AgentMessageDB).delete()
        db.query(AgentSessionDB).delete()
        db.commit()

        return {"status": "deleted", "count": count}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting all sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
