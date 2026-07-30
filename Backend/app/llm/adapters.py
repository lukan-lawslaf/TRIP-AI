"""Provider adapters: provider-agnostic types → vendor wire format.

One adapter per `Dialect`. Adding a vendor that speaks OpenAI's chat-completions
shape means adding a `ProviderSpec`, not a new adapter.

Structured output uses each provider's *native* JSON mode (§8) rather than a
"respond only in JSON" instruction. Not every model supports strict schemas, so
capability flags on the candidate pick the strongest mode it actually honours:

    json_schema  → strict, server-validated
    json_object  → valid JSON guaranteed, shape is not
    neither      → schema described in the prompt, parsed defensively

Downgrading is silent to the caller but logged, so a role quietly losing schema
enforcement after a failover is visible in the logs instead of surfacing as a
mysterious parse error.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.llm.roles import Dialect, ModelCandidate, ProviderSpec
from app.llm.types import (
    LLMResponse,
    Message,
    ProviderUnavailable,
    RateLimited,
    RequestInvalid,
    Role,
    ToolCall,
    ToolSpec,
)

logger = logging.getLogger(__name__)


def _messages_to_openai(
    messages: list[Message], candidate: ModelCandidate
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role is Role.TOOL:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.content,
                }
            )
            continue

        if m.role is Role.ASSISTANT and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
            continue

        if m.media:
            if not candidate.supports_vision:
                # Text-only fallback candidate. Tell the model what it's missing
                # rather than letting it answer as if nothing was attached.
                logger.warning(
                    "adapter.media_dropped candidate=%s parts=%d",
                    candidate.key,
                    len(m.media),
                )
                kinds = ", ".join(sorted({p.mime_type for p in m.media}))
                note = (
                    f"\n\n[The user attached {len(m.media)} file(s) ({kinds}) that "
                    "this model cannot view. Ask them to describe the content.]"
                )
                out.append({"role": "user", "content": (m.content or "") + note})
                continue

            parts: list[dict[str, Any]] = []
            if m.content:
                parts.append({"type": "text", "text": m.content})
            for part in m.media:
                if part.is_video and not candidate.supports_video:
                    logger.warning(
                        "adapter.video_dropped candidate=%s mime=%s",
                        candidate.key,
                        part.mime_type,
                    )
                    parts.append(
                        {
                            "type": "text",
                            "text": f"[A {part.mime_type} video was attached but this "
                            "model cannot process video.]",
                        }
                    )
                    continue
                # OpenAI-compatible providers accept data URLs for both images and,
                # where supported, video parts.
                key = "video_url" if part.is_video else "image_url"
                parts.append({"type": key, key: {"url": part.to_data_url()}})
            out.append({"role": "user", "content": parts})
            continue

        out.append({"role": m.role.value, "content": m.content})
    return out


def _tools_to_openai(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _response_format(
    candidate: ModelCandidate,
    json_schema: dict[str, Any] | None,
    schema_name: str,
) -> dict[str, Any] | None:
    """Strongest native structured-output mode this candidate actually honours."""
    if json_schema is None:
        return None
    if candidate.supports_json_schema:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": json_schema,
            },
        }
    if candidate.supports_json_object:
        logger.debug(
            "adapter.schema_downgraded candidate=%s mode=json_object", candidate.key
        )
        return {"type": "json_object"}
    logger.debug(
        "adapter.schema_downgraded candidate=%s mode=prompt_only", candidate.key
    )
    return None


def _parse_tool_calls(raw: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for i, tc in enumerate(raw or []):
        fn = tc.get("function") or {}
        args_raw = fn.get("arguments")
        if isinstance(args_raw, dict):
            args = args_raw
        else:
            try:
                args = json.loads(args_raw or "{}")
            except (json.JSONDecodeError, TypeError):
                # A malformed argument blob shouldn't kill the whole turn; the
                # agent loop reports it back to the model as a tool error.
                logger.warning("adapter.bad_tool_args name=%s", fn.get("name"))
                args = {"__parse_error__": str(args_raw)[:500]}
        if not fn.get("name"):
            continue
        calls.append(
            ToolCall(id=tc.get("id") or f"call_{i}", name=fn["name"], arguments=args)
        )
    return calls


def _raise_for_status(exc: httpx.HTTPStatusError, candidate: ModelCandidate) -> None:
    status = exc.response.status_code
    body = exc.response.text[:400]
    if status == 429:
        raise RateLimited(
            f"rate limited: {body}", candidate=candidate.key, status=status
        ) from exc
    if status >= 500:
        raise ProviderUnavailable(
            f"upstream {status}: {body}", candidate=candidate.key, status=status
        ) from exc
    # OpenRouter reports upstream 429s as a 4xx envelope with code 429 inside.
    if "429" in body or "rate-limited" in body.lower() or "quota" in body.lower():
        raise RateLimited(
            f"rate limited (wrapped {status}): {body}",
            candidate=candidate.key,
            status=status,
        ) from exc
    raise RequestInvalid(
        f"invalid request {status}: {body}", candidate=candidate.key, status=status
    ) from exc


class OpenAIAdapter:
    """Chat-completions dialect. Serves OpenRouter, Groq, NVIDIA NIM, Google's shim."""

    dialect = Dialect.OPENAI

    async def complete(
        self,
        client: httpx.AsyncClient,
        *,
        provider: ProviderSpec,
        candidate: ModelCandidate,
        api_key: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        temperature: float = 0.3,
        max_tokens: int | None = None,
        timeout: float = 90.0,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": candidate.model,
            "messages": _messages_to_openai(messages, candidate),
            "temperature": temperature,
            "max_tokens": max_tokens or candidate.max_output_tokens,
        }

        if tools and candidate.supports_tools:
            payload["tools"] = _tools_to_openai(tools)
            payload["tool_choice"] = "auto"
        elif tools:
            logger.warning(
                "adapter.tools_unsupported candidate=%s count=%d",
                candidate.key,
                len(tools),
            )

        rf = _response_format(candidate, json_schema, schema_name)
        if rf:
            payload["response_format"] = rf

        # Pin the upstream so quota attribution is unambiguous.
        if candidate.upstream and provider.supports_upstream_routing:
            payload["provider"] = {
                "order": [candidate.upstream],
                "allow_fallbacks": False,
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **provider.extra_headers,
        }

        try:
            resp = await client.post(
                f"{provider.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _raise_for_status(exc, candidate)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # §3.3: timeouts fail over, not just rate-limit responses.
            raise ProviderUnavailable(
                f"{type(exc).__name__}: {exc}", candidate=candidate.key
            ) from exc

        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(
                f"non-JSON response: {resp.text[:200]}", candidate=candidate.key
            ) from exc

        # Some gateways return HTTP 200 with an error envelope.
        if isinstance(body.get("error"), dict):
            err = body["error"]
            code = err.get("code")
            msg = str(err.get("message"))[:300]
            if str(code) == "429" or "rate" in msg.lower():
                raise RateLimited(msg, candidate=candidate.key, status=429)
            raise ProviderUnavailable(msg, candidate=candidate.key)

        choices = body.get("choices") or []
        if not choices:
            raise ProviderUnavailable(
                f"no choices in response: {str(body)[:200]}", candidate=candidate.key
            )

        choice = choices[0]
        msg = choice.get("message") or {}
        usage = body.get("usage") or {}

        return LLMResponse(
            text=msg.get("content") or "",
            tool_calls=_parse_tool_calls(msg.get("tool_calls")),
            model=body.get("model") or candidate.model,
            provider=candidate.provider,
            finish_reason=choice.get("finish_reason") or "",
            prompt_tokens=usage.get("prompt_tokens") or 0,
            completion_tokens=usage.get("completion_tokens") or 0,
        )


_ADAPTERS = {Dialect.OPENAI: OpenAIAdapter()}


def get_adapter(dialect: Dialect) -> OpenAIAdapter:
    try:
        return _ADAPTERS[dialect]
    except KeyError:
        raise ValueError(f"No adapter for dialect {dialect!r}") from None
