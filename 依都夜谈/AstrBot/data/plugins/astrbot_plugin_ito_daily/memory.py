"""Lightweight persistent group & member memory for warm continuity."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MAX_MEMBER_NOTES = 8
MAX_GROUP_FACTS = 16


class GroupMemoryStore:
    def __init__(self, file_path: Path):
        self.path = Path(file_path)
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            delete=False,
        ) as stream:
            temp = Path(stream.name)
            try:
                json.dump(self._data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.close()
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)

    def _group(self, group_id: str) -> dict:
        bucket = self._data.setdefault(group_id, {"members": {}, "group_facts": []})
        bucket.setdefault("members", {})
        bucket.setdefault("group_facts", [])
        return bucket

    def remember_member(
        self,
        group_id: str,
        sender_id: str,
        *,
        name: str = "",
        notes: list[str] | tuple[str, ...] = (),
    ) -> None:
        if not sender_id:
            return
        bucket = self._group(group_id)
        profile = bucket["members"].setdefault(sender_id, {"name": name or sender_id, "notes": []})
        if name:
            profile["name"] = name
        existing = list(profile.get("notes", []))
        for note in notes:
            cleaned = " ".join(str(note).strip().split())[:120]
            if cleaned and cleaned not in existing:
                existing.append(cleaned)
        profile["notes"] = existing[-MAX_MEMBER_NOTES:]
        self._save()

    def remember_group_fact(self, group_id: str, fact: str) -> None:
        cleaned = " ".join(str(fact).strip().split())[:160]
        if not cleaned:
            return
        bucket = self._group(group_id)
        facts = list(bucket.get("group_facts", []))
        if cleaned not in facts:
            facts.append(cleaned)
        bucket["group_facts"] = facts[-MAX_GROUP_FACTS:]
        self._save()

    def format_for_prompt(
        self,
        group_id: str,
        *,
        active_sender_ids: tuple[str, ...] = (),
        max_chars: int = 900,
    ) -> str:
        bucket = self._data.get(group_id)
        if not bucket:
            return ""
        lines: list[str] = []
        members = bucket.get("members", {})
        for uid in active_sender_ids:
            profile = members.get(uid)
            if not profile:
                continue
            notes = profile.get("notes") or []
            if notes:
                name = profile.get("name") or uid
                lines.append(f"- {name}：{'；'.join(notes[-4:])}")
        group_facts = bucket.get("group_facts") or []
        if group_facts:
            lines.append("- 群里近况/共同梗：" + "；".join(group_facts[-5:]))
        if not lines:
            return ""
        text = "\n".join(lines)
        return text[:max_chars]
