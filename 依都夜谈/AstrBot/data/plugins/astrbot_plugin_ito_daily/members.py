"""Cached group-member nickname resolution via WeChat Native API."""

from __future__ import annotations

import time


def pick_display_name(item: dict) -> str:
    for key in ("roomDisplayName", "displayName", "nickname", "alias", "username", "id"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return " ".join(val.strip().split())[:64]
    return ""


class MemberDirectory:
    def __init__(self, *, ttl_seconds: float = 600.0):
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, dict[str, str]] = {}
        self._fetched_at: dict[str, float] = {}

    def peek(self, group_id: str, sender_id: str) -> str | None:
        return self._cache.get(group_id, {}).get(sender_id)

    def all_cached(self, group_id: str) -> dict[str, str]:
        return dict(self._cache.get(group_id, {}))

    async def refresh(self, group_id: str, client) -> dict[str, str]:
        if client is None or getattr(client, "closed", False):
            return self.all_cached(group_id)
        mapping: dict[str, str] = {}
        cursor = ""
        seen_cursors: set[str] = set()
        try:
            for _ in range(20):
                page = await client.group_members(group_id, limit=100, cursor=cursor)
                items = page.get("items") if isinstance(page, dict) else None
                if not isinstance(items, list):
                    break
                for item in items:
                    if not isinstance(item, dict) or item.get("deleted") is True:
                        continue
                    name = pick_display_name(item)
                    if not name:
                        continue
                    for id_key in ("username", "id"):
                        uid = item.get(id_key)
                        if isinstance(uid, str) and uid.strip():
                            mapping[uid.strip()] = name
                next_cursor = page.get("nextCursor") if isinstance(page, dict) else None
                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        except Exception:
            return self.all_cached(group_id)
        if mapping:
            self._cache[group_id] = mapping
            self._fetched_at[group_id] = time.monotonic()
        return self.all_cached(group_id)

    async def resolve(self, group_id: str, sender_id: str, client=None) -> str:
        if not sender_id:
            return "群友"
        now = time.monotonic()
        stale = (now - self._fetched_at.get(group_id, float("-inf"))) >= self.ttl_seconds
        if stale or (group_id not in self._cache):
            await self.refresh(group_id, client)
        return self._cache.get(group_id, {}).get(sender_id) or sender_id

    async def resolve_map(self, group_id: str, client=None) -> dict[str, str]:
        now = time.monotonic()
        stale = (now - self._fetched_at.get(group_id, float("-inf"))) >= self.ttl_seconds
        if stale or (group_id not in self._cache):
            await self.refresh(group_id, client)
        return self.all_cached(group_id)
