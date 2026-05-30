from __future__ import annotations

import argparse
import dataclasses
import os
import time
from datetime import datetime
from pathlib import Path

from .backends import FISH_API_WRAPPER, default_fish_command, generate_reference_voices
from .casting import (
    apply_cast_identification,
    fallback_cast_for_speaker,
    identify_cast_with_llm,
    infer_character_cast_with_llm,
    infer_character_profiles,
    overrides_from_character_cast,
    refine_speakers_with_llm,
)
from .models import CharacterCast, Segment
from .parsing import discover_speakers, extract_epub_chapters, parse_chapters_to_segments
from .rendering import preview_voices, render_audiobook
from .speaker_cleanup import (
    collect_known_cast_names,
    filter_segments_to_real_speakers,
    filter_voice_map_to_real_speakers,
    filtered_speaker_list,
)
from .utils import load_character_overrides, write_json
from .voices import load_or_create_prosody_map, load_or_create_voice_map, write_reference_voice_manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("epub", type=Path, nargs="?")
    parser.add_argument("--out", type=Path, default=Path("audiobook_out"))
    parser.add_argument("--backend", choices=["kokoro", "xtts", "fish"], default="kokoro")
    parser.add_argument("--kokoro-accent", choices=["british", "american", "mixed"], default="british")
    parser.add_argument("--reference-voice-dir", type=Path, default=None)
    parser.add_argument("--fish-command", default=None)
    parser.add_argument("--write-fish-wrapper", type=Path, default=None)
    parser.add_argument("--auto-generate-reference-voices", action="store_true")
    parser.add_argument("--generate-reference-voices-with", choices=["kokoro", "fish"], default="kokoro")
    parser.add_argument("--force-reference-voices", action="store_true")
    parser.add_argument("--pause-ms", type=int, default=220)
    parser.add_argument("--parse-only", action="store_true")
    parser.add_argument("--llm-speaker-pass", action="store_true")
    parser.add_argument("--ollama-model", default="qwen3:32b")
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    parser.add_argument("--llm-timeout", type=int, default=None)
    parser.add_argument("--llm-retries", type=int, default=None)
    parser.add_argument("--max-llm-dialogue", type=int, default=1200)
    parser.add_argument("--llm-batch-size", type=int, default=20)
    parser.add_argument("--auto-voice-profiles", action="store_true")
    parser.add_argument("--llm-cast-pass", action="store_true")
    parser.add_argument("--force-cast", action="store_true")
    parser.add_argument("--force-character-profiles", action="store_true")
    parser.add_argument("--force-voice-map", action="store_true")
    parser.add_argument("--force-prosody-map", action="store_true")
    parser.add_argument("--use-prosody", action="store_true")
    parser.add_argument("--preview-voices", action="store_true")
    parser.add_argument("--character-overrides", type=Path, default=None)
    return parser


def apply_runtime_configuration(args: argparse.Namespace) -> None:
    if args.llm_timeout is not None:
        os.environ["OLLAMA_TIMEOUT"] = str(args.llm_timeout)
    if args.llm_retries is not None:
        os.environ["OLLAMA_RETRIES"] = str(args.llm_retries)
    if args.backend == "fish" and not args.fish_command:
        args.fish_command = default_fish_command(Path(__file__))


def load_or_build_segments(args: argparse.Namespace, chapters: list[str], segments_path: Path) -> list[Segment]:
    if segments_path.exists() and not args.force_cast and not args.force_character_profiles:
        try:
            return [Segment(**item) for item in __import__("json").loads(segments_path.read_text())]
        except Exception:
            return parse_chapters_to_segments(chapters)
    return parse_chapters_to_segments(chapters)


