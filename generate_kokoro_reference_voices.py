#!/usr/bin/env python3
from __future__ import annotations

import re

BAD_REFERENCE_METADATA = {
    "by", "status", "published", "updated", "words", "chapters",
    "rated", "original source", "source", "author", "title",
}

BAD_REFERENCE_STARTS = (
    "the ", "a ", "an ", "his ", "her ", "their ", "while ", "well ",
    "each ", "almost ", "accelerating ", "setting ", "flanked ",
    "resistance ", "tendrils ", "weather ", "humanity ", "space ",
    "turn ", "point ", "or ", "in ", "re ", "dear ",
)

def is_bad_reference_speaker(name: str) -> bool:
    name = re.sub(r"\s+", " ", str(name or "")).strip().strip("\"'“”‘’:-—–")
    if not name:
        return True
    if name in {"Narrator", "Unknown"}:
        return False

    low = name.lower()
    words = name.split()

    if low in BAD_REFERENCE_METADATA:
        return True
    if any(low.startswith(prefix) for prefix in BAD_REFERENCE_STARTS):
        return True
    if len(words) > 3:
        return True
    if any(ch in name for ch in ".!?;,:/\\[]{}()"):
        return True
    if "'" in name and len(words) > 1:
        return True
    if len(name) > 40:
        return True
    if not re.match(r"^[A-Za-z][A-Za-z0-9 '\-\.]*$", name):
        return True

    return False


import hashlib
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

OUT = Path("audiobook_out")
REF = OUT / "reference_voices"
REF.mkdir(parents=True, exist_ok=True)

profiles_path = OUT / "character_profiles.json"
cast_path = OUT / "character_cast.json"
voice_map_path = OUT / "voice_map.provisional_kokoro.json"

if not profiles_path.exists():
    raise SystemExit(f"Missing {profiles_path}; run metadata stage first.")

profiles = json.loads(profiles_path.read_text())

casts = {}
if cast_path.exists():
    casts = json.loads(cast_path.read_text())

if voice_map_path.exists():
    voice_map = json.loads(voice_map_path.read_text())
else:
    male = ["bm_daniel", "bm_fable", "bm_george", "bm_lewis"]
    female = ["bf_alice", "bf_emma", "bf_isabella", "bf_lily"]
    neutral = ["bm_fable", "bm_george", "bf_emma", "bf_isabella"]

    def stable_index(text: str, modulo: int) -> int:
        return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) % modulo

    voice_map = {}
    for name, p in profiles.items():
        gender = p.get("gender", "neutral")
        pool = male if gender == "male" else female if gender == "female" else neutral
        voice_map[name] = {"voice": pool[stable_index(name, len(pool))]}

def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")[:80] or "speaker"

def seed_text(name: str, profile: dict, cast: dict) -> str:
    if name == "Narrator":
        return (
            "The evening settled into quiet shadow. "
            "The narration should be clear, steady, warm, and comfortable for long listening."
        )

    personality = profile.get("personality") or cast.get("personality") or []
    traits = ", ".join(personality[:4]) or profile.get("voice_style") or cast.get("voice_style") or "natural"
    dialect = (
        cast.get("accent_region")
        or profile.get("accent_region")
        or profile.get("dialect")
        or "neutral British or Irish"
    )
    direction = (
        cast.get("voice_direction")
        or profile.get("voice_direction")
        or "natural audiobook character voice"
    )

    return (
        f"This is {name}. "
        f"The voice should sound {profile.get('age', cast.get('age', 'adult'))}, "
        f"{profile.get('gender', cast.get('gender', 'neutral'))}, "
        f"{dialect}, {traits}. "
        f"{direction}. "
        "Keep it natural, consistent, distinct from the rest of the cast, and do not imitate a real person."
    )

pipeline = KPipeline(lang_code="b")

for name, profile in profiles.items():
    out = REF / f"{safe_filename(name)}.wav"
    if out.exists():
        print(f"exists: {out}")
        continue

    voice = voice_map.get(name, {}).get("voice", "bm_george")
    cast = casts.get(name, {})

    print(f"generating reference: {name}: {voice} -> {out}")

    parts = []
    for _, _, audio in pipeline(seed_text(name, profile, cast), voice=voice):
        parts.append(audio)

    if not parts:
        print(f"no audio for {name}")
        continue

    sf.write(str(out), np.concatenate(parts), 24000)
