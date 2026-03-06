"""Pydantic models for chat endpoints."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    message: str
    trades_executed: list[dict] = []
    watchlist_changes: list[dict] = []
    errors: list[str] = []
