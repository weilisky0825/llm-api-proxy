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
        "messages": [_convert_openai_message(m) for m in non_system],
        "max_tokens": body.get("max_tokens", 4096),
        "temperature": body.get("temperature", 1.0),
        "stream": body.get("stream", False),
    }

    if system_messages:
        result["system"] = "\n".join(m.get("content", "") for m in system_messages)

    if "stop" in body and body["stop"]:
        stops = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]
        result["stop_sequences"] = stops

    return result


def _convert_openai_message(msg: dict[str, Any]) -> dict[str, Any]:
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
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                })
            else:
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
        elif ptype == "tool_use":
            blocks.append({
                "type": "tool_use",
                "id": part.get("id", ""),
                "name": part.get("name", ""),
                "input": part.get("input", {}),
            })
        elif ptype == "tool_result":
            raw = part.get("content", "")
            if isinstance(raw, list):
                text_parts = []
                for item in raw:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    else:
                        text_parts.append(str(item))
                content_str = "\n".join(text_parts) if text_parts else ""
            else:
                content_str = str(raw) if raw is not None else ""
            blocks.append({
                "type": "tool_result",
                "tool_use_id": part.get("tool_call_id", part.get("tool_use_id", "")),
                "content": content_str,
            })
        else:
            blocks.append({"type": "text", "text": json.dumps(part)})

    return {"role": role, "content": blocks}


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
        openai_messages.extend(_convert_anthropic_message(msg))

    result: dict[str, Any] = {
        "model": body.get("model", ""),
        "messages": openai_messages,
        "max_tokens": body.get("max_tokens", 4096),
        "temperature": body.get("temperature", 1.0),
        "stream": body.get("stream", False),
    }

    if "stop_sequences" in body and body["stop_sequences"]:
        result["stop"] = body["stop_sequences"]

    # Convert tools from Anthropic → OpenAI format
    if "tools" in body and body["tools"]:
        openai_tools = []
        for t in body["tools"]:
            # Anthropic: {"name": "x", "description": "y", "input_schema": {...}}
            # OpenAI: {"type": "function", "function": {"name": "x", "description": "y", "parameters": {...}}}
            func = {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            }
            openai_tools.append({"type": "function", "function": func})
        result["tools"] = openai_tools

    # Convert tool_choice
    if "tool_choice" in body:
        tc = body["tool_choice"]
        if isinstance(tc, str):
            result["tool_choice"] = tc
        elif isinstance(tc, dict):
            tc_type = tc.get("type", "")
            if tc_type == "tool":
                result["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tc.get("name", "")},
                }
            else:
                result["tool_choice"] = tc

    return result


