"""Request schemas for API endpoints.

Based on specification in docs/req.txt section 3.2, 3.3, 4.2
NEW ARCHITECTURE (v3.0): Supports prompt_id for new architecture.
"""

from typing import Dict, Optional
from pydantic import BaseModel, Field


class RunSingleRequest(BaseModel):
    """Request body for POST /api/run/single.

    Specification: docs/req.txt section 3.2 (通信フロー)
    NEW ARCHITECTURE: If prompt_id is provided, uses PromptRevision.
                      Otherwise falls back to ProjectRevision for backward compatibility.
    """
    project_id: int = Field(
        default=1,
        description="Project ID to use (defaults to 1 for backward compatibility)"
    )
    prompt_id: Optional[int] = Field(
        default=None,
        description="Prompt ID to use (NEW ARCHITECTURE). If provided, uses PromptRevision instead of ProjectRevision."
    )
    prompt_revision_id: Optional[int] = Field(
        default=None,
        description="Specific prompt revision ID to use. If provided, validates and uses this exact revision."
    )
    input_params: Dict[str, str] = Field(
        ...,
        description="Dictionary of parameter name to value"
    )
    repeat: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Number of times to repeat execution (1-10)"
    )
    model_name: str = Field(
        default=None,
        description="LLM model to use (defaults to ACTIVE_LLM_MODEL)"
    )
    include_csv_header: bool = Field(
        default=True,
        description="Include CSV header only in first row (for repeat > 1)"
    )
    temperature: float = Field(
        default=0.7,
        ge=0,
        le=2,
        description="Temperature for LLM (0-2)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "input_params": {
                    "question": "What is the capital of France?",
                    "context": "France is a country in Europe."
                },
                "repeat": 3,
                "model_name": "azure-gpt-4.1",
                "prompt_id": 1
            }
        }


class RunBatchAllRequest(BaseModel):
    """Request body for POST /api/run/batch-all.

    Executes batch for ALL prompts in a project.
    All jobs are created upfront on the server so execution continues
    even if the browser is closed.
    """
    project_id: int = Field(
        ...,
        description="Project ID containing multiple prompts"
    )
    dataset_id: int = Field(
        ...,
        description="Dataset ID to use for batch execution"
    )
    model_name: str = Field(
        default=None,
        description="LLM model to use"
    )
    include_csv_header: bool = Field(
        default=True,
        description="Include CSV header in output"
    )
    temperature: float = Field(
        default=0.7,
        ge=0,
        le=2,
        description="Temperature for LLM (0-2)"
    )
    force: bool = Field(
        default=False,
        description="Force execution even if there are already running jobs"
    )
