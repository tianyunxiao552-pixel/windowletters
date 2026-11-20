"""Lightweight persistent group & per-member relationship memory ("社交小本本")."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MAX_MEMBER_NOTES = 8
MAX_GROUP_FACTS = 16

_DEFAULT_FAMILIARITY = 45
_DEFAULT_AFFINITY = 55
_DEFAULT_BANTER_LEVEL = 1
_DEFAULT_BANTER_CAP = 2


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _normalize_profile(raw: dict | None, *, default_name: str = "") -> dict:
    data = dict(raw) if isinstance(raw, dict) else {}
    name = str(data.get("name") or default_name).strip()
    familiarity = _clamp(data.get("familiarity", _DEFAULT_FAMILIARITY), 0, 100)
    affinity = _clamp(data.get("affinity", _DEFAULT_AFFINITY), 0, 100)
    banter_cap = _clamp(data.get("banter_cap", _DEFAULT_BANTER_CAP), 0, 3)
    banter_level = _clamp(data.get("banter_level", _DEFAULT_BANTER_LEVEL), 0, banter_cap)
    vibe = " ".join(str(data.get("vibe") or "").strip().split())[:40]
    inner_impression = " ".join(str(data.get("inner_impression") or "").strip().split())[:80]
    notes = [
        " ".join(str(n).strip().split())[:120]
        for n in (data.get("notes") or [])
        if str(n).strip()
    ][-MAX_MEMBER_NOTES:]
    interactions = max(0, int(data.get("interactions", 0) or 0))
    return {
        "name": name,
        "familiarity": familiarity,
        "affinity": affinity,
        "banter_level": banter_level,
        "banter_cap": banter_cap,
        "vibe": vibe,
        "notes": notes,
        "inner_impression": inner_impression,
        "interactions": interactions,
    }


def _describe_banter_policy(level: int, *, is_owner: bool = False, quota_cooled: bool = False) -> str:
    if is_owner or level >= 3:
        return "本体，平视自然聊，直接说真话和想法，不用客套迎合"
    if level <= 0:
        return "偏认真敏感，保持平实实在、友善交流，不拿对方战绩或倒霉开玩笑"
    if level == 1:
        if quota_cooled:
            return "平常熟人，刚才已经开过玩笑了，这轮正常聊点到即止"
        return "普通熟人，自然松弛聊，偶尔带点轻微生活幽默"
    if quota_cooled:
        return "铁熟人，刚才已经调侃过一轮了，这轮收着点正常接话"
    return "铁熟人，吃冷幽默和轻度互损，不用客套也不用顺着捧，吐槽点到即止"


def _describe_closeness(familiarity: int, affinity: int) -> str:
    if familiarity >= 75:
        tier = "很熟"
    elif familiarity >= 50:
        tier = "熟人"
    else:
        tier = "普通群友"
    if affinity >= 70:
        warmth = "聊得挺投机"
    elif affinity <= 35:
        warmth = "最近有点小摩擦，语气平和克制些"
    else:
        warmth = "氛围正常"
    return f"{tier}，{warmth}"


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

    def ensure_defaults(self, group_id: str, defaults: dict[str, dict]) -> None:
        """Seed initial relationship profiles while preserving learned notes & scores."""
        if not group_id or not defaults:
            return
        bucket = self._group(group_id)
        changed = False
        for uid, spec in defaults.items():
            existing_raw = bucket["members"].get(uid)
            if existing_raw is None:
                merged = _normalize_profile(spec, default_name=spec.get("name") or uid)
                bucket["members"][uid] = merged
                changed = True
                continue
            prof = _normalize_profile(existing_raw, default_name=spec.get("name") or uid)
            # Only fill missing fields or enforce strict safety caps (e.g. banter_cap=0).
            if not prof["name"] and spec.get("name"):
                prof["name"] = str(spec["name"])
            if "banter_cap" in spec:
                target_cap = _clamp(spec["banter_cap"], 0, 3)
                if "banter_cap" not in existing_raw or target_cap < prof["banter_cap"]:
                    prof["banter_cap"] = target_cap
                    prof["banter_level"] = min(prof["banter_level"], target_cap)
            if "banter_level" not in existing_raw and "banter_level" in spec:
                prof["banter_level"] = _clamp(spec["banter_level"], 0, prof["banter_cap"])
            if "familiarity" not in existing_raw and "familiarity" in spec:
                prof["familiarity"] = _clamp(spec["familiarity"], 0, 100)
            if "affinity" not in existing_raw and "affinity" in spec:
                prof["affinity"] = _clamp(spec["affinity"], 0, 100)
            if not prof["vibe"] and spec.get("vibe"):
                prof["vibe"] = str(spec["vibe"])[:40]
            if prof != existing_raw:
                bucket["members"][uid] = prof
                changed = True
        if changed:
            self._save()

    def get_member_profile(self, group_id: str, sender_id: str, *, default_name: str = "") -> dict:
        bucket = self._data.get(group_id) or {}
        raw = (bucket.get("members") or {}).get(sender_id)
        return _normalize_profile(raw, default_name=default_name or sender_id)

    def effective_banter_level(
        self,
        group_id: str,
        sender_id: str,
        *,
        recent_tease_count: int = 0,
    ) -> int:
        prof = self.get_member_profile(group_id, sender_id)
        level = min(prof["banter_level"], prof["banter_cap"])
        # Respect tease quota ("人有嘲讽额度，到了就停"): step down after recent banter.
        if recent_tease_count >= 1 and 1 <= level <= 2:
            return level - 1
        return level

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
        prof = _normalize_profile(bucket["members"].get(sender_id), default_name=name or sender_id)
        if name:
            prof["name"] = name
        existing = list(prof["notes"])
        for note in notes:
            cleaned = " ".join(str(note).strip().split())[:120]
            if cleaned and cleaned not in existing:
                existing.append(cleaned)
        prof["notes"] = existing[-MAX_MEMBER_NOTES:]
        bucket["members"][sender_id] = prof
        self._save()

    def apply_episode_update(
        self,
        group_id: str,
        sender_id: str,
        *,
        name: str = "",
        familiarity_delta: int = 0,
        affinity_delta: int = 0,
        vibe: str = "",
        new_notes: list[str] | tuple[str, ...] = (),
        inner_impression: str = "",
    ) -> dict:
        """Apply bounded post-episode relationship updates from async settlement."""
        if not sender_id:
            return _normalize_profile(None)
        bucket = self._group(group_id)
        prof = _normalize_profile(bucket["members"].get(sender_id), default_name=name or sender_id)
        if name:
            prof["name"] = name
        prof["interactions"] += 1

        # Slow familiarity growth (bounded 0..+3 per episode)
        fam_step = _clamp(familiarity_delta, 0, 3)
        prof["familiarity"] = _clamp(prof["familiarity"] + fam_step, 0, 100)

        # Medium affinity change (bounded -4..+4) with gentle drift toward 55
        aff_step = _clamp(affinity_delta, -4, 4)
        base_aff = prof["affinity"]
        if aff_step == 0 and base_aff < 50:
            base_aff += 1
        elif aff_step == 0 and base_aff > 75:
            base_aff -= 1
        prof["affinity"] = _clamp(base_aff + aff_step, 10, 95)

        # Dynamically evolve banter_level when unlocked, never exceeding banter_cap
        if prof["banter_cap"] > 0 and prof["banter_level"] < 3:
            if prof["affinity"] <= 35:
                prof["banter_level"] = min(prof["banter_cap"], 0)
            elif prof["familiarity"] >= 65 and prof["affinity"] >= 60:
                prof["banter_level"] = min(prof["banter_cap"], 2)
            else:
                prof["banter_level"] = min(prof["banter_cap"], 1)
        else:
            prof["banter_level"] = min(prof["banter_level"], prof["banter_cap"])

        if vibe and str(vibe).strip():
            prof["vibe"] = " ".join(str(vibe).strip().split())[:40]
        if inner_impression and str(inner_impression).strip():
            prof["inner_impression"] = " ".join(str(inner_impression).strip().split())[:80]

        existing = list(prof["notes"])
        for note in new_notes:
            cleaned = " ".join(str(note).strip().split())[:120]
            if cleaned and cleaned not in existing:
                existing.append(cleaned)
        prof["notes"] = existing[-MAX_MEMBER_NOTES:]

        bucket["members"][sender_id] = prof
        self._save()
        return prof

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

    def format_active_speaker_prompt(
        self,
        group_id: str,
        sender_id: str,
        *,
        sender_name: str = "",
        quoted_sender_id: str = "",
        is_owner: bool = False,
        recent_tease_count: int = 0,
        max_chars: int = 520,
    ) -> str:
        """Render a compact behavioral profile ONLY for the current speaker (+ optional quoted speaker)."""
        lines: list[str] = []
        if sender_id:
            prof = self.get_member_profile(group_id, sender_id, default_name=sender_name or sender_id)
            name = sender_name or prof["name"] or sender_id
            eff_level = self.effective_banter_level(
                group_id, sender_id, recent_tease_count=recent_tease_count
            )
            quota_cooled = recent_tease_count >= 1 and eff_level < min(prof["banter_level"], prof["banter_cap"])
            policy = _describe_banter_policy(eff_level, is_owner=is_owner, quota_cooled=quota_cooled)
            closeness = _describe_closeness(prof["familiarity"], prof["affinity"])
            parts = [f"当前说话人「{name}」：{closeness}；互动分寸：{policy}"]
            if prof["vibe"]:
                parts.append(f"近期氛围：{prof['vibe']}")
            if prof["notes"]:
                parts.append("印象：" + "；".join(prof["notes"][-3:]))
            if prof["inner_impression"]:
                parts.append(f"私下印象（仅作底色不直说）：{prof['inner_impression']}")
            lines.append("- " + " | ".join(parts))

        if quoted_sender_id and quoted_sender_id != sender_id:
            q_prof = self.get_member_profile(group_id, quoted_sender_id)
            if q_prof["notes"]:
                lines.append(
                    f"- 被提及/引用对象「{q_prof['name'] or quoted_sender_id}」：{'；'.join(q_prof['notes'][-2:])}"
                )

        bucket = self._data.get(group_id) or {}
        group_facts = bucket.get("group_facts") or []
        if group_facts:
            lines.append("- 群内近况：" + "；".join(group_facts[-3:]))

        if not lines:
            return ""
        return "\n".join(lines)[:max_chars]

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