def _convert_anthropic_message(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a single Anthropic message to OpenAI format.

    Returns a list because Anthropic tool_result blocks in a user message
    become multiple OpenAI messages with role="tool".
    """
    role = msg.get("role", "user")
    content = msg.get("content", "")

    if isinstance(content, str):
        return [{"role": role, "content": content}]

    # Check for tool_use blocks (assistant message)
    has_tool_use = any(b.get("type") == "tool_use" for b in content)
    if has_tool_use:
        return _convert_tool_use_message(content)

    # Check for tool_result blocks (user message with tool results)
    has_tool_result = any(b.get("type") == "tool_result" for b in content)
    if has_tool_result:
        return _convert_tool_result_message(content)

    # Regular message with content blocks
    parts = []
    thinking_text = ""
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
                parts.append({"type": "image_url", "image_url": {"url": source.get("url", "")}})
        elif btype == "thinking":
            # Collect thinking text as a text block
            thinking_text = block.get("thinking", "")
        elif btype == "tool_result":
            raw = block.get("content", "")
            if isinstance(raw, list):
                text_parts = []
                for item in raw:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    else:
                        text_parts.append(str(item))
                content_str = "\n".join(text_parts) if text_parts else ""
            else:
                content_str = str(raw) if raw is not None else ""
            parts.append({
                "type": "tool_result",
                "tool_call_id": block.get("tool_use_id", ""),
                "content": content_str,
            })

    if not parts:
        return [{"role": role, "content": thinking_text if thinking_text else ""}]

    # Flatten: if only one text part, return simple string content
    if len(parts) == 1 and parts[0].get("type") == "text":
        return [{"role": role, "content": parts[0].get("text", "")}]

    return [{"role": role, "content": parts}]


def _convert_tool_use_message(content: list[dict]) -> list[dict[str, Any]]:
    """Convert assistant message with tool_use blocks to OpenAI tool_calls format."""
    text_parts = []
    tool_calls = []

    for block in content:
        btype = block.get("type", "")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_input = block.get("input", {})
            tool_calls.append({
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input),
                },
            })
        elif btype == "thinking":
            text_parts.append(block.get("thinking", ""))

    msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
    if tool_calls:
        msg["tool_calls"] = tool_calls

    return [msg]


def _convert_tool_result_message(content: list[dict]) -> list[dict[str, Any]]:
    """Convert user message with tool_result blocks to separate OpenAI tool messages."""
    results = []
    text_parts = []

    for block in content:
        btype = block.get("type", "")
        if btype == "tool_result":
            raw = block.get("content", "")
            if isinstance(raw, list):
                text_parts_inner = []
                for item in raw:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts_inner.append(item.get("text", ""))
                    else:
                        text_parts_inner.append(str(item))
                content_str = "\n".join(text_parts_inner) if text_parts_inner else ""
            else:
                content_str = str(raw) if raw is not None else ""
            results.append({
                "role": "tool",
                "tool_call_id": block.get("tool_use_id", ""),
                "content": content_str,
            })
        elif btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "thinking":
            text_parts.append(block.get("thinking", ""))

    msgs = []
    if text_parts:
        msgs.append({"role": "user", "content": "\n".join(text_parts)})
    msgs.extend(results)
    return msgs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_data_url(url: str) -> tuple[str, str]:
    header, data = url.split(",", 1)
    media_type = header.split(":")[1].split(";")[0]
    return media_type, data


# ---------------------------------------------------------------------------
# Response conversion
# ---------------------------------------------------------------------------


def convert_anthropic_response(body: dict[str, Any]) -> dict[str, Any]:
    content_blocks = body.get("content", [])
    text = ""
    tool_calls = []

    for block in content_blocks:
        if block.get("type") == "text":
            text += block.get("text", "")
        elif block.get("type") == "tool_use":
            tool_input = block.get("input", {})
            tool_calls.append({
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input),
                },
            })

    usage = body.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    message = {"role": "assistant", "content": text if text else None}
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": body.get("id", ""),
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": message,
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
    tool_use_blocks = []

    if choices:
        message = choices[0].get("message", {})
        text = message.get("content", "") or ""

        # Convert OpenAI tool_calls to Anthropic tool_use
        for tc in message.get("tool_calls", []):
            func = tc.get("function", {})
            try:
                tool_input = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                tool_input = {}
            tool_use_blocks.append({
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "input": tool_input,
            })

    usage = body.get("usage", {})

    content = [{"type": "text", "text": text}] if text else []
    content.extend(tool_use_blocks)

    return {
        "id": body.get("id", ""),
        "type": "message",
        "role": "assistant",
        "content": content,
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
    tool_call_index = 0
    current_tool_call = {}

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
                msg = data.get("message", {}) or {}
                yield f"data: {json.dumps({'id': msg.get('id', ''), 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"

            elif event_type == "content_block_start":
                block = data.get("content_block", {}) or {}
                btype = block.get("type", "")
                if btype == "tool_use":
                    tc_idx = data.get("index", tool_call_index)
                    current_tool_call = {
                        "index": tc_idx,
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "args": "",
                    }
                    payload = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "tool_calls": [{
                                    "index": tc_idx,
                                    "id": block.get("id", ""),
                                    "type": "function",
                                    "function": {"name": block.get("name", ""), "arguments": ""},
                                }]
                            },
                            "finish_reason": None,
                        }],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

            elif event_type == "content_block_delta":
                delta = data.get("delta", {}) or {}
                dtype = delta.get("type", "")
                if dtype == "text":
                    yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'choices': [{'index': index, 'delta': {'content': delta.get('text', '')}, 'finish_reason': None}]})}\n\n"
                elif dtype == "input_json_delta":
                    partial = delta.get("partial_json", "")
                    if current_tool_call:
                        current_tool_call["args"] += partial
                        payload = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "tool_calls": [{
                                        "index": current_tool_call["index"],
                                        "function": {"arguments": partial},
                                    }]
                                },
                                "finish_reason": None,
                            }],
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

            elif event_type == "message_delta":
                usage = data.get("usage") or {}
                stop_reason = (data.get("delta") or {}).get("stop_reason")
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
    initialized = False

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

        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            continue

        choice = choices[0]
        if not choice or not isinstance(choice, dict):
            continue

        delta = choice.get("delta")
        if delta is None:
            delta = {}
        finish = choice.get("finish_reason")

        # Only emit message_start/content_block_start once
        if delta.get("role") == "assistant" and not initialized:
            initialized = True
            yield 'event: message_start\ndata: {"type": "message_start", "message": {"id": "' + data.get("id", "") + '", "type": "message", "role": "assistant", "content": [], "model": "' + data.get("model", "") + '"}}\n\n'
            yield 'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\n'
            continue

        # Skip pure role announcements (no content)
        if delta.get("role") == "assistant" and not delta.get("content") and not delta.get("reasoning_content") and not delta.get("tool_calls"):
            continue

        # Upstream may send text in reasoning_content instead of content
        text = delta.get("content", "") or delta.get("reasoning_content", "")
        if text:
            safe_text = json.dumps(text)
            yield f'event: content_block_delta\ndata: {{"type": "content_block_delta", "index": 0, "delta": {{"type": "text_delta", "text": {safe_text}}}}}\n\n'

        # Handle tool_calls in delta
        tool_calls = delta.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                tc_idx = tc.get("index", 0)
                if tc.get("id"):
                    # First time we see this tool call
                    func = tc.get("function", {}) or {}
                    tc_block = json.dumps({
                        "type": "content_block_start",
                        "index": tc_idx,
                        "content_block": {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": func.get("name", ""),
                            "input": {},
                        },
                    })
                    yield f'event: content_block_start\ndata: {tc_block}\n\n'
                if tc.get("function", {}).get("arguments"):
                    args = tc["function"]["arguments"]
                    tc_delta = json.dumps({
                        "type": "content_block_delta",
                        "index": tc_idx,
                        "delta": {"type": "input_json_delta", "partial_json": args},
                    })
                    yield f'event: content_block_delta\ndata: {tc_delta}\n\n'

        if finish:
            usage = data.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
            completion_tokens = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
            payload = json.dumps({
                "type": "message_delta",
                "delta": {"stop_reason": _map_stop_reason(finish)},
                "usage": {"input_tokens": prompt_tokens, "output_tokens": completion_tokens},
            })
            yield f'event: message_delta\ndata: {payload}\n\n'
