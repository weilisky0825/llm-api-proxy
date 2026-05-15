from __future__ import annotations

import json
from typing import Any, AsyncGenerator


# ---------------------------------------------------------------------------
# OpenAI → Anthropic
# ---------------------------------------------------------------------------


def openai_to_anthropic(body: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict] = body.get("messages", [])
    system_messages = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    result: dict[str, Any] = {
        "model": body.get("model", ""),
        "messages": [_convert_message(m) for m in non_system],
        "max_tokens": body.get("max_tokens", 4096),
        "temperature": body.get("temperature", 1.0),
        "stream": body.get("stream", False),
    }

    if system_messages:
        # Merge multiple system messages into one
        result["system"] = "\n".join(m.get("content", "") for m in system_messages)

    if "stop" in body and body["stop"]:
        stops = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]
        result["stop_sequences"] = stops

    return result


def _convert_message(msg: dict[str, Any]) -> dict[str, Any]:
    role = msg.get("role", "user")
    content = msg.get("content", "")

    if isinstance(content, str):
        return {"role": role, "content": content}

    # content is a list (multimodal)
    blocks = []
    for part in content:
        ptype = part.get("type", "")
        if ptype == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif ptype == "image_url":
            url_data = part.get("image_url", {})
            url = url_data.get("url", "")
            if url.startswith("data:"):
                media_type, b64 = _parse_data_url(url)
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    }
                )
            else:
                blocks.append(
                    {
                        "type": "image",
                        "source": {"type": "url", "url": url},
                    }
                )
        elif ptype == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": part.get("id", ""),
                    "name": part.get("name", ""),
                    "input": part.get("input", {}),
                }
            )
        elif ptype == "tool_result":
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": part.get("tool_use_id", ""),
                    "content": part.get("content", ""),
                }
            )
        else:
            blocks.append({"type": "text", "text": json.dumps(part)})

    return {"role": role, "content": blocks}


def _parse_data_url(url: str) -> tuple[str, str]:
    # data:image/png;base64,XXXXX
    header, data = url.split(",", 1)
    media_type = header.split(":")[1].split(";")[0]
    return media_type, data


# ---------------------------------------------------------------------------
# Anthropic → OpenAI
# ---------------------------------------------------------------------------


def anthropic_to_openai(body: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict] = body.get("messages", [])
    system = body.get("system", "")

    openai_messages = []
    if system:
        openai_messages.append({"role": "system", "content": system})

    for msg in messages:
        openai_messages.append(_convert_anthropic_message(msg))

    result: dict[str, Any] = {
        "model": body.get("model", ""),
        "messages": openai_messages,
        "max_tokens": body.get("max_tokens", 4096),
        "temperature": body.get("temperature", 1.0),
        "stream": body.get("stream", False),
    }

    if "stop_sequences" in body and body["stop_sequences"]:
        result["stop"] = body["stop_sequences"]

    return result


def _convert_anthropic_message(msg: dict[str, Any]) -> dict[str, Any]:
    role = msg.get("role", "user")
    content = msg.get("content", "")

    if isinstance(content, str):
        return {"role": role, "content": content}

    # content is a list of blocks
    parts = []
    for block in content:
        btype = block.get("type", "")
        if btype == "text":
            parts.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image":
            source = block.get("source", {})
            if source.get("type") == "base64":
                data_url = f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
            else:
                parts.append(
                    {"type": "image_url", "image_url": {"url": source.get("url", "")}}
                )
        elif btype == "tool_use":
            parts.append(
                {
                    "type": "tool_use",
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                }
            )
        elif btype == "tool_result":
            parts.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("tool_use_id", ""),
                    "content": block.get("content", ""),
                }
            )
        else:
            parts.append(block)

    return {"role": role, "content": parts if len(parts) > 1 else (parts[0].get("text", "") if parts and parts[0].get("type") == "text" else parts)}


