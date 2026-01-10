"""Background task runner for AI Agent tasks.

This module handles asynchronous execution of agent tasks,
allowing users to close the browser and check results later.
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable

from backend.database.database import SessionLocal
from backend.database.models import AgentTask, AgentMessage as AgentMessageDB, AgentSession as AgentSessionDB
from backend.agent.engine import AgentEngine, AgentSession, AgentMessage, MessageRole

logger = logging.getLogger(__name__)

# Global executor for background tasks
_executor: Optional[ThreadPoolExecutor] = None
_running_tasks: Dict[int, threading.Event] = {}  # task_id -> cancel_event

# Thread-safe event log storage for real-time streaming
_event_logs: Dict[int, List[Dict[str, Any]]] = {}  # task_id -> list of events
_event_locks: Dict[int, threading.Lock] = {}  # task_id -> lock for thread-safe access


def _get_event_lock(task_id: int) -> threading.Lock:
    """Get or create a lock for the task's event log."""
    if task_id not in _event_locks:
        _event_locks[task_id] = threading.Lock()
    return _event_locks[task_id]


def add_event(task_id: int, event_type: str, message: str, data: Optional[Dict] = None) -> None:
    """Add an event to the task's execution log (thread-safe).

    Args:
        task_id: ID of the task
        event_type: Type of event (e.g., 'status', 'tool_start', 'tool_end', 'llm_response', 'error')
        message: Human-readable message
        data: Optional additional data
    """
    lock = _get_event_lock(task_id)
    with lock:
        if task_id not in _event_logs:
            _event_logs[task_id] = []

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": event_type,
            "message": message,
            "data": data or {}
        }
        _event_logs[task_id].append(event)

        # Also persist to database periodically
        if len(_event_logs[task_id]) % 5 == 0:  # Every 5 events
            _persist_events(task_id)


def get_events(task_id: int, since_index: int = 0) -> List[Dict[str, Any]]:
    """Get events for a task starting from a specific index.

    Args:
        task_id: ID of the task
        since_index: Index to start from (for incremental fetching)

    Returns:
        List of events from since_index onwards
    """
    lock = _get_event_lock(task_id)
    with lock:
        if task_id not in _event_logs:
            # Try to load from database
            _event_logs[task_id] = _load_events_from_db(task_id)
        return _event_logs[task_id][since_index:]


def _load_events_from_db(task_id: int) -> List[Dict[str, Any]]:
    """Load events from database for a task."""
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if task and task.execution_log:
            try:
                return json.loads(task.execution_log)
            except json.JSONDecodeError:
                return []
        return []
    finally:
        db.close()


def _persist_events(task_id: int) -> None:
    """Persist current events to database."""
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if task:
            events = _event_logs.get(task_id, [])
            task.execution_log = json.dumps(events, ensure_ascii=False)
            db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist events for task {task_id}: {e}")
    finally:
        db.close()


def clear_events(task_id: int) -> None:
    """Clear events for a completed task."""
    lock = _get_event_lock(task_id)
    with lock:
        if task_id in _event_logs:
            del _event_logs[task_id]
    if task_id in _event_locks:
        del _event_locks[task_id]


