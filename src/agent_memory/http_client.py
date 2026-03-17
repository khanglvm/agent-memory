"""Shared HTTP client for embedding and LLM providers."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class APIClient:
    """Async HTTP client with retry logic and optional API key auth."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        allow_insecure: bool = False,
    ) -> None:
        # [RT-15] Enforce HTTPS when api_key is set (unless allow_insecure=True)
        if api_key and not allow_insecure and base_url.startswith("http://"):
            raise ValueError(
                f"[RT-15] API key provided but base_url uses HTTP: {base_url!r}. "
                "Use HTTPS or set allow_insecure=True to override."
            )

        self._base_url = base_url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    async def post(self, path: str, json: dict, **kwargs) -> dict:
        """POST request with exponential backoff on 429 (max 3 retries)."""
        max_retries = 3
        delay = 1.0

        for attempt in range(max_retries + 1):
            response = await self._client.post(path, json=json, **kwargs)

            if response.status_code == 429:
                if attempt < max_retries:
                    logger.warning(
                        "Rate limited (429), retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                response.raise_for_status()

            response.raise_for_status()
            return response.json()

        # Unreachable, but satisfies type checker
        raise RuntimeError("Exceeded retry attempts")  # pragma: no cover

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
