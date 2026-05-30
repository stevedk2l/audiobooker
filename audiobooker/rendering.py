from __future__ import annotations

import argparse
import shutil
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


def apply_audio_filter(src: Path, dst: Path, prosody: ProsodySettings | None) -> None:
    if not prosody:
        shutil.copyfile(src, dst)
        return

    filters = []

    if abs(prosody.tempo - 1.0) > 0.001:
        tempo = max(0.5, min(2.0, prosody.tempo))
        filters.append(f"atempo={tempo}")

    if abs(prosody.volume_db) > 0.01:
        filters.append(f"volume={prosody.volume_db}dB")

    if not filters:
        shutil.copyfile(src, dst)
        return

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", ",".join(filters), str(dst)]
    subprocess.run(cmd, check=True)


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


def encode_m4b(in_wav: Path, out_m4b: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(in_wav),
            "-vn",
            "-c:a", "aac",
            "-b:a", "96k",
            "-movflags", "+faststart",
            str(out_m4b),
        ],
        check=True,
    )


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
    segments_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    wavs: list[Path] = []

    for n, seg in enumerate(segments, 1):
        if not seg.text:
            continue

        speaker = seg.speaker if seg.speaker in voice_map else "Narrator"
        assignment = voice_map.get(speaker) or VoiceAssignment(speaker=speaker, voice="")
        profile = profiles.get(speaker) or CharacterProfile(name=speaker)
        prosody = prosody_map.get(speaker)

        raw_wav = segments_dir / f"{seg.idx:06d}_{safe_filename(speaker, 'speaker')}.wav"
        processed_wav = processed_dir / f"{seg.idx:06d}_{safe_filename(speaker, 'speaker')}.wav"
        pause_wav = processed_dir / f"{seg.idx:06d}_pause.wav"

        if not raw_wav.exists():
            print(f"Rendering {n}/{len(segments)}: {speaker}: {seg.text[:80]}")
            backend.synthesize(seg.text, assignment.voice, raw_wav, profile)

        if not processed_wav.exists():
            apply_audio_filter(raw_wav, processed_wav, prosody)

        wavs.append(processed_wav)

        pause_ms = prosody.pause_ms if prosody else args.pause_ms
        if pause_ms > 0:
            if not pause_wav.exists():
                write_silence(pause_wav, duration_ms=pause_ms)
            wavs.append(pause_wav)

    full_wav = args.out / "audiobook.wav"
    out_m4b = args.out / f"{safe_filename(args.epub.stem, 'audiobook')}.m4b"

    print("Concatenating WAVs...")
    concatenate_wavs(wavs, full_wav)

    print("Encoding M4B...")
    encode_m4b(full_wav, out_m4b)

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
