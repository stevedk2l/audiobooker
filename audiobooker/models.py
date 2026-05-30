from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class Segment:
    idx: int
    chapter: int
    kind: str
    speaker: str
    text: str


@dataclasses.dataclass
class CharacterProfile:
    name: str
    gender: str = "neutral"
    age: str = "adult"
    role: str = "character"
    voice_style: str = "natural"
    dialect: str = "neutral_british_irish"
    personality: list[str] = dataclasses.field(default_factory=list)
    delivery: str = "natural"
    pitch: str = "medium"
    voice_direction: str = "natural British or Irish audiobook character voice"


@dataclasses.dataclass
class CharacterCast:
    name: str
    gender: str = "neutral"
    age: str = "adult"
    role: str = "character"
    social_register: str = "unknown"
    accent_region: str = "neutral_british_irish"
    accent_confidence: float = 0.0
    accent_basis: str = "unknown"
    reason: str = ""
    voice_style: str = "natural"
    personality: list[str] = dataclasses.field(default_factory=list)
    voice_direction: str = "natural British or Irish audiobook character voice"


@dataclasses.dataclass
class VoiceAssignment:
    speaker: str
    voice: str
    description: str = ""
    reference_audio: str = ""
    voice_direction: str = ""


@dataclasses.dataclass
class ProsodySettings:
    speaker: str
    pitch_semitones: float = 0.0
    tempo: float = 1.0
    volume_db: float = 0.0
    pause_ms: int = 220
    description: str = ""
