from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def ollama_chat(
    model: str,
    system_prompt: str,
    user_prompt: str,
    host: str,
    num_ctx: int | None = None,
    timeout_override: int | None = None,
) -> str:
    timeout = timeout_override or int(os.environ.get("OLLAMA_TIMEOUT", "120"))
    retries = int(os.environ.get("OLLAMA_RETRIES", "1"))
    prompt_chars = len(user_prompt)

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": float(os.environ.get("OLLAMA_TEMPERATURE", "0.1")),
            "num_ctx": num_ctx or int(os.environ.get("OLLAMA_NUM_CTX", "8192")),
        },
    }

    url = host.rstrip("/") + "/api/chat"
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        t0 = time.monotonic()
        print(f"[{_ts()}] ollama request: model={model} prompt={prompt_chars}ch timeout={timeout}s attempt={attempt+1}/{retries+1}")
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            content = raw.get("message", {}).get("content", "").strip()
            elapsed = time.monotonic() - t0
            print(f"[{_ts()}] ollama response: {len(content)}ch in {elapsed:.1f}s")
            return content
        except Exception as exc:
            elapsed = time.monotonic() - t0
            last_error = exc
            if attempt < retries:
                print(f"[{_ts()}] ollama FAILED after {elapsed:.1f}s, retrying {attempt + 1}/{retries}: {exc}")
                time.sleep(2 + attempt * 3)
            else:
                print(f"[{_ts()}] ollama FAILED after {elapsed:.1f}s (final): {exc}")

    raise TimeoutError(f"Ollama call failed after {retries + 1} attempts: {last_error}")
