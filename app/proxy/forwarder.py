from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx

from app.config import ProviderConfig, UpstreamConfig


class ProviderClient:
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(config.timeout),
            headers={"Content-Type": "application/json"},
        )

    def _auth_headers(self) -> dict[str, str]:
        if self.config.provider == "openai":
            return {"Authorization": f"Bearer {self.config.api_key}"}
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
        }

    async def send(
        self, path: str, body: dict[str, Any], extra_headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, Any], dict[str, Any]]:
        headers = {**self._auth_headers(), **(extra_headers or {})}
        resp = await self._client.post(path, json=body, headers=headers)
        try:
            resp_body = resp.json()
        except json.JSONDecodeError:
            resp_body = {"error": resp.text}
        return resp.status_code, dict(resp.headers), resp_body

    async def send_stream(
        self, path: str, body: dict[str, Any], extra_headers: dict[str, str] | None = None
    ) -> AsyncGenerator[bytes, None]:
        headers = {**self._auth_headers(), **(extra_headers or {})}
        async with self._client.stream("POST", path, json=body, headers=headers) as resp:
            async for chunk in resp.aiter_bytes():
                yield chunk

    async def close(self):
        await self._client.aclose()


class ProviderRouter:
    def __init__(self):
        self._clients: dict[str, ProviderClient] = {}
        self._upstream: UpstreamConfig = UpstreamConfig()

    def initialize(self, upstream_config: UpstreamConfig):
        self._upstream = upstream_config
        self._clients.clear()

        if not upstream_config.providers:
            legacy = ProviderConfig(
                name="legacy", provider=upstream_config.provider,
                api_key=upstream_config.api_key, base_url=upstream_config.base_url,
                timeout=upstream_config.timeout, default=True,
            )
            self._clients["legacy"] = ProviderClient(legacy)
        else:
            for p in upstream_config.providers:
                self._clients[p.name] = ProviderClient(p)

    def get_client(self, model: str) -> ProviderClient:
        provider = self._upstream.get_provider_for_model(model)
        return self._clients[provider.name]

    async def send(
        self, model: str, path: str, body: dict[str, Any], extra_headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, Any], dict[str, Any]]:
        return await self.get_client(model).send(path, body, extra_headers)

    async def send_stream(
        self, model: str, path: str, body: dict[str, Any], extra_headers: dict[str, str] | None = None
    ) -> AsyncGenerator[bytes, None]:
        client = self.get_client(model)
        async with client._client.stream(
            "POST", path, json=body, headers={**client._auth_headers(), **(extra_headers or {})}
        ) as resp:
            async for line in resp.aiter_lines():
                if line:
                    yield (line + "\n").encode("utf-8")
                else:
                    yield b"\n"

    async def close_all(self):
        for c in self._clients.values():
            await c.close()

    async def get_models(self) -> tuple[int, dict]:
        if self._clients:
            client = next(iter(self._clients.values()))
            resp = await client._client.get("/models", headers=client._auth_headers())
            try:
                return resp.status_code, resp.json()
            except json.JSONDecodeError:
                return resp.status_code, {"error": resp.text}
        return 0, {"error": "No providers configured"}


router = ProviderRouter()
forwarder = router  # Backward compat alias
