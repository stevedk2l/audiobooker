from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .constants import KNOWN_FEMALE_HINTS, KNOWN_MALE_HINTS


def stable_index(text: str, modulo: int) -> int:
    if modulo <= 0:
        return 0
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16) % modulo


def safe_filename(text: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
    return cleaned[:100] or fallback


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return text


def read_json(path: Path, default: Any) -> Any:
    if path and path.exists():
        return json.loads(path.read_text())
    return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError("No JSON object found in LLM response")


def load_character_overrides(path: Path | None) -> dict:
    if not path:
        return {}
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def guess_character_gender(speaker: str, overrides: dict | None = None) -> str:
    if overrides and speaker in overrides and isinstance(overrides[speaker], dict):
        gender = overrides[speaker].get("gender")
        if gender:
            return str(gender)

    low = speaker.lower()
    if low in KNOWN_MALE_HINTS or any(h in low.split() for h in KNOWN_MALE_HINTS):
        return "male"
    if low in KNOWN_FEMALE_HINTS or any(h in low.split() for h in KNOWN_FEMALE_HINTS):
        return "female"

    if low.endswith(("a", "ia", "elle", "ine")):
        return "female"

    return "neutral"
