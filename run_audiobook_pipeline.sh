#!/usr/bin/env bash
set -euo pipefail

# Full lifecycle audiobook pipeline:
# 1. Prepare venv and compatible dependency pins
# 2. Check Ollama / optionally pull model
# 3. Build metadata, speaker attribution, cast map, profiles, voice map
# 4. Generate Kokoro reference voices for XTTS/Fish
# 5. Rebuild voice map with references
# 6. Optionally preview voices
# 7. Render final audiobook

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

EPUB="${EPUB:-}"
OUT_DIR="${OUT_DIR:-audiobook_out}"

BACKEND="${BACKEND:-xtts}"
REFERENCE_GENERATOR="${REFERENCE_GENERATOR:-kokoro}"

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:32b}"
OLLAMA_FAST_MODEL="${OLLAMA_FAST_MODEL:-qwen3:14b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"

LLM_TIMEOUT="${LLM_TIMEOUT:-180}"
LLM_RETRIES="${LLM_RETRIES:-2}"
LLM_BATCH_SIZE="${LLM_BATCH_SIZE:-24}"
MAX_LLM_DIALOGUE="${MAX_LLM_DIALOGUE:-0}"

PREVIEW_VOICES="${PREVIEW_VOICES:-0}"
RESET="${RESET:-0}"
FORCE="${FORCE:-0}"
SKIP_LLM="${SKIP_LLM:-0}"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"

