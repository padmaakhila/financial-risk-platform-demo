
"""Pydantic request and response models for the read-only AP Copilot."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator


class ChatMessage(BaseModel):
    """One previous conversation message.

    Only user and assistant messages are accepted.
    System/developer messages cannot be supplied by the client.
    """

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=1500)

    @validator("content")
    def validate_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Conversation message cannot be empty.")
        return value


class ChatRequest(BaseModel):
    """Incoming Copilot question and bounded conversation history."""

    question: str = Field(..., max_length=5000)
    invoice_number: Optional[str] = Field(None, max_length=100)
    history: List[ChatMessage] = Field(default_factory=list)

    @validator("history")
    def validate_history(cls, value: List[ChatMessage]) -> List[ChatMessage]:
        if len(value) > 8:
            raise ValueError("At most 8 previous conversation messages are allowed.")
        return value


class ChatResponse(BaseModel):
    """Copilot response, with optional structured investigation data."""

    answer: str
    mode: str
    model_available: bool = False

    invoice: Optional[Dict[str, Any]] = None
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    extraction: List[Dict[str, Any]] = Field(default_factory=list)
    match_info: Optional[Dict[str, Any]] = None
    verify_steps: List[str] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    retrieved: Dict[str, int] = Field(default_factory=dict)

    request_id: str = ""
