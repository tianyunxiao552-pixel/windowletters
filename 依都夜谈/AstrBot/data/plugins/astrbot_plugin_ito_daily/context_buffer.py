"""Bounded sliding group-chat context buffer to eliminate context gaps."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8), "北京时间")


@dataclass(frozen=True)
class ChatEntry:
    message_id: str
    sender_id: str
    sender_name: str
    text: str
    ts: float
    is_bot: bool = False
    quote_text: str = ""
    server_id: str = ""


class GroupContextBuffer:
    def __init__(self, *, max_items: int = 36, max_age_seconds: float = 2700.0):
        self.max_items = max_items
        self.max_age_seconds = max_age_seconds
        self._groups: dict[str, deque[ChatEntry]] = {}
        self._seen_ids: dict[str, deque[str]] = {}

    def record(
        self,
        group_id: str,
        *,
        message_id: str,
        sender_id: str,
        sender_name: str,
        text: str,
        ts: float | None = None,
        is_bot: bool = False,
        quote_text: str = "",
        server_id: str = "",
    ) -> None:
        cleaned = " ".join(text.strip().split())
        if not cleaned and not quote_text:
            return
        seen = self._seen_ids.setdefault(group_id, deque(maxlen=self.max_items * 2))
        if message_id and message_id in seen:
            return
        if message_id:
            seen.append(message_id)
        entries = self._groups.setdefault(group_id, deque(maxlen=self.max_items))
        entries.append(
            ChatEntry(
                message_id=message_id,
                sender_id=sender_id,
                sender_name=sender_name or sender_id or "群友",
                text=cleaned[:500],
                ts=time.time() if ts is None else ts,
                is_bot=is_bot,
                quote_text=" ".join(quote_text.strip().split())[:140] if quote_text else "",
                server_id=server_id or "",
            )
        )

    def recent(self, group_id: str, *, limit: int = 24, now: float | None = None) -> list[ChatEntry]:
        entries = self._groups.get(group_id)
        if not entries:
            return []
        ref = time.time() if now is None else now
        cutoff = ref - self.max_age_seconds
        fresh = [e for e in entries if e.ts >= cutoff]
        return fresh[-limit:]

    def format_context(
        self,
        group_id: str,
        *,
        limit: int = 22,
        now: float | None = None,
        exclude_message_id: str | None = None,
        max_chars: int = 2400,
    ) -> str:
        items = [
            e
            for e in self.recent(group_id, limit=limit + 1, now=now)
            if not exclude_message_id or e.message_id != exclude_message_id
        ][-limit:]
        if not items:
            return ""
        lines: list[str] = []
        total = 0
        for entry in reversed(items):
            hhmm = datetime.fromtimestamp(entry.ts, tz=BEIJING).strftime("%H:%M")
            speaker = "依都(你)" if entry.is_bot else entry.sender_name
            quote_part = f" [引用:{entry.quote_text[:60]}]" if entry.quote_text else ""
            line = f"[{hhmm}] {speaker}{quote_part}: {entry.text}"
            if lines and total + len(line) + 1 > max_chars:
                break
            lines.append(line)
            total += len(line) + 1
        lines.reverse()
        return "\n".join(lines)

    def active_sender_ids(self, group_id: str, *, limit: int = 12, now: float | None = None) -> tuple[str, ...]:
        ids: list[str] = []
        for entry in reversed(self.recent(group_id, limit=limit, now=now)):
            if not entry.is_bot and entry.sender_id and entry.sender_id not in ids:
                ids.append(entry.sender_id)
        return tuple(ids)

    def was_bot_message(self, group_id: str, *, server_id: str = "", text: str = "") -> bool:
        entries = self._groups.get(group_id)
        if not entries:
            return False
        norm_text = " ".join(text.strip().split()) if text else ""
        for entry in reversed(entries):
            if not entry.is_bot:
                continue
            if server_id and entry.server_id and entry.server_id == server_id:
                return True
            if norm_text and entry.text and (norm_text == entry.text or norm_text in entry.text or entry.text in norm_text):
                return True
        return False
