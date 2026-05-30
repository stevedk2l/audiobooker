from __future__ import annotations

import re

from .constants import BAD_SPEAKER_STARTS, GENERIC_BAD_SPEAKERS, METADATA_SPEAKERS
from .models import VoiceAssignment


def normalize_speaker_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    return name.strip(" \t\r\n\"'“”‘’:-—–")


def is_probably_bad_speaker_name(name: str) -> bool:
    name = normalize_speaker_name(name)
    if not name:
        return True

    if name in {"Narrator", "Unknown"}:
        return False

    low = name.lower()
    words = name.split()

    if low in METADATA_SPEAKERS:
        return True

    if low in GENERIC_BAD_SPEAKERS:
        return True

    if any(low.startswith(prefix) for prefix in BAD_SPEAKER_STARTS):
        return True

    if len(words) > 3:
        return True

    if any(ch in name for ch in ".!?;"):
        return True

    if any(ch in name for ch in ",:/\\[]{}()"):
        return True

    if "'" in name and len(words) > 1:
        return True

    if len(words) > 1:
        capitalized = sum(1 for w in words if w[:1].isupper())
        if capitalized < len(words):
            return True

    if len(name) > 40:
        return True

    if not re.match(r"^[A-Za-z][A-Za-z0-9 '\-.]*$", name):
        return True

    return False


def collect_known_cast_names(casts=None, character_overrides=None) -> set[str]:
    known = set()

    if casts:
        for cast in casts:
            name = getattr(cast, "name", None)
            if name:
                known.add(normalize_speaker_name(name))
            elif isinstance(cast, dict) and cast.get("name"):
                known.add(normalize_speaker_name(cast["name"]))

    if character_overrides:
        known.update(normalize_speaker_name(k) for k in character_overrides.keys())

    return {x for x in known if x and not is_probably_bad_speaker_name(x)}


def filter_segments_to_real_speakers(segments: list[dict], known_cast_names: set[str] | None = None) -> list[dict]:
    known_cast_names = known_cast_names or set()
    cleaned = []

    for seg in segments:
        seg = dict(seg)
        speaker = normalize_speaker_name(seg.get("speaker", ""))

        if speaker in {"Narrator", "Unknown"}:
            seg["speaker"] = speaker
        elif speaker in known_cast_names:
            seg["speaker"] = speaker
        elif is_probably_bad_speaker_name(speaker):
            seg["speaker"] = "Unknown" if seg.get("kind") == "dialogue" else "Narrator"
        else:
            seg["speaker"] = speaker

        cleaned.append(seg)

    return cleaned


def filter_voice_map_to_real_speakers(
    voice_map: dict,
    segments: list[dict],
    known_cast_names: set[str] | None = None,
) -> dict:
    known_cast_names = known_cast_names or set()
    used_speakers = {
        normalize_speaker_name(seg.get("speaker", ""))
        for seg in segments
        if normalize_speaker_name(seg.get("speaker", ""))
    }

    allowed = {"Narrator", "Unknown"} | known_cast_names | used_speakers
    cleaned = {}

    for speaker, entry in (voice_map or {}).items():
        speaker = normalize_speaker_name(speaker)
        if not speaker:
            continue
        if speaker not in allowed:
            continue
        if speaker not in {"Narrator", "Unknown"} and speaker not in known_cast_names and is_probably_bad_speaker_name(speaker):
            continue
        cleaned[speaker] = entry

    if "Narrator" not in cleaned:
        cleaned["Narrator"] = VoiceAssignment(
            speaker="Narrator",
            voice="bf_lily",
            description="Default narrator voice",
            reference_audio="",
            voice_direction="clear neutral audiobook narration",
        )

    return cleaned


def filtered_speaker_list(segments: list[dict], known_cast_names: set[str] | None = None) -> list[str]:
    known_cast_names = known_cast_names or set()
    speakers = {
        normalize_speaker_name(seg.get("speaker", ""))
        for seg in segments
        if normalize_speaker_name(seg.get("speaker", ""))
    }

    speakers = {
        s for s in speakers
        if s in {"Narrator", "Unknown"} or s in known_cast_names or not is_probably_bad_speaker_name(s)
    }

    return sorted(speakers, key=lambda x: (x != "Narrator", x == "Unknown", x.lower()))
