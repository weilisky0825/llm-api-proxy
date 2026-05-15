from __future__ import annotations

import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.logging.middleware import get_middleware
from app.proxy.converter import (
    convert_anthropic_response,
    convert_anthropic_stream,
    openai_to_anthropic,
)
from app.proxy.forwarder import router as provider_router

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "")
    mw = get_middleware()

    start = time.time()
    is_stream = body.get("stream", False)
    provider_config = settings.upstream.get_provider_for_model(model)

    # Build upstream URL for logging
    upstream_path = "/messages" if provider_config.provider == "anthropic" else "/chat/completions"
    upstream_url = f"{provider_config.base_url}{upstream_path}"

    request_id = await mw.on_request(
        {
            "path": "/v1/chat/completions",
            "model": model,
            "api_type": "openai",
            "body": json.dumps(body),
            "headers": json.dumps({"content-type": "application/json"}),
            "provider_name": provider_config.name,
            "upstream_url": upstream_url,
        },
        client_ip=request.client.host if request.client else None,
        user_id=getattr(request.state, "user_id", None),
        user_name=getattr(request.state, "user_name", ""),
    )

    if provider_config.provider == "anthropic":
        upstream_body = openai_to_anthropic(body)
        if is_stream:
            upstream_stream = provider_router.send_stream(model, "/messages", upstream_body)
            return StreamingResponse(
                convert_anthropic_stream(upstream_stream),
                media_type="text/event-stream",
                headers={"X-Request-ID": request_id},
            )
        status, resp_headers, resp_body = await provider_router.send(model, "/messages", upstream_body)
        if status >= 400:
            await mw.on_response(
                request_id, status_code=status,
                response_body=json.dumps(resp_body),
                response_time_ms=int((time.time() - start) * 1000), usage=None,
            )
            return resp_body
        resp_body = convert_anthropic_response(resp_body)
    else:
        if is_stream:
            upstream_stream = provider_router.send_stream(model, "/chat/completions", body)
            return StreamingResponse(
                upstream_stream,
                media_type="text/event-stream",
                headers={"X-Request-ID": request_id},
            )
        status, resp_headers, resp_body = await provider_router.send(model, "/chat/completions", body)

    elapsed = int((time.time() - start) * 1000)
    usage = resp_body.get("usage", {}) if isinstance(resp_body, dict) else {}
    if isinstance(usage, dict):
        usage = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    await mw.on_response(
        request_id,
        status_code=status,
        response_body=json.dumps(resp_body),
        response_time_ms=elapsed,
        usage=usage if isinstance(usage, dict) else None,
    )

    # Update user quota/usage
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        from app.auth.user_middleware import update_user_usage
        await update_user_usage(user_id, usage.get("total_tokens", 0) if isinstance(usage, dict) else 0)

    return resp_body


@router.post("/v1/completions")
async def completions(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    chat_body = {
        "model": body.get("model", ""),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": body.get("max_tokens", 4096),
        "temperature": body.get("temperature", 1.0),
        "stream": body.get("stream", False),
    }
    req = type("FakeRequest", (), {"json": lambda: chat_body, "client": request.client})()
    return await chat_completions(req)


@router.get("/v1/models")
async def list_models():
    status, resp = await router.get_models()
    return resp
