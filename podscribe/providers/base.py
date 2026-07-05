"""Provider protocol + the shared retry/stream wrapper used by every provider."""
from __future__ import annotations

import time
from typing import Callable, Optional, Protocol

import requests

RETRY_DELAYS = [1, 2, 4]


def stream_with_retry(
    make_response: Callable[[], requests.Response],
    consume: Callable[[requests.Response], str],
    *,
    max_retries: int,
    on_retry: Callable[[int, str], None],
) -> Optional[str]:
    """POST + stream with the project's retry policy.

    Retries connection errors and 5xx (sleeping RETRY_DELAYS between attempts).
    Returns None on any 4xx or after exhausting retries. `consume` turns the
    streamed response into the accumulated text and may raise RequestException
    mid-stream (caught and retried).
    """
    for attempt in range(max_retries):
        try:
            resp = make_response()
            resp.raise_for_status()
            return consume(resp)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is not None and 400 <= status < 500:
                return None  # 4xx: don't retry
            if attempt < max_retries - 1:
                on_retry(attempt + 1, str(e))
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
                continue
            return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                on_retry(attempt + 1, str(e))
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
                continue
            return None
    return None


class Provider(Protocol):
    """Contract every provider implements. model/base_url/api_key are baked in."""

    model: str

    def generate(
        self, prompt: str, *, max_retries: int = 3,
        on_token: Callable[[str], None] = lambda t: None,
        on_stats: Callable[[dict], None] = lambda d: None,
        on_retry: Callable[[int, str], None] = lambda a, e: None,
    ) -> Optional[str]: ...

    def chat(
        self, messages: list, tools: Optional[list] = None, *, max_retries: int = 3,
        on_token: Callable[[str], None] = lambda t: None,
        on_message: Callable[[dict], None] = lambda d: None,
        on_retry: Callable[[int, str], None] = lambda a, e: None,
    ) -> Optional[str]: ...

    def model_info(self) -> dict: ...
