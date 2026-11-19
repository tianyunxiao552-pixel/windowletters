"""Choose group responses across mentions, self-quotes, pats, and smart proactive chat."""

from __future__ import annotations

import re

PROACTIVE_CHANCE = 0.27
PROACTIVE_INTERVAL_SECONDS = 300
PAT_COOLDOWN_SECONDS = 8.0
IMAGE_COOLDOWN_SECONDS = 15.0
QUOTE_SELF_BURST_LIMIT = 2
QUOTE_SELF_WINDOW_SECONDS = 90.0

_SEVERE_ABUSE_WORDS = (
    "臭婊子",
    "婊子",
    "几把套子",
    "去死",
    "去亖",
    "草泥马",
    "操你妈",
    "操你",
    "草你",
    "尼玛",
    "煞笔",
    "傻逼",
    "狗叫",
    "弱智",
    "脑残",
)

_HOSTILE_BAIT_WORDS = (
    *_SEVERE_ABUSE_WORDS,
    "傻b",
    "sb",
    "滚",
    "丨",
    "区区区",
    "略略略",
    "闭嘴",
    "废物",
)

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


def is_hostile_bait_text(text: str) -> bool:
    """Return True for profanity, abuse, single-char provocation, or pure trolling bait."""
    cleaned = text.strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if any(w in lower for w in _SEVERE_ABUSE_WORDS):
        return True
    if lower in {"丨", "滚", "sb", "略略略", "区区区"}:
        return True
    if len(cleaned) <= 16 and any(w in lower for w in _HOSTILE_BAIT_WORDS):
        return True
    return False


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
    recent_quote_count: int = 0,
    has_image: bool = False,
    since_last_image: float = float("inf"),
) -> str:
    if text and is_hostile_bait_text(text):
        return "ignore"
    if mentioned:
        return "mention"
    if quoted_self:
        if text and is_hostile_bait_text(text):
            return "ignore"
        if recent_quote_count >= QUOTE_SELF_BURST_LIMIT:
            return "ignore"
        return "quote_self"
    if patted_self:
        return "pat" if since_last_pat >= PAT_COOLDOWN_SECONDS else "ignore"
    if has_image:
        return "image" if since_last_image >= IMAGE_COOLDOWN_SECONDS else "ignore"
    if (
        has_plain_text
        and since_last >= PROACTIVE_INTERVAL_SECONDS
        and roll < PROACTIVE_CHANCE
        and (text is None or not is_low_signal_text(text))
    ):
        return "proactive"
    return "ignore"
