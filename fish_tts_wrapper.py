#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def read_reference_audio(path: str) -> str | None:
    if not path:
        return None

    p = Path(path)
    if not p.exists():
        return None

    return base64.b64encode(p.read_bytes()).decode("ascii")


def post_json(url: str, payload: dict, timeout: int = 300) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "audio/wav, audio/*, application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        content_type = resp.headers.get("Content-Type", "")

        if "application/json" in content_type:
            parsed = json.loads(body.decode("utf-8"))
            for key in ("audio", "audio_base64", "wav", "data"):
                value = parsed.get(key)
                if isinstance(value, str):
                    try:
                        return base64.b64decode(value)
                    except Exception:
                        pass

            raise RuntimeError(f"JSON response did not contain base64 audio keys: {list(parsed.keys())}")

        return body


def main() -> int:
    parser = argparse.ArgumentParser(description="Wrapper around Fish Speech HTTP TTS API.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", "--out", dest="output", required=True, type=Path)
    parser.add_argument("--voice-direction", default="natural audiobook character voice")
    parser.add_argument("--reference-audio", default="")
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--api-url", default=os.environ.get("FISH_API_URL", "http://127.0.0.1:8080/v1/tts"))
    args = parser.parse_args()

    text = args.text.strip()
    if args.voice_direction:
        prompted_text = (
            f"Voice direction: {args.voice_direction}. "
            f"Speak naturally as an audiobook character. Text: {text}"
        )
    else:
        prompted_text = text

    payload = {"text": prompted_text}
    ref_b64 = read_reference_audio(args.reference_audio)

    if ref_b64:
        payload["reference_audio"] = ref_b64
        payload["reference_text"] = args.reference_text or text[:240]

    try:
        audio = post_json(args.api_url, payload)
    except urllib.error.HTTPError as exc:
        sys.stderr.write(exc.read().decode("utf-8", errors="replace") + "\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"Fish API request failed: {exc}\n")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(audio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
