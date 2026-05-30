from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .constants import ACCENT_REGION_DIRECTIONS, ACCENT_REGIONS
from .llm import ollama_chat
from .models import CharacterCast, CharacterProfile, Segment
from .parsing import discover_speakers
from .utils import clean_text, extract_json_object, guess_character_gender, write_json


def _group_segments_by_chapter(segments: list[Segment]) -> dict[int, list[Segment]]:
    """Group segments by chapter number, preserving order."""
    chapters: dict[int, list[Segment]] = {}
    for seg in segments:
        chapters.setdefault(seg.chapter, []).append(seg)
    return chapters


def _build_chapter_prompt(chapter_segs: list[Segment], max_chars: int = 24000) -> tuple[str, list[Segment]]:
    """Build chapter text with dialogue lines marked. Returns prompt text and dialogue segments."""
    lines: list[str] = []
    dialogue_segs: list[Segment] = []
    char_count = 0

    for seg in chapter_segs:
        if char_count >= max_chars:
            break
        if seg.kind == "dialogue":
            line = f'[DIALOGUE id={seg.idx}] "{seg.text}"'
            dialogue_segs.append(seg)
        else:
            line = seg.text[:500]
        lines.append(line)
        char_count += len(line)

    return "\n".join(lines), dialogue_segs


def refine_speakers_with_llm(
    segments: list[Segment],
    model: str,
    host: str,
    out_path: Path,
    batch_size: int,
    force: bool = False,
    max_dialogue: int | None = None,
) -> list[Segment]:
    if out_path.exists() and not force:
        data = json.loads(out_path.read_text())
        return [Segment(**item) for item in data]

    from datetime import datetime
    import time

    system_prompt = (
        "You are a literary analyst attributing dialogue to characters in a book. "
        "You will receive full chapter text with dialogue lines marked as [DIALOGUE id=N]. "
        "Use the surrounding narration for clues (e.g. 'he said', 'she replied', character actions). "
        "Return strict JSON only. No markdown. No thinking. No commentary."
    )

    chapters = _group_segments_by_chapter(segments)
    chapter_nums = sorted(chapters.keys())
    total_attributed = 0

    for ci, chap_num in enumerate(chapter_nums):
        chap_segs = chapters[chap_num]
        chapter_text, dialogue_segs = _build_chapter_prompt(chap_segs)

        if not dialogue_segs:
            continue

        ts = datetime.now().strftime("%H:%M:%S")
        print(
            f"[{ts}] LLM speaker chapter {ci+1}/{len(chapter_nums)} "
            f"(ch.{chap_num}): {len(dialogue_segs)} dialogue lines, "
            f"{len(chapter_text)} chars"
        )
        t0 = time.monotonic()

        ids_list = ", ".join(str(s.idx) for s in dialogue_segs)
        prompt = f"""
Below is the full text of chapter {chap_num}. Dialogue lines are marked with [DIALOGUE id=N].
Use the narration context to determine who is speaking each dialogue line.

Return a JSON object mapping each dialogue id to the speaker name.
You MUST include ALL of these ids: {ids_list}
Use character names (e.g. "Squall", "Zell"), not descriptions.
If you truly cannot determine the speaker, use "Unknown".

Chapter text:
{chapter_text}
""".strip()

        try:
            raw = ollama_chat(
                model, system_prompt, prompt, host,
                num_ctx=16384,
                timeout_override=300,
            )
            result = extract_json_object(raw)

            attributed = 0
            for seg in dialogue_segs:
                speaker = clean_text(str(result.get(str(seg.idx), "")))
                if speaker and speaker != "Unknown":
                    seg.speaker = speaker[:80]
                    attributed += 1

            elapsed = time.monotonic() - t0
            ts2 = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts2}] ch.{chap_num}: attributed {attributed}/{len(dialogue_segs)} in {elapsed:.1f}s")
            total_attributed += attributed

        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ch.{chap_num} FAILED after {elapsed:.1f}s: {exc}")

    print(f"Total attributed: {total_attributed} dialogue lines across {len(chapter_nums)} chapters")
    write_json(out_path, [dataclasses.asdict(seg) for seg in segments])
    return segments