def get_executor() -> ThreadPoolExecutor:
    """Get or create the global executor."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="agent_task_")
    return _executor


def start_background_task(
    task_id: int,
    session_id: str,
    user_message: str,
    model_name: str = None,
    temperature: float = 0.7,
    max_iterations: int = None
) -> None:
    """Start a background task for agent execution.

    Args:
        task_id: Database ID of the AgentTask
        session_id: Session ID for the agent
        user_message: User's message to process
        model_name: LLM model to use
        temperature: LLM temperature
        max_iterations: Maximum iterations (None uses system default)
    """
    executor = get_executor()
    cancel_event = threading.Event()
    _running_tasks[task_id] = cancel_event

    executor.submit(
        _run_task,
        task_id,
        session_id,
        user_message,
        model_name,
        temperature,
        cancel_event,
        max_iterations
    )


def _load_conversation_history(db, session: AgentSession) -> None:
    """Load conversation history from database into the session.

    This enables multi-turn conversations where the agent needs context
    from previous messages (e.g., confirming with "yes" after a question).

    Args:
        db: Database session
        session: AgentSession to load messages into
    """
    try:
        # Query past messages for this session
        past_messages = db.query(AgentMessageDB).filter(
            AgentMessageDB.session_id == session.id
        ).order_by(AgentMessageDB.created_at).all()

        if not past_messages:
            logger.info(f"No conversation history found for session {session.id}")
            return

        logger.info(f"Loading {len(past_messages)} messages from history for session {session.id}")

        # Add messages to session (skip system message as it's already added)
        for msg in past_messages:
            role_str = msg.role.lower()

            # Skip system messages (already in session)
            if role_str == "system":
                continue

            # Parse role
            if role_str == "user":
                role = MessageRole.USER
            elif role_str == "assistant":
                role = MessageRole.ASSISTANT
            elif role_str == "tool":
                role = MessageRole.TOOL
            else:
                logger.warning(f"Unknown role: {role_str}, skipping message")
                continue

            # Create AgentMessage
            agent_msg = AgentMessage(
                role=role,
                content=msg.content,
                tool_call_id=msg.tool_call_id
            )

            # Parse tool_calls if present
            if msg.tool_calls:
                try:
                    from backend.agent.engine import ToolCall
                    tool_calls_data = json.loads(msg.tool_calls)
                    for tc_data in tool_calls_data:
                        agent_msg.tool_calls.append(ToolCall(
                            id=tc_data.get("id", ""),
                            name=tc_data.get("name", ""),
                            arguments=tc_data.get("arguments", {}),
                            result=tc_data.get("result")
                        ))
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool_calls for message {msg.id}")

            session.add_message(agent_msg)

    except Exception as e:
        logger.error(f"Error loading conversation history: {e}", exc_info=True)


def _run_task(
    task_id: int,
    session_id: str,
    user_message: str,
    model_name: str,
    temperature: float,
    cancel_event: threading.Event,
    max_iterations: int = None
) -> None:
    """Execute the agent task in background.

    This runs in a separate thread.

    Args:
        task_id: Database ID of the AgentTask
        session_id: Session ID for the agent
        user_message: User's message to process
        model_name: LLM model to use
        temperature: LLM temperature
        cancel_event: Event to check for cancellation
        max_iterations: Maximum iterations (None uses system default)
    """
    db = SessionLocal()
    try:
        # Initialize event log
        add_event(task_id, "status", "タスクを開始しています...", {"model": model_name})

        # Update task status to running
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if not task:
            logger.error(f"Task {task_id} not found")
            add_event(task_id, "error", "タスクが見つかりません")
            return

        task.status = "running"
        task.started_at = datetime.utcnow().isoformat()
        db.commit()

        logger.info(f"Starting agent task {task_id} with model {model_name}")
        add_event(task_id, "status", f"モデル {model_name} でエージェントを起動中...")

        # Check if session is already terminated
        db_session = db.query(AgentSessionDB).filter(AgentSessionDB.id == session_id).first()
        if db_session and db_session.terminated:
            logger.warning(f"Session {session_id} is terminated, rejecting new message")
            add_event(task_id, "error", "セッションが終了済みのため、新しいメッセージは処理できません")
            task.status = "completed"
            task.assistant_response = "このセッションはセキュリティ上の理由により終了しています。新しいセッションを開始してください。"
            task.finished_at = datetime.utcnow().isoformat()
            db.commit()
            _persist_events(task_id)
            return

        # Check for cancellation
        if cancel_event.is_set():
            add_event(task_id, "status", "タスクがキャンセルされました")
            task.status = "cancelled"
            task.finished_at = datetime.utcnow().isoformat()
            db.commit()
            _persist_events(task_id)
            return

        # Create agent engine and session with event callback
        add_event(task_id, "status", "エージェントセッションを作成中...")
        engine = AgentEngine(model_name=model_name, temperature=temperature)

        # Set up event callback for the engine
        def event_callback(event_type: str, message: str, data: Optional[Dict] = None):
            add_event(task_id, event_type, message, data)

        engine.event_callback = event_callback  # Attach callback

        session = engine.create_session(session_id=session_id, model_name=model_name, temperature=temperature, max_iterations=max_iterations)

        # Load conversation history from database
        # This is critical for multi-turn conversations (e.g., "yes" confirmations)
        add_event(task_id, "status", "会話履歴を読み込み中...")
        _load_conversation_history(db, session)

        # Run agent synchronously (we're already in a thread)
        add_event(task_id, "thinking", "ユーザーメッセージを処理中...", {"message": user_message[:100]})
        response = engine.run_sync(session, user_message)

        # Check if session was terminated by security guardrail
        if session.terminated:
            logger.warning(f"Session {session_id} was terminated by security guardrail")
            add_event(task_id, "security", "セキュリティガードレールによりセッションが終了しました")
            # Persist terminated state to database
            if db_session:
                db_session.terminated = 1
                db.commit()
            else:
                # Create session record with terminated flag
                db_session = AgentSessionDB(
                    id=session_id,
                    title="[終了] " + user_message[:40] + "...",
                    terminated=1,
                    created_at=datetime.utcnow().isoformat() + 'Z',
                    updated_at=datetime.utcnow().isoformat() + 'Z'
                )
                db.add(db_session)
                db.commit()

        # Check for cancellation again
        if cancel_event.is_set():
            add_event(task_id, "status", "タスクがキャンセルされました")
            task.status = "cancelled"
            task.finished_at = datetime.utcnow().isoformat()
            db.commit()
            _persist_events(task_id)
            return

        # Collect tool calls log
        tool_calls_log = []
        for msg in session.messages:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls_log.append({
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "result": tc.result
                    })

        # Add completion event
        add_event(task_id, "complete", "処理が完了しました", {
            "tool_count": len(tool_calls_log),
            "response_length": len(response) if response else 0
        })

        # Update task with results
        task.status = "completed"
        task.assistant_response = response
        task.tool_calls_log = json.dumps(tool_calls_log, ensure_ascii=False)
        task.finished_at = datetime.utcnow().isoformat()

        # Persist all events to database
        _persist_events(task_id)

        db.commit()

        logger.info(f"Agent task {task_id} completed successfully")

    except Exception as e:
        logger.error(f"Agent task {task_id} failed: {e}", exc_info=True)
        add_event(task_id, "error", f"エラーが発生しました: {str(e)}")
        try:
            task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
            if task:
                task.status = "error"
                task.error_message = str(e)
                task.finished_at = datetime.utcnow().isoformat()
                _persist_events(task_id)
                db.commit()
        except Exception as db_error:
            logger.error(f"Failed to update task status: {db_error}")
    finally:
        db.close()
        # Clean up running tasks
        if task_id in _running_tasks:
            del _running_tasks[task_id]


def cancel_task(task_id: int) -> bool:
    """Cancel a running task.

    Args:
        task_id: ID of the task to cancel

    Returns:
        True if cancel signal was sent, False if task not running
    """
    if task_id in _running_tasks:
        _running_tasks[task_id].set()
        return True
    return False


def get_task_status(task_id: int) -> Optional[Dict]:
    """Get the status of a task from the database.

    Args:
        task_id: ID of the task

    Returns:
        Task status dict or None if not found
    """
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if not task:
            return None

        # Check if session is terminated
        session_terminated = False
        db_session = db.query(AgentSessionDB).filter(AgentSessionDB.id == task.session_id).first()
        if db_session and db_session.terminated:
            session_terminated = True

        result = {
            "id": task.id,
            "session_id": task.session_id,
            "status": task.status,
            "model_name": task.model_name,
            "user_message": task.user_message,
            "assistant_response": task.assistant_response,
            "error_message": task.error_message,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "session_terminated": session_terminated
        }

        # Parse tool calls log if present
        if task.tool_calls_log:
            try:
                result["tool_calls"] = json.loads(task.tool_calls_log)
            except json.JSONDecodeError:
                result["tool_calls"] = []
        else:
            result["tool_calls"] = []

        return result
    finally:
        db.close()


def get_session_tasks(session_id: str, limit: int = 20) -> list:
    """Get all tasks for a session.

    Args:
        session_id: Session ID to filter by
        limit: Maximum number of tasks to return

    Returns:
        List of task status dicts
    """
    db = SessionLocal()
    try:
        tasks = db.query(AgentTask).filter(
            AgentTask.session_id == session_id
        ).order_by(AgentTask.created_at.desc()).limit(limit).all()

        return [
            {
                "id": t.id,
                "session_id": t.session_id,
                "status": t.status,
                "model_name": t.model_name,
                "user_message": t.user_message[:100] + "..." if t.user_message and len(t.user_message) > 100 else t.user_message,
                "created_at": t.created_at,
                "started_at": t.started_at,
                "finished_at": t.finished_at
            }
            for t in tasks
        ]
    finally:
        db.close()


def get_recent_tasks(limit: int = 20) -> list:
    """Get recent tasks across all sessions.

    Args:
        limit: Maximum number of tasks to return

    Returns:
        List of task status dicts
    """
    db = SessionLocal()
    try:
        tasks = db.query(AgentTask).order_by(
            AgentTask.created_at.desc()
        ).limit(limit).all()

        return [
            {
                "id": t.id,
                "session_id": t.session_id,
                "status": t.status,
                "model_name": t.model_name,
                "user_message": t.user_message[:100] + "..." if t.user_message and len(t.user_message) > 100 else t.user_message,
                "assistant_response": t.assistant_response[:200] + "..." if t.assistant_response and len(t.assistant_response) > 200 else t.assistant_response,
                "created_at": t.created_at,
                "started_at": t.started_at,
                "finished_at": t.finished_at
            }
            for t in tasks
        ]
    finally:
        db.close()


def create_task(
    session_id: str,
    user_message: str,
    model_name: str = None
) -> AgentTask:
    """Create a new task in the database.

    Args:
        session_id: Session ID
        user_message: User's message
        model_name: LLM model to use

    Returns:
        Created AgentTask instance
    """
    db = SessionLocal()
    try:
        task = AgentTask(
            session_id=session_id,
            status="pending",
            model_name=model_name,
            user_message=user_message,
            created_at=datetime.utcnow().isoformat()
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
    finally:
        db.close()
