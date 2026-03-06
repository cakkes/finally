"""LLM service for AI chat with structured outputs."""

import json
import os

from pydantic import BaseModel

import litellm


class TradeAction(BaseModel):
    ticker: str
    side: str  # "buy" or "sell"
    quantity: float


class WatchlistChange(BaseModel):
    ticker: str
    action: str  # "add" or "remove"


class LLMResponse(BaseModel):
    message: str
    trades: list[TradeAction] = []
    watchlist_changes: list[WatchlistChange] = []


SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant for a simulated stock trading platform.
The user has virtual money and can buy/sell stocks at current market prices.

Current Portfolio:
{portfolio_context}

You can:
- Analyze portfolio composition, risk, P&L
- Execute trades by including them in your "trades" array
- Manage the watchlist via "watchlist_changes"
- Answer questions about stocks and trading strategy

Be concise, data-driven, and helpful. Always respond with valid JSON matching the required schema."""


MOCK_RESPONSE = LLMResponse(
    message="I'm FinAlly, your AI trading assistant. I can see your portfolio and help you analyze positions and execute trades. What would you like to do?",
    trades=[],
    watchlist_changes=[],
)


class LLMService:
    def __init__(self):
        self.mock_mode = os.getenv("LLM_MOCK", "false").lower() == "true"
        self.api_key = os.getenv("OPENROUTER_API_KEY")

    async def chat(
        self,
        user_message: str,
        portfolio_context: dict,
        history: list[dict],
    ) -> LLMResponse:
        if self.mock_mode:
            return MOCK_RESPONSE

        system_msg = SYSTEM_PROMPT.format(
            portfolio_context=json.dumps(portfolio_context, indent=2)
        )

        messages = [{"role": "system", "content": system_msg}]

        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": user_message})

        try:
            response = await litellm.acompletion(
                model="openrouter/openai/gpt-oss-120b",
                messages=messages,
                response_format=LLMResponse,
                api_key=self.api_key,
                api_base="https://openrouter.ai/api/v1",
                extra_headers={"X-Provider": "Cerebras"},
            )

            content = response.choices[0].message.content
            return LLMResponse.model_validate_json(content)

        except Exception as e:
            return LLMResponse(
                message=f"Sorry, I encountered an error: {e}",
                trades=[],
                watchlist_changes=[],
            )