def identify_cast_with_llm(
    segments: list[Segment],
    model: str,
    host: str,
    cache_path: Path,
    force: bool = False,
) -> dict[str, str | None]:
    """Ask the LLM to identify real characters from the raw speaker list.

    Returns a dict mapping every raw speaker name to either:
      - a canonical name (for aliases, e.g. "Squall Leonhart" -> "Squall")
      - the same name (confirmed real character)
      - None (garbage / not a character)
    """
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text())

    speakers = discover_speakers(segments)
    # Count dialogue lines per speaker for context
    counts: dict[str, int] = {}
    for seg in segments:
        if seg.kind == "dialogue" and seg.speaker in speakers:
            counts[seg.speaker] = counts.get(seg.speaker, 0) + 1

    speaker_info = {
        s: {"dialogue_lines": counts.get(s, 0)}
        for s in speakers
        if s not in ("Narrator", "Unknown")
    }

    system_prompt = (
        "You are a literary analyst identifying real characters in a book. "
        "You MUST return a JSON object with one key per speaker name from the input. "
        "Return strict JSON only. No markdown. No commentary. No thinking."
    )

    user_prompt = f"""
I have {len(speaker_info)} speaker names extracted from a book, with dialogue line counts.
Many are NOT real characters. You must classify EVERY SINGLE name below.

For each speaker name, return:
- The canonical character name (string) if it is a real character
- null if it is NOT a character (garbage, metadata, chapter title, sentence fragment, reviewer name)

If two names refer to the same character (e.g. "Bob" and "Bob Smith"), map both to the
shorter canonical form (e.g. "Bob Smith": "Bob", "Bob": "Bob").

IMPORTANT:
- You MUST include ALL {len(speaker_info)} speaker names in your response.
- Names with many dialogue lines (>5) are very likely real characters.
- Names with 0-1 dialogue lines that look like sentences or titles are likely garbage.
- Generic roles like "Commander", "Guard", "Student" with dialogue lines ARE valid speakers.
- Do NOT include "Narrator" or "Unknown" in your response.
- Do NOT repeat examples — classify the ACTUAL names listed below.

Return a single JSON object mapping every name to its canonical form or null:

ACTUAL SPEAKER NAMES TO CLASSIFY:
{json.dumps(speaker_info, indent=2, ensure_ascii=False)}
""".strip()

    result: dict[str, str | None] = {}
    try:
        raw = ollama_chat(
            model, system_prompt, user_prompt, host,
            num_ctx=16384,
            timeout_override=600,
        )
        result = extract_json_object(raw)
    except Exception as exc:
        print(f"LLM cast identification failed; skipping: {exc}")
        return {}

    # Check coverage — if the LLM returned too few entries, it probably
    # echoed examples instead of processing the real list
    coverage = len(result) / max(len(speaker_info), 1)
    if coverage < 0.3:
        print(f"LLM cast identification returned only {len(result)}/{len(speaker_info)} entries ({coverage:.0%} coverage) — likely bad response, skipping")
        return {}

    # Validate: canonical names must themselves map to themselves
    canonical_names = {v for v in result.values() if v is not None}
    for canon in canonical_names:
        if canon in result and result[canon] is None:
            # LLM contradicted itself — keep the canonical
            result[canon] = canon
        elif canon not in result:
            result[canon] = canon

    write_json(cache_path, result)

    kept = sum(1 for v in result.values() if v is not None)
    removed = sum(1 for v in result.values() if v is None)
    aliases = sum(1 for k, v in result.items() if v is not None and v != k)
    print(f"LLM cast identification: {kept} characters kept, {removed} removed, {aliases} aliases merged")

    return result


def apply_cast_identification(
    segments: list[Segment],
    cast_map: dict[str, str | None],
) -> list[Segment]:
    """Apply the LLM cast identification to segments: remap aliases, demote garbage to Narrator/Unknown."""
    if not cast_map:
        return segments

    for seg in segments:
        if seg.speaker in ("Narrator", "Unknown"):
            continue
        mapped = cast_map.get(seg.speaker)
        if mapped is None:
            # Garbage speaker — demote
            seg.speaker = "Unknown" if seg.kind == "dialogue" else "Narrator"
        elif mapped != seg.speaker:
            # Alias — remap to canonical name
            seg.speaker = mapped

    return segments


def cast_sample_pack(segments: list[Segment], max_chars: int = 26000) -> dict:
    speakers = [s for s in discover_speakers(segments) if s != "Narrator"]
    pack: dict[str, dict] = {
        speaker: {"approx_dialogue_chars": 0, "sample_lines": [], "nearby_context": []}
        for speaker in speakers
    }

    for i, seg in enumerate(segments):
        if seg.kind != "dialogue" or seg.speaker not in pack:
            continue

        item = pack[seg.speaker]
        item["approx_dialogue_chars"] += len(seg.text)

        if len(item["sample_lines"]) < 8:
            item["sample_lines"].append(seg.text[:420])

        if len(item["nearby_context"]) < 3:
            ctx = []
            for j in range(max(0, i - 2), min(len(segments), i + 3)):
                s2 = segments[j]
                ctx.append(f"{s2.kind}/{s2.speaker}: {s2.text[:240]}")
            item["nearby_context"].append(ctx)

    ordered = dict(sorted(pack.items(), key=lambda kv: kv[1]["approx_dialogue_chars"], reverse=True))
    text = json.dumps(ordered, ensure_ascii=False)
    if len(text) <= max_chars:
        return ordered

    slim: dict[str, dict] = {}
    total = 0
    for speaker, item in ordered.items():
        reduced = {
            "approx_dialogue_chars": item["approx_dialogue_chars"],
            "sample_lines": item["sample_lines"][:4],
            "nearby_context": item["nearby_context"][:1],
        }
        chunk = json.dumps({speaker: reduced}, ensure_ascii=False)
        if total + len(chunk) > max_chars:
            break
        slim[speaker] = reduced
        total += len(chunk)

    return slim


