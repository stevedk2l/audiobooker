#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

import soundfile as sf

SAFE_RE = re.compile(r"[^A-Za-z0-9._ -]+")

def safe_name(name: str) -> str:
    name = SAFE_RE.sub("_", name).strip().replace(" ", "_")
    return name or "Unknown"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice-map", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    voice_map_path = Path(args.voice_map)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with voice_map_path.open("r", encoding="utf-8") as f:
        voice_map = json.load(f)

    try:
        from kokoro import KPipeline
    except Exception as exc:
        raise SystemExit(f"Could not import Kokoro. Install with: pip install kokoro. Error: {exc}")

    pipeline = KPipeline(lang_code="b")

    import time
    from datetime import datetime
    total_voices = len([k for k, v in voice_map.items() if isinstance(v, dict)])
    generated = 0

    for speaker, info in sorted(voice_map.items()):
        if not isinstance(info, dict):
            continue

        voice = info.get("voice") or "bm_george"
        direction = info.get("voice_direction") or info.get("description") or "natural British audiobook voice"

        ref_path = out_dir / f"{safe_name(speaker)}.wav"
        if ref_path.exists() and not args.force:
            print(f"exists: {speaker}: {ref_path}")
            continue

        sample_text = (
            f"{direction}. "
            "I remember the shape of the room, the weight of the silence, "
            "and the words I chose not to say."
        )

        generated += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] generating reference {generated}/{total_voices}: {speaker}: {voice} -> {ref_path}")
        t0 = time.monotonic()

        chunks = []
        for _, _, audio in pipeline(sample_text, voice=voice, speed=1.0):
            chunks.append(audio)

        if not chunks:
            print(f"[{ts}] warning: no audio generated for {speaker}")
            continue

        import numpy as np
        wav = np.concatenate(chunks)
        sf.write(str(ref_path), wav, 24000)
        elapsed = time.monotonic() - t0
        ts2 = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts2}] done {speaker} in {elapsed:.1f}s")

        info["reference_audio"] = str(ref_path)

    with voice_map_path.open("w", encoding="utf-8") as f:
        json.dump(voice_map, f, indent=2, ensure_ascii=False)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
