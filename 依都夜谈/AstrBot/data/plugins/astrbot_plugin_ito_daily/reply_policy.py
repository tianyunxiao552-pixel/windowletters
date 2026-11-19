"""Choose group responses across mentions, self-quotes, pats, and smart proactive chat."""

from __future__ import annotations

import re

PROACTIVE_CHANCE = 0.27
PROACTIVE_INTERVAL_SECONDS = 300
PAT_COOLDOWN_SECONDS = 8.0

_NOISE_WORDS = frozenset(
    {
        "1",
        "2",
        "?",
        "？",
        "额",
        "呃",
        "嗯",
        "哦",
        "噢",
        "啊",
        "哈",
        "草",
        "ok",
        "okay",
        "kk",
        "好的",
        "好",
        "行",
        "收到",
        "6",
        "66",
        "666",
    }
)
_PUNCT_OR_SPACE_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
_REPEATED_FILLER_RE = re.compile(r"^[额呃嗯哦噢啊哈?？!！.。~～…]+$")


def is_low_signal_text(text: str) -> bool:
    """Return True for ultra-short filler or punctuation that makes bad proactive hooks."""
    cleaned = text.strip()
    if not cleaned:
        return True
    if _PUNCT_OR_SPACE_RE.match(cleaned):
        return True
    if _REPEATED_FILLER_RE.match(cleaned):
        return True
    lower = cleaned.lower()
    if lower in _NOISE_WORDS:
        return True
    return len(cleaned) <= 1


def select_reply(
    mentioned: bool,
    has_plain_text: bool,
    roll: float,
    since_last: float,
    *,
    quoted_self: bool = False,
    patted_self: bool = False,
    since_last_pat: float = float("inf"),
    text: str | None = None,
) -> str:
    if mentioned:
        return "mention"
    if quoted_self:
        return "quote_self"
    if patted_self:
        return "pat" if since_last_pat >= PAT_COOLDOWN_SECONDS else "ignore"
    if (
        has_plain_text
        and since_last >= PROACTIVE_INTERVAL_SECONDS
        and roll < PROACTIVE_CHANCE
        and (text is None or not is_low_signal_text(text))
    ):
        return "proactive"
    return "ignore"
