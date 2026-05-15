from __future__ import annotations
import json
import time
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.config import settings
from app.logging.middleware import get_middleware
from app.proxy.converter import (
    anthropic_to_openai,
    convert_openai_response,
    convert_openai_stream,
)
from app.proxy.forwarder import router as provider_router
router = APIRouter()
@router.post("/v1/messages")
async def messages(request: Request):
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
            "path": "/v1/messages",
            "model": model,
            "api_type": "anthropic",
            "body": json.dumps(body),
            "headers": json.dumps(
                {
                    "content-type": "application/json",
                    "anthropic-version": request.headers.get(
                        "anthropic-version", "2023-06-01"
                    ),
                }
            ),
            "provider_name": provider_config.name,
            "upstream_url": upstream_url,
        },
        client_ip=request.client.host if request.client else None,
        user_id=getattr(request.state, "user_id", None),
        user_name=getattr(request.state, "user_name", ""),
    )
    if provider_config.provider == "openai":
        upstream_body = anthropic_to_openai(body)
        if is_stream:
            upstream_stream = provider_router.send_stream(model, "/chat/completions", upstream_body)
            return StreamingResponse(
                convert_openai_stream(upstream_stream),
                media_type="text/event-stream",
                headers={"X-Request-ID": request_id},
            )
        status, resp_headers, resp_body = await provider_router.send(model, "/chat/completions", upstream_body)
        if status >= 400:
            await mw.on_response(
                request_id, status_code=status,
                response_body=json.dumps(resp_body),
                response_time_ms=int((time.time() - start) * 1000), usage=None,
            )
            return resp_body
        resp_body = convert_openai_response(resp_body)
    else:
        if is_stream:
            upstream_stream = provider_router.send_stream(model, "/messages", body)
            return StreamingResponse(
                upstream_stream,
                media_type="text/event-stream",
                headers={"X-Request-ID": request_id},
            )
        status, resp_headers, resp_body = await provider_router.send(model, "/messages", body)
    elapsed = int((time.time() - start) * 1000)
    usage = None
    if isinstance(resp_body, dict):
        resp_usage = resp_body.get("usage", {})
        if isinstance(resp_usage, dict):
            usage = {
                "input_tokens": resp_usage.get("input_tokens", 0),
                "output_tokens": resp_usage.get("output_tokens", 0),
                "total_tokens": resp_usage.get("input_tokens", 0)
                + resp_usage.get("output_tokens", 0),
            }
    await mw.on_response(
        request_id,
        status_code=status,
        response_body=json.dumps(resp_body) if not isinstance(resp_body, str) else resp_body,
        response_time_ms=elapsed,
        usage=usage,
    )
    # Update user quota/usage
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        from app.auth.user_middleware import update_user_usage
        await update_user_usage(user_id, usage.get("total_tokens", 0) if isinstance(usage, dict) else 0)
    return resp_body
@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    body = await request.json()
    text = body.get("text", "")
    estimated = max(1, len(text) // 4)
    return {"token_count": estimated}
@router.get("/v1/models")
async def list_models():
    status, resp = await provider_router.get_models()
    return resp
