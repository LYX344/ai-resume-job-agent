import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.models.chat import ChatMessage
from app.models.config import ModelRuntimeConfig

ChatPayloadMessage = ChatMessage | dict[str, Any]


class LLMClientError(Exception):
    """Base error for LLM client failures."""


class LLMConfigurationError(LLMClientError):
    """Raised when required LLM configuration is missing."""


class LLMProviderError(LLMClientError):
    """Raised when the upstream LLM provider returns an error."""


@dataclass(frozen=True)
class LLMChatResult:
    content: str
    model: str
    finish_reason: str | None
    usage: dict[str, Any] | None
    tool_calls: list["LLMToolCall"] = field(default_factory=list)


@dataclass(frozen=True)
class LLMToolFunctionCall:
    name: str
    arguments: str


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    type: str
    function: LLMToolFunctionCall


@dataclass(frozen=True)
class LLMStreamDelta:
    type: str
    text: str


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 1,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    @classmethod
    def from_settings(cls) -> "OpenAICompatibleClient":
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        *,
        messages: list[ChatPayloadMessage],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMChatResult:
        payload = self._build_payload(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            tools=tools,
            tool_choice=tool_choice,
        )
        data = await self._post_json(payload)
        return self._parse_chat_response(data)

    async def stream_chat(
        self,
        *,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator["LLMStreamDelta"]:
        payload = self._build_payload(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async with self._client.stream(
            "POST",
            self._chat_completions_url,
            headers=self._headers,
            json=payload,
        ) as response:
            await self._raise_for_status(response)
            async for line in response.aiter_lines():
                chunk = self._parse_stream_line(line)
                if chunk:
                    yield chunk

    @property
    def _chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    @property
    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        *,
        messages: list[ChatPayloadMessage],
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [_dump_message(message) for message in messages],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream"] = True
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

    async def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        attempts = max(0, self.max_retries) + 1
        for attempt in range(attempts):
            try:
                response = await self._client.post(
                    self._chat_completions_url,
                    headers=self._headers,
                    json=payload,
                )
                if response.status_code >= 500 and attempt < attempts - 1:
                    continue
                await self._raise_for_status(response)
                return response.json()
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break
        raise LLMProviderError(f"LLM provider request failed: {last_error}") from last_error

    async def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        message = response.text
        try:
            data = response.json()
            message = data.get("error", {}).get("message", message)
        except ValueError:
            pass
        raise LLMProviderError(
            f"LLM provider returned HTTP {response.status_code}: {message}"
        )

    def _parse_chat_response(self, data: dict[str, Any]) -> LLMChatResult:
        try:
            choice = data["choices"][0]
            message = choice["message"]
            # Reasoning models (e.g. deepseek) can return an empty content with
            # the text in reasoning_content; fall back so callers still get text.
            content = message.get("content") or message.get("reasoning_content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("LLM provider returned an invalid chat response.") from exc
        return LLMChatResult(
            content=content,
            model=data.get("model", self.model),
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            tool_calls=self._parse_tool_calls(message.get("tool_calls")),
        )

    def _parse_tool_calls(self, raw_tool_calls: Any) -> list[LLMToolCall]:
        if raw_tool_calls is None:
            return []
        if not isinstance(raw_tool_calls, list):
            raise LLMProviderError("LLM provider returned invalid tool calls.")

        tool_calls: list[LLMToolCall] = []
        for raw_tool_call in raw_tool_calls:
            if not isinstance(raw_tool_call, dict):
                raise LLMProviderError("LLM provider returned invalid tool calls.")
            function = raw_tool_call.get("function")
            if not isinstance(function, dict):
                raise LLMProviderError("LLM provider returned invalid tool calls.")
            tool_call_id = raw_tool_call.get("id")
            tool_call_type = raw_tool_call.get("type")
            function_name = function.get("name")
            function_arguments = function.get("arguments")
            if not all(
                isinstance(value, str)
                for value in (
                    tool_call_id,
                    tool_call_type,
                    function_name,
                    function_arguments,
                )
            ):
                raise LLMProviderError("LLM provider returned invalid tool calls.")
            tool_calls.append(
                LLMToolCall(
                    id=tool_call_id,
                    type=tool_call_type,
                    function=LLMToolFunctionCall(
                        name=function_name,
                        arguments=function_arguments,
                    ),
                )
            )
        return tool_calls

    def _parse_stream_line(self, line: str) -> "LLMStreamDelta | None":
        if not line.startswith("data:"):
            return None
        raw_data = line.removeprefix("data:").strip()
        if raw_data == "[DONE]":
            return None
        try:
            data = json.loads(raw_data)
            choice = data["choices"][0]
            delta = choice.get("delta", {})
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("LLM provider returned an invalid stream chunk.") from exc
        content = delta.get("content")
        if content:
            return LLMStreamDelta(type="content", text=content)
        reasoning = delta.get("reasoning_content")
        if reasoning:
            return LLMStreamDelta(type="reasoning", text=reasoning)
        finish_reason = choice.get("finish_reason")
        if finish_reason:
            return LLMStreamDelta(type="finish", text=str(finish_reason))
        return None


def _dump_message(message: ChatPayloadMessage) -> dict[str, Any]:
    if isinstance(message, ChatMessage):
        return message.model_dump()
    return message


def build_llm_client(config: ModelRuntimeConfig | None = None) -> OpenAICompatibleClient:
    """按运行时配置构建 LLM client；缺省字段回退 `.env` 默认。"""
    config = config or ModelRuntimeConfig()
    return OpenAICompatibleClient(
        base_url=config.base_url or settings.llm_base_url,
        api_key=config.api_key or settings.llm_api_key,
        model=config.model or settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