def fallback_cast_for_speaker(speaker: str, overrides: dict | None = None) -> CharacterCast:
    gender = guess_character_gender(speaker, overrides)
    accent = "neutral_british_irish"

    if speaker == "Narrator":
        return CharacterCast(
            name=speaker,
            gender="neutral",
            role="narrator",
            accent_region="neutral_british_irish",
            accent_confidence=0.8,
            accent_basis="audiobook_default",
            voice_style="clear narrator",
            personality=["clear", "steady", "warm"],
            voice_direction="clear, steady audiobook narrator with a neutral British and Irish broadcast style",
        )

    return CharacterCast(
        name=speaker,
        gender=gender,
        age="adult",
        role="character",
        social_register="unknown",
        accent_region=accent,
        accent_confidence=0.2,
        accent_basis="unknown",
        reason="No strong evidence available; using neutral British/Irish audiobook casting.",
        voice_style="natural",
        personality=["natural", "distinct", "consistent"],
        voice_direction=(
            f"{gender} adult character voice; neutral British and Irish audiobook style; "
            "natural, consistent, distinct from the rest of the cast"
        ),
    )


def infer_character_cast_with_llm(
    segments: list[Segment],
    model: str,
    host: str,
    cache_path: Path,
    force: bool = False,
    overrides: dict | None = None,
) -> dict[str, CharacterCast]:
    if cache_path.exists() and not force:
        data = json.loads(cache_path.read_text())
        return {name: CharacterCast(**item) for name, item in data.items()}

    speakers = discover_speakers(segments)
    sample_pack = cast_sample_pack(segments)

    system_prompt = (
        "You are a casting director for a synthetic audiobook. "
        "Infer consistent whole-book character casting from dialogue and context. "
        "Return strict JSON only. No markdown. No commentary. "
        "Do not imitate real actors or real people. "
        "Do not assign strong regional accents without a reason. "
        "Use unknown or neutral_british_irish when evidence is weak."
    )

    user_prompt = f"""
Assign a consistent casting profile for each character.

Allowed accent_region values:
{json.dumps(ACCENT_REGIONS, ensure_ascii=False)}

accent_basis must be one of:
- explicit_textual_evidence
- character_name_or_origin_hint
- social_role_inference
- personality_casting_choice
- weak_inference
- unknown

Rules:
1. Keep each character's accent_region consistent across the entire book.
2. Do not collapse British/Irish voices into only English RP.
3. Do not randomly distribute accents purely for variety.
4. If evidence is weak, choose neutral_british_irish or unknown.
5. If choosing a regional accent from weak inference, set accent_confidence below 0.55.
6. voice_direction should be concise and usable by a TTS model.
7. Avoid stereotypes. Use respectful regional casting language.
8. Do not imitate any real person.

Character evidence:
{json.dumps(sample_pack, indent=2, ensure_ascii=False)}

Return this JSON shape:
{{
  "Character Name": {{
    "name": "Character Name",
    "gender": "male|female|neutral",
    "age": "child|young_adult|adult|older_adult",
    "role": "short role",
    "social_register": "working_class|middle_class|upper_class|military|royal|academic|neutral|unknown",
    "accent_region": "one allowed accent_region",
    "accent_confidence": 0.0,
    "accent_basis": "one allowed basis",
    "reason": "short explanation",
    "voice_style": "short style",
    "personality": ["trait1", "trait2", "trait3"],
    "voice_direction": "concise synthetic audiobook voice direction"
  }}
}}
""".strip()

    raw_result: dict = {}
    try:
        raw = ollama_chat(
            model, system_prompt, user_prompt, host,
            num_ctx=16384,
            timeout_override=600,
        )
        raw_result = extract_json_object(raw)
    except Exception as exc:
        print(f"Character cast LLM pass failed; using fallback cast. Reason: {exc}")

    casts: dict[str, CharacterCast] = {}

    for speaker in speakers:
        if speaker == "Narrator":
            casts[speaker] = fallback_cast_for_speaker("Narrator", overrides)
            continue

        raw_item = raw_result.get(speaker, {}) if isinstance(raw_result, dict) else {}
        fallback = fallback_cast_for_speaker(speaker, overrides)

        accent = str(raw_item.get("accent_region") or fallback.accent_region)
        if accent not in ACCENT_REGIONS:
            accent = "unknown"

        try:
            confidence = float(raw_item.get("accent_confidence", fallback.accent_confidence))
        except Exception:
            confidence = fallback.accent_confidence

        casts[speaker] = CharacterCast(
            name=speaker,
            gender=str(raw_item.get("gender") or fallback.gender),
            age=str(raw_item.get("age") or fallback.age),
            role=str(raw_item.get("role") or fallback.role),
            social_register=str(raw_item.get("social_register") or fallback.social_register),
            accent_region=accent,
            accent_confidence=max(0.0, min(1.0, confidence)),
            accent_basis=str(raw_item.get("accent_basis") or fallback.accent_basis),
            reason=str(raw_item.get("reason") or fallback.reason),
            voice_style=str(raw_item.get("voice_style") or fallback.voice_style),
            personality=list(raw_item.get("personality") or fallback.personality),
            voice_direction=str(raw_item.get("voice_direction") or fallback.voice_direction),
        )

    if overrides:
        for speaker, override in overrides.items():
            if not isinstance(override, dict):
                continue
            base = casts.get(speaker) or fallback_cast_for_speaker(speaker, overrides)
            casts[speaker] = CharacterCast(
                name=speaker,
                gender=str(override.get("gender") or base.gender),
                age=str(override.get("age") or base.age),
                role=str(override.get("role") or base.role),
                social_register=str(override.get("social_register") or base.social_register),
                accent_region=str(override.get("accent_region") or override.get("dialect") or base.accent_region),
                accent_confidence=float(override.get("accent_confidence") or base.accent_confidence),
                accent_basis=str(override.get("accent_basis") or base.accent_basis),
                reason=str(override.get("accent_reason") or override.get("reason") or base.reason),
                voice_style=str(override.get("voice_style") or base.voice_style),
                personality=list(override.get("personality") or base.personality),
                voice_direction=str(override.get("voice_direction") or base.voice_direction),
            )

    write_json(cache_path, {k: dataclasses.asdict(v) for k, v in casts.items()})
    return casts


