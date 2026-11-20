"""Clean LLM output for natural WeChat chat delivery."""

from __future__ import annotations

import re

_SKIP_RE = re.compile(r"(?:^|\s)[\[【(（]?\s*SKIP\s*[\]】)）]?(?:\s|[。！!.])*$", re.I)
_EXPLICIT_SKIP_TOKEN_RE = re.compile(r"[\[【]\s*SKIP\s*[\]】]", re.I)
_LEAKED_THOUGHT_RE = re.compile(
    r"(?:完全触发了规则|触发了规则[:：]|直接输出\s*\[?SKIP|不附带任何解释|按照(?:人设|系统提示|规则)|因此我应该(?:保持安静|跳过|输出))",
    re.I,
)
_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}\s+")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
_BULLET_RE = re.compile(r"(?m)^\s*[-*•]\s+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
# Trim Gemini 3.8's repetitive Chinese internet-slang crutches ("属于是" / declarative "是吧") at line ends.
_SHUYUSHI_TAIL_RE = re.compile(r"(?:[，,\s]*)属于是(?=[。！!？?~\s\n]|$)")
_SHIBA_CRUTCH_RE = re.compile(r"(?<![不就还也才算])(?:[，,\s]*)是吧(?=[。！!~\s\n]|$)")


def is_skip_reply(text: str) -> bool:
    """Return True if the model intended to skip or leaked internal rule-checking thoughts."""
    if not text:
        return False
    return bool(
        _SKIP_RE.match(text)
        or _EXPLICIT_SKIP_TOKEN_RE.search(text)
        or _LEAKED_THOUGHT_RE.search(text)
    )


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
        if len(cleaned) > 5:
            cleaned = _SHUYUSHI_TAIL_RE.sub("", cleaned)
            cleaned = _SHIBA_CRUTCH_RE.sub("", cleaned)
    cleaned = _BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def split_natural_bubbles(text: str, *, max_bubbles: int = 2) -> list[str]:
    """Split multi-line casual chat replies into at most max_bubbles WeChat bubbles without leaking extra newlines."""
    cleaned = text.strip()
    if not cleaned:
        return []
    # Keep structured multi-line blocks (e.g., daily summaries or long requested analyses) as a single message.
    if any(marker in cleaned for marker in ("【", "▌", "✦")) or len(cleaned) > 220:
        return [cleaned]
    raw_parts = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    if len(raw_parts) == 1 and "\n" in raw_parts[0]:
        raw_parts = [line.strip() for line in raw_parts[0].split("\n") if line.strip()]
    # Flatten any internal single newlines inside parts so segmented_reply regex [^\n]+ never re-splits beyond max_bubbles.
    flat_parts = ["  ".join(ln.strip() for ln in p.splitlines() if ln.strip()) for p in raw_parts]
    flat_parts = [p for p in flat_parts if p]
    if len(flat_parts) <= 1:
        return flat_parts
    if len(flat_parts) > max_bubbles:
        head = flat_parts[: max_bubbles - 1]
        tail = "  ".join(flat_parts[max_bubbles - 1 :])
        return [*head, tail]
    return flat_parts