# ---------------------------------------------------------------------------
# Response conversion
# ---------------------------------------------------------------------------


def convert_anthropic_response(body: dict[str, Any]) -> dict[str, Any]:
    content_blocks = body.get("content", [])
    text = ""
    for block in content_blocks:
        if block.get("type") == "text":
            text += block.get("text", "")

    usage = body.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    return {
        "id": body.get("id", ""),
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": _map_stop_reason(body.get("stop_reason")),
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def convert_openai_response(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices", [])
    text = ""
    if choices:
        message = choices[0].get("message", {})
        text = message.get("content", "")

    usage = body.get("usage", {})

    return {
        "id": body.get("id", ""),
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": body.get("model", ""),
        "stop_reason": _map_stop_reason(choices[0].get("finish_reason") if choices else None),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _map_stop_reason(reason: str | None) -> str | None:
    if reason in ("stop", "end_turn"):
        return "end_turn"
    if reason in ("length", "max_tokens"):
        return "max_tokens"
    if reason == "tool_calls":
        return "tool_use"
    if reason == "content_filter":
        return "end_turn"
    return reason


# ---------------------------------------------------------------------------
# Streaming conversion
# ---------------------------------------------------------------------------


async def convert_anthropic_stream(
    stream: AsyncGenerator[bytes, None],
) -> AsyncGenerator[bytes, None]:
    """Convert Anthropic SSE stream to OpenAI SSE format."""
    event_type = None
    chunk_id = "chatcmpl-proxy"
    index = 0

    async for raw_line in stream:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line.strip():
            continue

        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
            continue

        if line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if event_type == "message_start":
                msg = data.get("message", {})
                yield f"data: {json.dumps({'id': msg.get('id', ''), 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"

            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                text = delta.get("text", "")
                if text:
                    yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'choices': [{'index': index, 'delta': {'content': text}, 'finish_reason': None}]})}\n\n"

            elif event_type == "message_delta":
                usage = data.get("usage", {})
                stop_reason = data.get("delta", {}).get("stop_reason")
                finish = _map_stop_reason(stop_reason)
                payload: dict[str, Any] = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": index, "delta": {}, "finish_reason": finish}],
                }
                if usage:
                    payload["usage"] = {
                        "prompt_tokens": usage.get("input_tokens", 0),
                        "completion_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                    }
                yield f"data: {json.dumps(payload)}\n\n"
                yield "data: [DONE]\n\n"


async def convert_openai_stream(
    stream: AsyncGenerator[bytes, None],
) -> AsyncGenerator[bytes, None]:
    """Convert OpenAI SSE stream to Anthropic SSE format."""
    async for raw_line in stream:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line.strip():
            continue

        if not line.startswith("data:"):
            continue

        data_str = line[len("data:"):].strip()
        if data_str == "[DONE]":
            yield 'event: message_delta\ndata: {"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 0}}\n\n'
            continue

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        choices = data.get("choices", [])
        if not choices:
            continue

        choice = choices[0]
        delta = choice.get("delta", {})
        finish = choice.get("finish_reason")

        if delta.get("role") == "assistant":
            yield 'event: message_start\ndata: {"type": "message_start", "message": {"id": "' + data.get("id", "") + '", "type": "message", "role": "assistant", "content": [], "model": "' + data.get("model", "") + '"}}\n\n'
            yield 'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\n'
            continue

        text = delta.get("content", "")
        if text:
            yield f'event: content_block_delta\ndata: {{"type": "content_block_delta", "index": 0, "delta": {{"type": "text_delta", "text": "{text}"}}}}\n\n'

        if finish:
            usage = data.get("usage", {})
            yield f'event: message_delta\ndata: {{"type": "message_delta", "delta": {{"stop_reason": "{_map_stop_reason(finish)}"}}, "usage": {{"input_tokens": {usage.get("prompt_tokens", 0)}, "output_tokens": {usage.get("completion_tokens", 0)}}}}}\n\n'