def overrides_from_character_cast(casts: dict[str, CharacterCast]) -> dict:
    result: dict[str, dict] = {}

    for speaker, cast in casts.items():
        accent_hint = ACCENT_REGION_DIRECTIONS.get(cast.accent_region, ACCENT_REGION_DIRECTIONS["unknown"])
        direction = cast.voice_direction or (
            f"{cast.age} {cast.gender} voice; {accent_hint}; "
            f"{cast.voice_style}; natural audiobook character performance"
        )

        result[speaker] = {
            "gender": cast.gender,
            "dialect": cast.accent_region,
            "accent_region": cast.accent_region,
            "accent_confidence": cast.accent_confidence,
            "accent_basis": cast.accent_basis,
            "accent_reason": cast.reason,
            "age": cast.age,
            "role": cast.role,
            "social_register": cast.social_register,
            "voice_style": cast.voice_style,
            "personality": cast.personality,
            "voice_direction": direction,
        }

    return result


def infer_character_profiles(
    speakers: list[str],
    casts: dict[str, CharacterCast],
    cache_path: Path,
    force: bool = False,
    overrides: dict | None = None,
) -> dict[str, CharacterProfile]:
    if cache_path.exists() and not force:
        data = json.loads(cache_path.read_text())
        return {name: CharacterProfile(**item) for name, item in data.items()}

    profiles: dict[str, CharacterProfile] = {}

    for speaker in speakers:
        cast = casts.get(speaker) or fallback_cast_for_speaker(speaker, overrides)
        profiles[speaker] = CharacterProfile(
            name=speaker,
            gender=cast.gender,
            age=cast.age,
            role=cast.role,
            voice_style=cast.voice_style,
            dialect=cast.accent_region,
            personality=cast.personality,
            delivery="natural",
            pitch="medium",
            voice_direction=cast.voice_direction,
        )

    if overrides:
        for speaker, override in overrides.items():
            if not isinstance(override, dict):
                continue
            base = profiles.get(speaker) or CharacterProfile(name=speaker)
            profiles[speaker] = CharacterProfile(
                name=speaker,
                gender=str(override.get("gender") or base.gender),
                age=str(override.get("age") or base.age),
                role=str(override.get("role") or base.role),
                voice_style=str(override.get("voice_style") or base.voice_style),
                dialect=str(override.get("dialect") or override.get("accent_region") or base.dialect),
                personality=list(override.get("personality") or base.personality),
                delivery=str(override.get("delivery") or base.delivery),
                pitch=str(override.get("pitch") or base.pitch),
                voice_direction=str(override.get("voice_direction") or base.voice_direction),
            )

    write_json(cache_path, {k: dataclasses.asdict(v) for k, v in profiles.items()})
    return profiles
