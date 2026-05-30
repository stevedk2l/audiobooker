from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .constants import (
    KOKORO_AMERICAN_FEMALE_VOICES,
    KOKORO_AMERICAN_MALE_VOICES,
    KOKORO_AMERICAN_NEUTRAL_VOICES,
    KOKORO_BRITISH_FEMALE_VOICES,
    KOKORO_BRITISH_MALE_VOICES,
    KOKORO_BRITISH_NEUTRAL_VOICES,
)
from .models import CharacterProfile, ProsodySettings, VoiceAssignment
from .utils import guess_character_gender, safe_filename, stable_index, write_json


def kokoro_pool_for(profile: CharacterProfile, accent: str) -> list[str]:
    gender = profile.gender

    if accent == "american":
        if gender == "male":
            return KOKORO_AMERICAN_MALE_VOICES
        if gender == "female":
            return KOKORO_AMERICAN_FEMALE_VOICES
        return KOKORO_AMERICAN_NEUTRAL_VOICES

    if accent == "mixed":
        if gender == "male":
            return KOKORO_BRITISH_MALE_VOICES + KOKORO_AMERICAN_MALE_VOICES
        if gender == "female":
            return KOKORO_BRITISH_FEMALE_VOICES + KOKORO_AMERICAN_FEMALE_VOICES
        return KOKORO_BRITISH_NEUTRAL_VOICES + KOKORO_AMERICAN_NEUTRAL_VOICES

    if gender == "male":
        return KOKORO_BRITISH_MALE_VOICES
    if gender == "female":
        return KOKORO_BRITISH_FEMALE_VOICES
    return KOKORO_BRITISH_NEUTRAL_VOICES


def load_or_create_voice_map(
    path: Path,
    speakers: list[str],
    profiles: dict[str, CharacterProfile],
    force: bool,
    accent: str,
    backend: str,
    reference_dir: Path,
    overrides: dict | None,
) -> dict[str, VoiceAssignment]:
    if path.exists() and not force:
        data = json.loads(path.read_text())
        return {k: VoiceAssignment(**v) for k, v in data.items()}

    voice_map: dict[str, VoiceAssignment] = {}

    for speaker in speakers:
        profile = profiles.get(speaker) or CharacterProfile(name=speaker, gender=guess_character_gender(speaker, overrides))
        override = overrides.get(speaker, {}) if overrides else {}

        if backend == "xtts":
            ref = reference_dir / f"{safe_filename(speaker, 'speaker')}.wav"
            voice = str(ref) if ref.exists() else ""
            voice_map[speaker] = VoiceAssignment(
                speaker=speaker,
                voice=voice,
                description=f"XTTS reference voice for {speaker}",
                reference_audio=voice,
                voice_direction=profile.voice_direction,
            )
            continue

        if backend == "fish":
            ref = reference_dir / f"{safe_filename(speaker, 'speaker')}.wav"
            voice = str(ref) if ref.exists() else ""
            voice_map[speaker] = VoiceAssignment(
                speaker=speaker,
                voice=voice,
                description=f"Fish reference/prompt voice for {speaker}",
                reference_audio=voice,
                voice_direction=profile.voice_direction,
            )
            continue

        if override.get("voice"):
            voice = str(override["voice"])
        else:
            pool = kokoro_pool_for(profile, accent)
            voice = pool[stable_index(f"{speaker}:{profile.gender}:{profile.dialect}:{profile.voice_style}", len(pool))]

        voice_map[speaker] = VoiceAssignment(
            speaker=speaker,
            voice=voice,
            description=f"Kokoro {profile.gender} {profile.dialect} voice",
            reference_audio="",
            voice_direction=profile.voice_direction,
        )

    write_json(path, {k: dataclasses.asdict(v) for k, v in voice_map.items()})
    return voice_map


def prosody_from_profile(profile: CharacterProfile) -> ProsodySettings:
    pitch = 0.0
    tempo = 1.0
    volume = 0.0
    pause = 220

    if profile.gender == "male":
        pitch -= 0.7
    elif profile.gender == "female":
        pitch += 0.5

    if profile.age == "child":
        pitch += 1.2
        tempo += 0.04
    elif profile.age == "older_adult":
        pitch -= 0.4
        tempo -= 0.04

    traits = {t.lower() for t in profile.personality}
    if "energetic" in traits or "bright" in traits:
        tempo += 0.04
    if "reserved" in traits or "calm" in traits:
        tempo -= 0.03
    if "authoritative" in traits:
        volume += 0.6
        pause += 40

    if profile.name == "Narrator":
        tempo = 0.98
        pause = 280

    variant = stable_index(profile.name, 1000)
    if profile.name != "Narrator":
        pitch += [-0.5, -0.25, 0, 0.25, 0.5][variant % 5]
        tempo *= [0.97, 0.985, 1.0, 1.015, 1.03][variant % 5]

    return ProsodySettings(
        speaker=profile.name,
        pitch_semitones=round(pitch, 2),
        tempo=round(max(0.8, min(1.2, tempo)), 3),
        volume_db=round(volume, 2),
        pause_ms=max(120, min(650, pause)),
        description=profile.voice_direction,
    )


def load_or_create_prosody_map(
    path: Path,
    speakers: list[str],
    profiles: dict[str, CharacterProfile],
    force: bool,
) -> dict[str, ProsodySettings]:
    if path.exists() and not force:
        data = json.loads(path.read_text())
        return {k: ProsodySettings(**v) for k, v in data.items()}

    result = {
        speaker: prosody_from_profile(profiles.get(speaker) or CharacterProfile(name=speaker))
        for speaker in speakers
    }

    write_json(path, {k: dataclasses.asdict(v) for k, v in result.items()})
    return result


def write_reference_voice_manifest(path: Path, speakers: list[str], profiles: dict[str, CharacterProfile], reference_dir: Path) -> None:
    manifest = {}
    for speaker in speakers:
        profile = profiles.get(speaker) or CharacterProfile(name=speaker)
        manifest[speaker] = {
            "speaker": speaker,
            "reference_audio": str(reference_dir / f"{safe_filename(speaker, 'speaker')}.wav"),
            "gender": profile.gender,
            "age": profile.age,
            "dialect": profile.dialect,
            "voice_direction": profile.voice_direction,
        }
    write_json(path, manifest)
