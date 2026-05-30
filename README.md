# Audiobooker

Convert EPUB books into multi-voice audiobooks with AI-powered speaker attribution and text-to-speech synthesis.

## Features

- **EPUB parsing** with automatic chapter extraction and dialogue segmentation
- **LLM speaker attribution** using local Ollama models — sends full chapter context for accurate dialogue identification
- **LLM cast identification** — filters garbage speaker names, merges aliases (e.g. "Squall Leonhart" → "Squall")
- **Character profiling** — infers gender, age, accent region, voice style, and personality for each character
- **Multi-backend TTS**:
  - **Kokoro** — fast local TTS with British/American accent pools
  - **XTTS** (Coqui TTS) — voice cloning with regional accent variation
  - **Fish Speech** — HTTP API-based TTS with reference voice cloning
- **Reference voice generation** — automatically generates seed voices per character using Kokoro
- **Audio rendering** — concatenates chapter audio with silence gaps, encodes to M4B with metadata

## Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) running locally (for speaker attribution and cast inference)
- One or more TTS backends installed

### Installation

```bash
# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# The pipeline script handles dependency installation automatically
```

### Usage

The simplest way to run the full pipeline:

```bash
./run_audiobook_pipeline.sh book.epub
```

Or use the Python CLI directly:

```bash
python3 -m audiobooker book.epub \
  --backend xtts \
  --llm-speaker-pass \
  --llm-cast-pass \
  --auto-generate-reference-voices \
  --preview-voices
```

### Common Overrides

```bash
# Use Kokoro backend (fastest, no voice cloning)
BACKEND=kokoro ./run_audiobook_pipeline.sh book.epub

# Use XTTS backend (best for regional accents)
BACKEND=xtts ./run_audiobook_pipeline.sh book.epub

# Use a specific Ollama model
OLLAMA_MODEL=qwen3:32b ./run_audiobook_pipeline.sh book.epub

# Skip LLM passes (use regex-only speaker detection)
SKIP_LLM=1 ./run_audiobook_pipeline.sh book.epub

# Force regeneration of all cached outputs
FORCE=1 ./run_audiobook_pipeline.sh book.epub

# Preview voices before full render
PREVIEW_VOICES=1 ./run_audiobook_pipeline.sh book.epub
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `BACKEND` | `xtts` | TTS backend: `kokoro`, `xtts`, or `fish` |
| `OLLAMA_MODEL` | `qwen3:32b` | Main Ollama model for speaker attribution |
| `OLLAMA_FAST_MODEL` | `qwen3:14b` | Fallback faster model |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `LLM_TIMEOUT` | `180` | Per-call timeout in seconds |
| `LLM_RETRIES` | `2` | Retries per failed LLM call |
| `SKIP_LLM` | `0` | Set to `1` to disable LLM passes |
| `FORCE` | `0` | Set to `1` to regenerate all cached outputs |
| `PREVIEW_VOICES` | `0` | Set to `1` to generate voice previews |
| `RESET` | `0` | Set to `1` to clear output directory |

## Architecture

```
audiobooker/
  cli.py              # Main entry point and pipeline orchestration
  models.py            # Data models (Segment, CharacterProfile, VoiceAssignment, etc.)
  constants.py         # Voice pools, accent regions, speaker validation sets
  parsing.py           # EPUB extraction, paragraph segmentation, speaker discovery
  speaker_cleanup.py   # Speaker name normalisation and filtering
  llm.py               # Ollama HTTP client with retry/timeout logic
  casting.py           # LLM speaker attribution, cast identification, profile inference
  voices.py            # Voice mapping, Kokoro voice pools, prosody settings
  backends.py          # TTS backend implementations (Kokoro, XTTS, Fish)
  rendering.py         # Audio rendering pipeline, silence, concat, M4B encoding
  __main__.py          # python3 -m audiobooker support
```

### Pipeline Stages

1. **Parse** — Extract chapters from EPUB, segment into narrator/dialogue
2. **LLM Speaker Attribution** — Send full chapter text to LLM for dialogue speaker identification
3. **LLM Cast Identification** — Filter garbage names, merge aliases, identify real characters
4. **Cast Inference** — Build character profiles with gender, accent, voice style
5. **Voice Mapping** — Assign TTS voices from accent-appropriate pools
6. **Reference Voice Generation** — Generate Kokoro seed voices per character
7. **Render** — Synthesise audio per segment, concatenate chapters, encode M4B

## License

Private project.