log() {
  echo
  echo "[$(date '+%H:%M:%S')] ==> $*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  ./run_audiobook_pipeline.sh book.epub

Common overrides:
  BACKEND=xtts ./run_audiobook_pipeline.sh book.epub
  BACKEND=kokoro ./run_audiobook_pipeline.sh book.epub
  OLLAMA_MODEL=qwen3:14b ./run_audiobook_pipeline.sh book.epub
  OLLAMA_MODEL=qwen3:32b ./run_audiobook_pipeline.sh book.epub
  SKIP_LLM=1 ./run_audiobook_pipeline.sh book.epub
  RESET=1 ./run_audiobook_pipeline.sh book.epub
  PREVIEW_VOICES=1 ./run_audiobook_pipeline.sh book.epub

Environment:
  EPUB                  EPUB path, optional if passed as first argument
  OUT_DIR               Output directory, default audiobook_out
  BACKEND               kokoro | xtts | fish, default xtts
  OLLAMA_MODEL          Main local LLM model, default qwen3:32b
  OLLAMA_FAST_MODEL     Fallback faster local LLM, default qwen3:14b
  LLM_TIMEOUT           Per-call timeout seconds, default 180
  LLM_RETRIES           Retries per LLM call, default 2
  LLM_BATCH_SIZE        Speaker attribution batch size, default 24
  MAX_LLM_DIALOGUE      Maximum dialogue lines to send through LLM, default 800
  SKIP_LLM              1 disables LLM passes
  RESET                 1 clears generated metadata/caches in OUT_DIR
  FORCE                 1 forces profile/voice regeneration
  PREVIEW_VOICES        1 generates previews before final render
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "$EPUB" && $# -gt 0 ]]; then
  EPUB="$1"
fi

[[ -n "$EPUB" ]] || die "No EPUB supplied. Run: ./run_audiobook_pipeline.sh book.epub"
[[ -f "$EPUB" ]] || die "EPUB not found: $EPUB"
[[ -f "ebook_audiobook_converter.py" ]] || die "Missing ebook_audiobook_converter.py in $PROJECT_DIR"

log "Checking system commands"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN not found. Install Python 3.11."
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg not found. Install with: brew install ffmpeg"

if [[ "$SKIP_LLM" != "1" ]]; then
  command -v ollama >/dev/null 2>&1 || die "ollama not found. Install Ollama or run with SKIP_LLM=1."
fi

log "Preparing Python virtual environment"

if [[ ! -d ".venv" ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip wheel "setuptools<82"

python -m pip install \
  ebooklib \
  beautifulsoup4 \
  lxml \
  soundfile \
  "numpy<2" \
  kokoro \
  TTS

log "Pinning compatible ML/TTS dependency versions"

# These pins avoid:
# - Coqui XTTS BeamSearchScorer import failure from transformers 5.x
# - gruut / TTS breakage from numpy 2.x
# - torch setuptools<82 warning
python -m pip install --upgrade --force-reinstall \
  "numpy<2" \
  "transformers==4.41.2" \
  "tokenizers==0.19.1" \
  "huggingface-hub==0.23.5" \
  "setuptools<82"

python - <<'PY'
import numpy
from transformers import BeamSearchScorer
print("Dependency check OK")
print("numpy:", numpy.__version__)
print("BeamSearchScorer import OK:", BeamSearchScorer.__name__)
PY

if [[ "$SKIP_LLM" != "1" ]]; then
  log "Checking Ollama"

  if ! curl -fsS "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    echo "Ollama server does not appear to be running."
    echo "Starting Ollama in background..."
    ollama serve >/tmp/audiobooker_ollama.log 2>&1 &
    sleep 5
  fi

  if ! curl -fsS "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    die "Ollama is not responding at ${OLLAMA_HOST}. Start it manually or use SKIP_LLM=1."
  fi

  echo "Pulling/checking main model: $OLLAMA_MODEL"
  ollama pull "$OLLAMA_MODEL"

  echo "Pulling/checking fallback fast model: $OLLAMA_FAST_MODEL"
  ollama pull "$OLLAMA_FAST_MODEL"
fi

mkdir -p "$OUT_DIR"

if [[ "$RESET" == "1" ]]; then
  log "Resetting generated metadata and caches"
  rm -f "$OUT_DIR/segments.json"
  rm -f "$OUT_DIR/voice_map.json"
  rm -f "$OUT_DIR/prosody_map.json"
  rm -f "$OUT_DIR/character_profiles.json"
  rm -f "$OUT_DIR/character_cast.json"
  rm -f "$OUT_DIR/speaker_attribution_cache.json"
  rm -rf "$OUT_DIR/reference_voices"
  rm -rf "$OUT_DIR/previews"
  rm -rf "$OUT_DIR/parts"
fi

log "Ensuring helper: Kokoro reference voice generator"

mkdir -p tools

cat > tools/generate_kokoro_reference_voices.py <<'PY'
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
PY

chmod +x tools/generate_kokoro_reference_voices.py

BASE_ARGS=(
  "$EPUB"
  --out "$OUT_DIR"
  --backend "$BACKEND"
  --reference-voice-dir "$OUT_DIR/reference_voices"
  --auto-voice-profiles
  --use-prosody
)

LLM_ARGS=()
if [[ "$SKIP_LLM" != "1" ]]; then
  LLM_ARGS+=(
    --llm-cast-pass
    --llm-speaker-pass
    --ollama-model "$OLLAMA_MODEL"
    --ollama-host "$OLLAMA_HOST"
    --llm-timeout "$LLM_TIMEOUT"
    --llm-retries "$LLM_RETRIES"
    --llm-batch-size "$LLM_BATCH_SIZE"
    --max-llm-dialogue "$MAX_LLM_DIALOGUE"
  )
fi

FORCE_ARGS=()
if [[ "$FORCE" == "1" || "$RESET" == "1" ]]; then
  FORCE_ARGS+=(
    --force-cast
    --force-character-profiles
    --force-voice-map
    --force-prosody-map
    --force-reference-voices
  )
fi

log "Stage 1: build metadata, speaker attribution, cast map, profiles, and provisional voice map"

set +e
python ebook_audiobook_converter.py \
  "${BASE_ARGS[@]}" \
  "${LLM_ARGS[@]}" \
  "${FORCE_ARGS[@]}" \
  --parse-only
stage1_status=$?
set -e

if [[ $stage1_status -ne 0 && "$SKIP_LLM" != "1" ]]; then
  echo
  echo "Stage 1 failed with main model. Retrying with faster fallback model: $OLLAMA_FAST_MODEL"

  python ebook_audiobook_converter.py \
    "${BASE_ARGS[@]}" \
    --llm-cast-pass \
    --llm-speaker-pass \
    --ollama-model "$OLLAMA_FAST_MODEL" \
    --ollama-host "$OLLAMA_HOST" \
    --llm-timeout "$LLM_TIMEOUT" \
    --llm-retries "$LLM_RETRIES" \
    --llm-batch-size "$LLM_BATCH_SIZE" \
    --max-llm-dialogue "$MAX_LLM_DIALOGUE" \
    "${FORCE_ARGS[@]}" \
    --parse-only
elif [[ $stage1_status -ne 0 ]]; then
  die "Stage 1 failed."
fi

VOICE_MAP="$OUT_DIR/voice_map.json"

[[ -f "$VOICE_MAP" ]] || die "Voice map was not created: $VOICE_MAP"

log "Stage 2: generate Kokoro reference voices for XTTS/Fish"

if [[ "$BACKEND" == "xtts" || "$BACKEND" == "fish" ]]; then
  mkdir -p "$OUT_DIR/reference_voices"

  REF_FORCE_ARG=()
  if [[ "$FORCE" == "1" || "$RESET" == "1" ]]; then
    REF_FORCE_ARG+=(--force)
  fi

  python tools/generate_kokoro_reference_voices.py \
    --voice-map "$VOICE_MAP" \
    --out-dir "$OUT_DIR/reference_voices" \
    "${REF_FORCE_ARG[@]}"
else
  echo "Skipping reference generation for backend=$BACKEND"
fi

log "Stage 3: rebuild voice map to pick up generated references"

python ebook_audiobook_converter.py \
  "${BASE_ARGS[@]}" \
  --parse-only

if [[ "$PREVIEW_VOICES" == "1" ]]; then
  log "Stage 4: generate voice previews"

  python ebook_audiobook_converter.py \
    "${BASE_ARGS[@]}" \
    --preview-voices
else
  log "Stage 4: skipping voice previews"
fi

log "Stage 5: render final audiobook"

python ebook_audiobook_converter.py \
  "${BASE_ARGS[@]}"

log "Done"

echo "Output directory: $OUT_DIR"
find "$OUT_DIR" -maxdepth 2 \( -name "*.m4b" -o -name "*.mp3" -o -name "*.wav" \) | sed 's#^#  #'
