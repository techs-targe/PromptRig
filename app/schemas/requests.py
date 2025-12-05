"""Request schemas for API endpoints.

Based on specification in docs/req.txt section 3.2, 3.3, 4.2
"""

from typing import Dict
from pydantic import BaseModel, Field


class RunSingleRequest(BaseModel):
    """Request body for POST /api/run/single.

    Specification: docs/req.txt section 3.2 (通信フロー)
    """
    project_id: int = Field(
        default=1,
        description="Project ID to use (defaults to 1 for backward compatibility)"
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
                "model_name": "azure-gpt-4.1"
            }
        }