def build_casts(
    all_segments: list[Segment],
    args: argparse.Namespace,
    character_overrides: dict,
) -> tuple[dict[str, CharacterCast], dict]:
    speakers = discover_speakers(all_segments)
    if args.llm_cast_pass:
        casts = infer_character_cast_with_llm(
            all_segments,
            args.ollama_model,
            args.ollama_host,
            args.out / "character_cast.json",
            force=args.force_cast,
            overrides=character_overrides,
        )
        cast_overrides = overrides_from_character_cast(casts)
        merged = dict(cast_overrides)
        merged.update(character_overrides)
        character_overrides = merged
        write_json(args.out / "character_overrides.auto.json", character_overrides)
    else:
        casts = {speaker: fallback_cast_for_speaker(speaker, character_overrides) for speaker in speakers}

    return casts, character_overrides


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    apply_runtime_configuration(args)

    if args.write_fish_wrapper:
        args.write_fish_wrapper.write_text(FISH_API_WRAPPER)
        args.write_fish_wrapper.chmod(0o755)
        print(f"Wrote Fish wrapper: {args.write_fish_wrapper}")
        return 0

    if not args.epub:
        parser.error("epub is required unless --write-fish-wrapper is used")

    if not args.epub.exists():
        raise SystemExit(f"EPUB not found: {args.epub}")

    args.out.mkdir(parents=True, exist_ok=True)
    character_overrides = load_character_overrides(args.character_overrides)

    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S")

    pipeline_t0 = time.monotonic()
    print(f"[{_ts()}] Extracting EPUB chapters...")
    chapters = extract_epub_chapters(args.epub)
    print(f"[{_ts()}] Found {len(chapters)} chapters.")

    segments_path = args.out / "segments.json"
    llm_segments_path = args.out / "segments.llm.json"
    all_segments = load_or_build_segments(args, chapters, segments_path)
    print(f"[{_ts()}] Loaded {len(all_segments)} segments")

    if args.llm_speaker_pass or args.llm_cast_pass:
        print(f"[{_ts()}] Warming up Ollama model ({args.ollama_model})...")
        t0 = time.monotonic()
        try:
            from .llm import ollama_chat
            ollama_chat(args.ollama_model, "You are a test.", "Reply OK.", args.ollama_host)
            print(f"[{_ts()}] Model loaded in {time.monotonic() - t0:.1f}s")
        except Exception as exc:
            print(f"[{_ts()}] Warmup failed ({exc}), continuing anyway...")

    if args.llm_speaker_pass:
        print(f"[{_ts()}] Starting LLM speaker attribution...")
        t0 = time.monotonic()
        all_segments = refine_speakers_with_llm(
            all_segments,
            args.ollama_model,
            args.ollama_host,
            llm_segments_path,
            args.llm_batch_size,
            force=args.force_cast,
            max_dialogue=args.max_llm_dialogue,
        )
        print(f"[{_ts()}] LLM speaker attribution done in {time.monotonic() - t0:.1f}s")

    write_json(segments_path, [dataclasses.asdict(seg) for seg in all_segments])

    # --- LLM cast identification: filter garbage & merge aliases ---
    if args.llm_cast_pass:
        print(f"[{_ts()}] Starting LLM cast identification...")
        t0 = time.monotonic()
        cast_id_map = identify_cast_with_llm(
            all_segments,
            args.ollama_model,
            args.ollama_host,
            args.out / "cast_identification.json",
            force=args.force_cast,
        )
        all_segments = apply_cast_identification(all_segments, cast_id_map)
        write_json(segments_path, [dataclasses.asdict(seg) for seg in all_segments])
        print(f"[{_ts()}] LLM cast identification done in {time.monotonic() - t0:.1f}s")

    print(f"[{_ts()}] Building casts...")
    casts, character_overrides = build_casts(all_segments, args, character_overrides)

    # --- Speaker cleanup: filter remaining garbage BEFORE building voice maps ---
    known_cast_names = collect_known_cast_names(casts=casts.values(), character_overrides=character_overrides)
    all_segments_dicts = [dataclasses.asdict(seg) for seg in all_segments]
    all_segments_dicts = filter_segments_to_real_speakers(all_segments_dicts, known_cast_names)
    all_segments = [Segment(**item) for item in all_segments_dicts]
    speakers = filtered_speaker_list(all_segments_dicts, known_cast_names)
    write_json(segments_path, all_segments_dicts)

    print(f"[{_ts()}] Discovered speakers ({len(speakers)}): {', '.join(speakers)}")

    print(f"[{_ts()}] Inferring character profiles...")
    profiles = infer_character_profiles(
        speakers,
        casts,
        args.out / "character_profiles.json",
        force=args.force_character_profiles,
        overrides=character_overrides,
    )

    print(f"[{_ts()}] Building voice maps...")
    reference_dir = args.reference_voice_dir or (args.out / "reference_voices")
    write_reference_voice_manifest(args.out / "reference_voice_manifest.json", speakers, profiles, reference_dir)

    provisional_voice_map = load_or_create_voice_map(
        args.out / "voice_map.provisional_kokoro.json",
        speakers,
        profiles,
        force=args.force_voice_map,
        accent=args.kokoro_accent,
        backend="kokoro",
        reference_dir=reference_dir,
        overrides=character_overrides,
    )

    print(f"[{_ts()}] Provisional voice map ready")

    if args.auto_generate_reference_voices:
        print(f"[{_ts()}] Generating reference voices...")
        t0 = time.monotonic()
        generate_reference_voices(
            speakers=speakers,
            profiles=profiles,
            voice_map=provisional_voice_map,
            reference_dir=reference_dir,
            method=args.generate_reference_voices_with,
            force=args.force_reference_voices,
            fish_command=args.fish_command or "",
        )
        print(f"[{_ts()}] Reference voices done in {time.monotonic() - t0:.1f}s")

    voice_map = load_or_create_voice_map(
        args.out / "voice_map.json",
        speakers,
        profiles,
        force=args.force_voice_map or args.auto_generate_reference_voices,
        accent=args.kokoro_accent,
        backend=args.backend,
        reference_dir=reference_dir,
        overrides=character_overrides,
    )

    # Safety: filter voice map to only contain real speakers
    voice_map = filter_voice_map_to_real_speakers(voice_map, all_segments_dicts, known_cast_names)
    write_json(args.out / "voice_map.json", {k: dataclasses.asdict(v) if hasattr(v, '__dataclass_fields__') else v for k, v in voice_map.items()})

    prosody_map = load_or_create_prosody_map(
        args.out / "prosody_map.json",
        speakers,
        profiles,
        force=args.force_prosody_map,
    )

    print(f"[{_ts()}] Voice map: {args.out / 'voice_map.json'}")
    print(f"[{_ts()}] Segments manifest: {segments_path}")

    if args.preview_voices:
        print(f"[{_ts()}] Generating voice previews...")
        preview_voices(speakers, profiles, voice_map, prosody_map, args)

    if args.parse_only:
        print(f"[{_ts()}] Parse-only mode — done in {time.monotonic() - pipeline_t0:.1f}s")
        return 0

    print(f"[{_ts()}] Starting audio render...")
    t0 = time.monotonic()
    out_m4b = render_audiobook(all_segments, profiles, voice_map, prosody_map, args)
    print(f"[{_ts()}] Render done in {time.monotonic() - t0:.1f}s")
    print(f"[{_ts()}] Complete: {out_m4b} (total pipeline: {time.monotonic() - pipeline_t0:.1f}s)")
    return 0
