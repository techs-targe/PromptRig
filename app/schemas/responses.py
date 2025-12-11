"""Response schemas for API endpoints.

Based on specification in docs/req.txt section 3.2, 4.2
"""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class ParameterDefinitionResponse(BaseModel):
    """Parameter definition extracted from prompt template."""
    name: str
    type: str  # TEXTn, NUM, DATE, DATETIME, FILE, FILEPATH
    html_type: str  # textarea, number, date, datetime-local, file, text
    rows: int = 0
    accept: Optional[str] = None  # For file input (e.g., "image/*")
    placeholder: Optional[str] = None  # For text inputs
    required: bool = True  # True if parameter is required (no | pipe)
    default: Optional[str] = None  # Default value if optional (from |default=...)


class JobItemResponse(BaseModel):
    """Job item response data."""
    id: int
    created_at: str
    input_params: str  # JSON string
    raw_prompt: str
    raw_response: Optional[str]
    parsed_response: Optional[str]
    status: str
    error_message: Optional[str]
    turnaround_ms: Optional[int]


class JobResponse(BaseModel):
    """Job response data."""
    id: int
    job_type: str
    status: str
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    turnaround_ms: Optional[int]
    merged_csv_output: Optional[str] = None  # Merged CSV for batch jobs
    model_name: Optional[str] = None  # LLM model used for execution
    prompt_name: Optional[str] = None  # Prompt name used for execution (NEW)
    items: List[JobItemResponse] = []


class ConfigResponse(BaseModel):
    """Response for GET /api/config.

    Specification: docs/req.txt section 3.2 (通信フロー step 2)
    """
    project_id: int
    project_name: str
    project_revision_id: int
    revision: int
    prompt_template: str
    parameters: List[ParameterDefinitionResponse]
    recent_jobs: List[JobResponse]
    available_models: List[str] = ["azure-gpt-4.1", "openai-gpt-4.1-nano"]


class RunSingleResponse(BaseModel):
    """Response for POST /api/run/single.

    Specification: docs/req.txt section 3.2 (通信フロー step 6)
    """
    success: bool
    job_id: int
    job: JobResponse
    message: str = ""
