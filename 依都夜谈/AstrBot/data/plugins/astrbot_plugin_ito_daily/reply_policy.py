"""Choose group responses across mentions, owner authority, self-quotes, pats, images, and smart proactive chat."""

from __future__ import annotations

import re

PROACTIVE_CHANCE = 0.14
PROACTIVE_INTERVAL_SECONDS = 300
PAT_COOLDOWN_SECONDS = 8.0
IMAGE_COOLDOWN_SECONDS = 90.0
IMAGE_REPLY_CHANCE = 0.45
QUOTE_SELF_BURST_LIMIT = 2
QUOTE_SELF_WINDOW_SECONDS = 90.0
BURST_MESSAGE_LIMIT = 5
FOLLOWUP_WINDOW_SECONDS = 45.0
FOLLOWUP_MAX_TURNS = 1
FOLLOWUP_MIN_CHARS = 4
GATE_SCAN_COOLDOWN_SECONDS = 45.0
GATE_MIN_NEW_MESSAGES = 2
GATE_MIN_SINGLE_CHARS = 16

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
    image_roll: float | None = None,
    recent_burst_count: int = 0,
    duplicate_recent_image: bool = False,
    is_owner: bool = False,
    is_recent_reply_target: bool = False,
    since_bot_replied_sender: float = float("inf"),
    followup_count: int = 0,
    is_quoting_other: bool = False,
    use_smart_gate: bool = False,
    since_last_gate_scan: float = float("inf"),
    new_msgs_since_scan: int = 0,
    proactive_interval: float = PROACTIVE_INTERVAL_SECONDS,
    gate_scan_cooldown: float = GATE_SCAN_COOLDOWN_SECONDS,
    image_cooldown: float = IMAGE_COOLDOWN_SECONDS,
    image_reply_chance: float = IMAGE_REPLY_CHANCE,
    followup_window: float = FOLLOWUP_WINDOW_SECONDS,
) -> str:
    # Owner explicit wake (@mention or quoting bot) bypasses hostile-bait & burst caps.
    if is_owner and mentioned:
        return "mention"
    if is_owner and quoted_self:
        return "quote_self"

    if text and is_hostile_bait_text(text):
        return "ignore"
    if mentioned:
        if duplicate_recent_image and not (text and text.strip() and text.strip() != "[图片]"):
            return "ignore"
        return "mention"
    if quoted_self:
        if recent_quote_count >= QUOTE_SELF_BURST_LIMIT:
            return "ignore"
        return "quote_self"
    if patted_self:
        return "pat" if since_last_pat >= PAT_COOLDOWN_SECONDS else "ignore"
    if (
        is_recent_reply_target
        and has_plain_text
        and not has_image
        and not is_quoting_other
        and followup_window > 0
        and since_bot_replied_sender <= followup_window
        and followup_count < FOLLOWUP_MAX_TURNS
        and (text is None or not is_low_signal_text(text))
        and (
            text is None
            or len(text.strip()) >= FOLLOWUP_MIN_CHARS
            or text.strip().endswith(("?", "？"))
        )
    ):
        return "followup"
    if has_image:
        if duplicate_recent_image:
            return "ignore"
        if recent_burst_count >= BURST_MESSAGE_LIMIT:
            return "ignore"
        chance_roll = roll if image_roll is None else image_roll
        if since_last_image >= image_cooldown and chance_roll < image_reply_chance:
            return "image"
        return "ignore"
    if not has_plain_text:
        return "ignore"
    if recent_burst_count >= BURST_MESSAGE_LIMIT:
        return "ignore"
    if text is not None and is_low_signal_text(text):
        return "ignore"
    if since_last < proactive_interval:
        return "ignore"
    if use_smart_gate:
        enough_signal = new_msgs_since_scan >= GATE_MIN_NEW_MESSAGES or (
            text is not None and len(text.strip()) >= GATE_MIN_SINGLE_CHARS
        )
        if since_last_gate_scan >= gate_scan_cooldown and enough_signal:
            return "gate_check"
        return "ignore"
    if roll < PROACTIVE_CHANCE:
        return "proactive"
    return "ignore"
