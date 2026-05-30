from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from .models import CharacterProfile, VoiceAssignment
from .utils import safe_filename


class TTSBackend:
    def synthesize(self, text: str, voice: str, out_wav: Path, profile: CharacterProfile | None = None) -> None:
        raise NotImplementedError


class KokoroBackend(TTSBackend):
    def __init__(self) -> None:
        try:
            from kokoro import KPipeline
        except Exception as exc:
            raise SystemExit("Kokoro is not installed. Run: pip install kokoro") from exc

        self.pipeline = KPipeline(lang_code="b")

    def synthesize(self, text: str, voice: str, out_wav: Path, profile: CharacterProfile | None = None) -> None:
        import numpy as np
        import soundfile as sf

        out_wav.parent.mkdir(parents=True, exist_ok=True)
        voice = voice or "bm_george"

        parts = []
        for _, _, audio in self.pipeline(text, voice=voice):
            parts.append(audio)

        if not parts:
            raise RuntimeError("Kokoro returned no audio")

        sf.write(str(out_wav), np.concatenate(parts), 24000)


class XTTSBackend(TTSBackend):
    def __init__(self) -> None:
        try:
            from TTS.api import TTS
        except Exception as exc:
            raise SystemExit("Coqui TTS is not installed. Run: pip install TTS") from exc

        self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

    def synthesize(self, text: str, voice: str, out_wav: Path, profile: CharacterProfile | None = None) -> None:
        out_wav.parent.mkdir(parents=True, exist_ok=True)

        speaker_wav = voice if voice and Path(voice).exists() else None
        if speaker_wav:
            self.tts.tts_to_file(
                text=text,
                speaker_wav=speaker_wav,
                language="en",
                file_path=str(out_wav),
            )
        else:
            self.tts.tts_to_file(
                text=text,
                language="en",
                file_path=str(out_wav),
            )


class FishSpeechBackend(TTSBackend):
    def __init__(self, command: str) -> None:
        if not command:
            raise SystemExit("--fish-command is required for backend=fish")
        self.command = command

    def synthesize(self, text: str, voice: str, out_wav: Path, profile: CharacterProfile | None = None) -> None:
        out_wav.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            *shlex.split(self.command),
            "--text", text,
            "--out", str(out_wav),
        ]

        if voice:
            cmd.extend(["--reference-audio", voice])
        if profile and profile.voice_direction:
            cmd.extend(["--voice-direction", profile.voice_direction])

        subprocess.run(cmd, check=True)


def backend_for(args: argparse.Namespace) -> TTSBackend:
    if args.backend == "kokoro":
        return KokoroBackend()
    if args.backend == "xtts":
        return XTTSBackend()
    if args.backend == "fish":
        return FishSpeechBackend(args.fish_command)
    raise SystemExit(f"Unknown backend: {args.backend}")


def default_fish_command(script_path: Path) -> str:
    wrapper_path = script_path.resolve().parent.parent / "fish_tts_wrapper.py"
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(wrapper_path))}"


def reference_seed_text(speaker: str, profile: CharacterProfile) -> str:
    if speaker == "Narrator":
        return (
            "The evening settled into quiet shadow. "
            "The narration should be clear, steady, warm, and comfortable for long listening."
        )

    traits = ", ".join(profile.personality[:4]) or profile.voice_style or "natural"
    return (
        f"This is {speaker}. "
        f"The voice should sound {profile.age}, {profile.gender}, {profile.dialect}, {traits}. "
        f"{profile.voice_direction}. "
        "Keep it natural, consistent, distinct from the rest of the cast, and do not imitate a real person."
    )


def generate_reference_voices(
    speakers: list[str],
    profiles: dict[str, CharacterProfile],
    voice_map: dict[str, VoiceAssignment],
    reference_dir: Path,
    method: str,
    force: bool = False,
    fish_command: str = "",
) -> None:
    reference_dir.mkdir(parents=True, exist_ok=True)

    if method == "kokoro":
        generator: TTSBackend = KokoroBackend()
    elif method == "fish":
        generator = FishSpeechBackend(fish_command)
    else:
        raise SystemExit(f"Unknown reference voice method: {method}")

    for speaker in speakers:
        profile = profiles.get(speaker) or CharacterProfile(name=speaker)
        out_wav = reference_dir / f"{safe_filename(speaker, 'speaker')}.wav"

        if out_wav.exists() and not force:
            continue

        assignment = voice_map.get(speaker)
        seed_voice = assignment.voice if assignment and method == "kokoro" else ""

        print(f"Generating {method} reference voice: {speaker} -> {out_wav}")
        generator.synthesize(reference_seed_text(speaker, profile), seed_voice, out_wav, profile)


FISH_API_WRAPPER = r'''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import requests

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080/v1/tts")
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--reference-audio", default="")
    parser.add_argument("--voice-direction", default="")
    args = parser.parse_args()

    text = args.text.strip()
    if args.voice_direction:
        text = f"Voice direction: {args.voice_direction}. Speak naturally as an audiobook character. Text: {text}"

    payload = {"text": text}

    files = None
    if args.reference_audio:
        files = {"reference_audio": open(args.reference_audio, "rb")}

    try:
        resp = requests.post(args.url, data=payload, files=files, timeout=600)
        resp.raise_for_status()
        with open(args.out, "wb") as f:
            f.write(resp.content)
    finally:
        if files:
            files["reference_audio"].close()

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''
