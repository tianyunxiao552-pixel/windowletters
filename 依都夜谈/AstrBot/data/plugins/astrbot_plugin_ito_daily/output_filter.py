"""Clean LLM output for natural WeChat chat delivery."""

from __future__ import annotations

import re

_SKIP_RE = re.compile(r"^\s*[\[【(（]?\s*SKIP\s*[\]】)）]?\s*$", re.I)
_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}\s+")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
_BULLET_RE = re.compile(r"(?m)^\s*[-*•]\s+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def is_skip_reply(text: str) -> bool:
    return bool(text and _SKIP_RE.match(text))


def clean_wechat_text(text: str, *, preserve_structure: bool = False) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").strip()
    cleaned = _HEADING_RE.sub("", cleaned)
    cleaned = _BOLD_RE.sub(r"\1", cleaned)
    cleaned = _ITALIC_RE.sub(r"\1", cleaned)
    cleaned = _INLINE_CODE_RE.sub(r"\1", cleaned)
    if not preserve_structure:
        cleaned = _BULLET_RE.sub("", cleaned)
    cleaned = _BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def split_natural_bubbles(text: str, *, max_bubbles: int = 3) -> list[str]:
    """Split multi-paragraph casual chat replies into 1-3 natural WeChat bubbles."""
    cleaned = text.strip()
    if not cleaned:
        return []
    # Keep structured multi-line blocks (e.g., daily summaries or step lists) as a single message.
    if any(marker in cleaned for marker in ("【", "▌", "✦")) or len(cleaned) > 220:
        return [cleaned]
    raw_parts = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    if len(raw_parts) == 1 and "\n" in raw_parts[0]:
        lines = [line.strip() for line in raw_parts[0].split("\n") if line.strip()]
        if 2 <= len(lines) <= max_bubbles:
            raw_parts = lines
    if len(raw_parts) <= 1:
        return raw_parts
    # Cap bubble count so we never spam the group.
    if len(raw_parts) > max_bubbles:
        head = raw_parts[: max_bubbles - 1]
        tail = "\n".join(raw_parts[max_bubbles - 1 :])
        raw_parts = [*head, tail]
    return raw_parts
