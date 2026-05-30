from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from .backends import backend_for, reference_seed_text
from .models import CharacterProfile, ProsodySettings, Segment, VoiceAssignment
from .utils import safe_filename


def write_silence(path: Path, sample_rate: int = 24000, duration_ms: int = 220) -> None:
    import numpy as np
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    samples = int(sample_rate * duration_ms / 1000)
    sf.write(str(path), np.zeros(samples, dtype=np.float32), sample_rate)


def _needs_prosody_filter(prosody: ProsodySettings | None) -> list[str]:
    """Return ffmpeg audio filter args if prosody requires processing, else empty list."""
    if not prosody:
        return []
    filters = []
    if abs(prosody.tempo - 1.0) > 0.001:
        filters.append(f"atempo={max(0.5, min(2.0, prosody.tempo))}")
    if abs(prosody.volume_db) > 0.01:
        filters.append(f"volume={prosody.volume_db}dB")
    return filters


def apply_audio_filter(src: Path, dst: Path, prosody: ProsodySettings | None) -> Path:
    """Apply prosody filter. Returns the path to use (src if no filter needed, dst if filtered)."""
    filters = _needs_prosody_filter(prosody)
    if not filters:
        return src

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", ",".join(filters), str(dst)]
    subprocess.run(cmd, check=True)
    return dst


def concatenate_wavs(wavs: list[Path], out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_wav.parent / "concat_list.txt"

    with list_file.open("w") as f:
        for wav in wavs:
            f.write(f"file '{wav.resolve()}'\n")

    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_wav)],
        check=True,
    )


def concat_and_encode_m4b(wavs: list[Path], out_m4b: Path) -> None:
    """Single-pass: concat WAVs and encode to M4B in one ffmpeg call (no intermediate full WAV)."""
    out_m4b.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_m4b.parent / "concat_list.txt"

    with list_file.open("w") as f:
        for wav in wavs:
            f.write(f"file '{wav.resolve()}'\n")

    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-vn",
            "-c:a", "aac",
            "-b:a", "96k",
            "-movflags", "+faststart",
            str(out_m4b),
        ],
        check=True,
    )


def _get_shared_silence(silence_cache: dict[int, Path], silence_dir: Path, duration_ms: int) -> Path:
    """Get or create a shared silence WAV for a given duration. One file per unique duration."""
    if duration_ms in silence_cache:
        return silence_cache[duration_ms]

    silence_path = silence_dir / f"silence_{duration_ms}ms.wav"
    if not silence_path.exists():
        write_silence(silence_path, duration_ms=duration_ms)

    silence_cache[duration_ms] = silence_path
    return silence_path


def render_audiobook(
    segments: list[Segment],
    profiles: dict[str, CharacterProfile],
    voice_map: dict[str, VoiceAssignment],
    prosody_map: dict[str, ProsodySettings],
    args: argparse.Namespace,
) -> Path:
    backend = backend_for(args)

    segments_dir = args.out / "rendered_segments"
    processed_dir = args.out / "processed_segments"
    silence_dir = args.out / "silence"
    segments_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    silence_dir.mkdir(parents=True, exist_ok=True)

    wavs: list[Path] = []
    silence_cache: dict[int, Path] = {}

    for n, seg in enumerate(segments, 1):
        if not seg.text:
            continue

        speaker = seg.speaker if seg.speaker in voice_map else "Narrator"
        assignment = voice_map.get(speaker) or VoiceAssignment(speaker=speaker, voice="")
        profile = profiles.get(speaker) or CharacterProfile(name=speaker)
        prosody = prosody_map.get(speaker)

        raw_wav = segments_dir / f"{seg.idx:06d}_{safe_filename(speaker, 'speaker')}.wav"
        processed_wav = processed_dir / f"{seg.idx:06d}_{safe_filename(speaker, 'speaker')}.wav"

        if not raw_wav.exists():
            print(f"Rendering {n}/{len(segments)}: {speaker}: {seg.text[:80]}")
            backend.synthesize(seg.text, assignment.voice, raw_wav, profile)

        if processed_wav.exists():
            wavs.append(processed_wav)
        else:
            wavs.append(apply_audio_filter(raw_wav, processed_wav, prosody))

        pause_ms = prosody.pause_ms if prosody else args.pause_ms
        if pause_ms > 0:
            wavs.append(_get_shared_silence(silence_cache, silence_dir, pause_ms))

    out_m4b = args.out / f"{safe_filename(args.epub.stem, 'audiobook')}.m4b"

    print(f"Encoding M4B directly from {len(wavs)} WAVs ({len(silence_cache)} unique silence durations)...")
    concat_and_encode_m4b(wavs, out_m4b)

    return out_m4b


def preview_voices(
    speakers: list[str],
    profiles: dict[str, CharacterProfile],
    voice_map: dict[str, VoiceAssignment],
    prosody_map: dict[str, ProsodySettings],
    args: argparse.Namespace,
) -> None:
    backend = backend_for(args)
    preview_dir = args.out / "voice_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    wavs: list[Path] = []

    for speaker in speakers:
        profile = profiles.get(speaker) or CharacterProfile(name=speaker)
        assignment = voice_map.get(speaker) or VoiceAssignment(speaker=speaker, voice="")
        out = preview_dir / f"{safe_filename(speaker, 'speaker')}.wav"

        if not out.exists():
            text = f"{speaker}. {reference_seed_text(speaker, profile)}"
            backend.synthesize(text[:700], assignment.voice, out, profile)

        wavs.append(out)

    combined = args.out / "voice_previews_combined.wav"
    concatenate_wavs(wavs, combined)
