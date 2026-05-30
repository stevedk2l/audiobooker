BAD_SPEAKER_NAMES = {
    "by", "status", "published", "updated", "words", "chapters", "rated",
    "original source", "source", "unknown", "space", "re", "point",
    "chapter", "author", "summary", "notes", "category", "language",
    "complete", "incomplete", "rating", "favorites", "follows", "reviews",
}

BAD_SPEAKER_WORDS = {
    "was", "were", "had", "has", "have", "looked", "stared", "glanced",
    "switched", "absorbed", "activated", "remained", "feared", "sprang",
    "said", "asked", "answered", "replied", "turned", "walked", "moved",
    "stood", "sat", "felt", "thought", "knew", "saw", "heard", "made",
    "cut", "remained", "accelerating", "intercept", "result",
}

KOKORO_BRITISH_FEMALE_VOICES = ["bf_alice", "bf_emma", "bf_isabella", "bf_lily"]
KOKORO_BRITISH_MALE_VOICES = ["bm_daniel", "bm_fable", "bm_george", "bm_lewis"]
KOKORO_BRITISH_NEUTRAL_VOICES = [
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]

KOKORO_AMERICAN_FEMALE_VOICES = ["af_heart", "af_nicole", "af_bella", "af_sarah"]
KOKORO_AMERICAN_MALE_VOICES = ["am_adam", "am_michael"]
KOKORO_AMERICAN_NEUTRAL_VOICES = [
    "af_heart", "af_nicole", "af_bella", "af_sarah",
    "am_adam", "am_michael",
]

ACCENT_REGIONS = [
    "english_rp",
    "english_northern",
    "english_west_country",
    "scottish_lowland",
    "scottish_highland",
    "welsh",
    "irish",
    "northern_irish",
    "neutral_british_irish",
    "non_native_british_irish",
    "unknown",
]

ACCENT_REGION_DIRECTIONS = {
    "english_rp": "English RP, clear, composed, precise",
    "english_northern": "northern English, grounded, direct, not posh",
    "english_west_country": "west country English, warm, informal, earthy",
    "scottish_lowland": "lowland Scottish, clear, dry, restrained",
    "scottish_highland": "highland Scottish, warmer, more lyrical, characterful",
    "welsh": "Welsh, musical, warm, grounded",
    "irish": "Irish, warm, lyrical, emotionally natural",
    "northern_irish": "Northern Irish, quick, bright, direct",
    "neutral_british_irish": "neutral British and Irish audiobook style",
    "non_native_british_irish": "non-native English speaker using clear British/Irish audiobook pronunciation",
    "unknown": "neutral British and Irish audiobook style",
}

KNOWN_MALE_HINTS = {
    "squall", "zell", "seifer", "laguna", "irvine", "kiros", "ward", "cid",
    "wedge", "biggs", "president", "duke", "sir", "mr", "father", "dad",
}
KNOWN_FEMALE_HINTS = {
    "rinoa", "selphie", "quistis", "edea", "ellone", "raine", "julia",
    "mrs", "miss", "mother", "mom", "mum",
}

METADATA_SPEAKERS = {
    "by",
    "status",
    "published",
    "updated",
    "words",
    "chapters",
    "rated",
    "original source",
    "source",
    "author",
    "title",
    "summary",
    "language",
    "category",
    "fandom",
    "relationship",
    "characters",
    "additional tags",
    "series",
    "notes",
}

BAD_SPEAKER_STARTS = (
    "the ",
    "a ",
    "an ",
    "his ",
    "her ",
    "their ",
    "while ",
    "well ",
    "each ",
    "almost ",
    "accelerating ",
    "setting ",
    "flanked ",
    "resistance ",
    "tendrils ",
    "weather ",
    "humanity ",
    "space ",
    "turn ",
    "point ",
    "or ",
    "in ",
    "re ",
    "dear ",
)

GENERIC_BAD_SPEAKERS = {
    "space",
    "point",
    "check",
    "result",
    "military",
    "lab",
    "words",
    "chapters",
    "rated",
    "published",
    "updated",
    "status",
    "by",
    "source",
    "original source",
}
