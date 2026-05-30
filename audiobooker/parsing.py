from __future__ import annotations

import re
from pathlib import Path

from .constants import BAD_SPEAKER_NAMES, BAD_SPEAKER_WORDS
from .models import Segment
from .utils import clean_text


def is_valid_speaker_name(name: str) -> bool:
    if not name:
        return False

    n = " ".join(str(name).strip().split())
    low = n.lower()

    if not n:
        return False

    if low in BAD_SPEAKER_NAMES:
        return False

    if len(n) > 32:
        return False

    words = n.split()
    if len(words) > 3:
        return False

    if any(ch in n for ch in ".?!:;\"“”"):
        return False

    if any(w.strip(".,!?;:'\"()[]{}").lower() in BAD_SPEAKER_WORDS for w in words):
        return False

    if re.match(r"^(by|status|published|updated|words|chapters|rated)\b", low):
        return False

    alpha_words = [w for w in re.split(r"[\s\-]+", n) if any(c.isalpha() for c in w)]
    if not alpha_words:
        return False

    if not any(w[:1].isupper() for w in alpha_words):
        return False

    sentence_markers = {"the", "a", "an", "of", "to", "from", "with", "while", "almost", "each", "his", "her", "their"}
    if any(w.lower().strip(".,!?;:'\"()[]{}") in sentence_markers for w in words):
        return False

    return True


def filter_speaker_names(names):
    clean = []
    seen = set()
    for name in names or []:
        n = " ".join(str(name).strip().split())
        if is_valid_speaker_name(n) and n not in seen:
            clean.append(n)
            seen.add(n)
    return clean


def filter_segments_by_speaker(segments):
    for seg in segments or []:
        speaker = seg.get("speaker") if isinstance(seg, dict) else None
        if speaker and not is_valid_speaker_name(speaker):
            seg["speaker"] = "Narrator"
    return segments


def extract_epub_chapters(epub_path: Path) -> list[str]:
    try:
        import ebooklib
        import warnings
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
        from ebooklib import epub

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    except Exception as exc:
        raise SystemExit("Install dependencies first: pip install ebooklib beautifulsoup4 lxml") from exc

    book = epub.read_epub(str(epub_path))
    chapters: list[str] = []

    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        soup = BeautifulSoup(item.get_content(), "lxml")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()

        parts: list[str] = []
        for node in soup.find_all(["h1", "h2", "h3", "p", "blockquote", "li"]):
            txt = clean_text(node.get_text(" ", strip=True))
            if txt:
                parts.append(txt)

        text = "\n".join(parts).strip()
        if text:
            chapters.append(text)

    return chapters


def paragraph_to_segments(paragraph: str) -> list[tuple[str, str, str]]:
    paragraph = clean_text(paragraph)
    if not paragraph:
        return []

    match = re.match(r"^([A-Z][A-Za-z0-9 ._'’-]{1,40})\s*(?::|—|-)\s*(.+)$", paragraph)
    if match:
        speaker = clean_text(match.group(1))
        text = clean_text(match.group(2))
        if speaker and text and is_valid_speaker_name(speaker):
            return [("dialogue", speaker, text)]

    quote_matches = list(re.finditer(r'"([^"]{1,1000})"', paragraph))
    if not quote_matches:
        return [("narrator", "Narrator", paragraph)]

    result: list[tuple[str, str, str]] = []
    cursor = 0

    for quote_match in quote_matches:
        before = clean_text(paragraph[cursor:quote_match.start()])
        quote = clean_text(quote_match.group(1))

        if before:
            result.append(("narrator", "Narrator", before))
        if quote:
            result.append(("dialogue", "Unknown", quote))

        cursor = quote_match.end()

    after = clean_text(paragraph[cursor:])
    if after:
        result.append(("narrator", "Narrator", after))

    return result


def parse_chapters_to_segments(chapters: list[str]) -> list[Segment]:
    segments: list[Segment] = []
    idx = 0

    for chapter_idx, chapter in enumerate(chapters, 1):
        paragraphs = [p.strip() for p in chapter.split("\n") if p.strip()]

        for paragraph in paragraphs:
            for kind, speaker, text in paragraph_to_segments(paragraph):
                if not speaker:
                    speaker = "Narrator" if kind == "narrator" else "Unknown"

                segments.append(
                    Segment(
                        idx=idx,
                        chapter=chapter_idx,
                        kind=kind,
                        speaker=speaker,
                        text=text,
                    )
                )
                idx += 1

    return segments


def discover_speakers(segments: list[Segment]) -> list[str]:
    seen: dict[str, None] = {}
    for seg in segments:
        if seg.speaker:
            seen.setdefault(seg.speaker, None)

    speakers = list(seen.keys())
    if "Narrator" not in speakers:
        speakers.insert(0, "Narrator")

    return speakers
