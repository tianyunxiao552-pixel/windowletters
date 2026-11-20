"""Hot-reloading numeric tuning panel & persistent owner directives (依都调参面板.json)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TUNING_DATA: dict = {
    "snark_level": 35,
    "warmth_level": 65,
    "humor_level": 65,
    "verbosity": 30,
    "meme_frequency": 50,
    "meme_cooldown_sec": 120,
    "proactive_threshold": 7,
    "proactive_cooldown_sec": 300,
    "gate_scan_cooldown_sec": 45,
    "image_reply_chance": 0.45,
    "image_cooldown_sec": 90,
    "followup_window_sec": 45,
    "tease_cooldown_sec": 600,
    "owner_directives": [],
}

# Friendly Chinese/English aliases for in-chat "@依都 调参 <别名> <数值>"
KNOB_ALIASES: dict[str, str] = {
    "snark": "snark_level",
    "snark_level": "snark_level",
    "冲": "snark_level",
    "冲度": "snark_level",
    "损人": "snark_level",
    "攻击性": "snark_level",
    "warmth": "warmth_level",
    "warmth_level": "warmth_level",
    "友善": "warmth_level",
    "温柔": "warmth_level",
    "共情": "warmth_level",
    "humor": "humor_level",
    "humor_level": "humor_level",
    "幽默": "humor_level",
    "玩梗": "humor_level",
    "乐子": "humor_level",
    "verbosity": "verbosity",
    "话长": "verbosity",
    "字数": "verbosity",
    "长度": "verbosity",
    "meme": "meme_frequency",
    "meme_frequency": "meme_frequency",
    "表情": "meme_frequency",
    "表情包": "meme_frequency",
    "meme_cooldown": "meme_cooldown_sec",
    "meme_cooldown_sec": "meme_cooldown_sec",
    "表情冷却": "meme_cooldown_sec",
    "表情包冷却": "meme_cooldown_sec",
    "threshold": "proactive_threshold",
    "proactive_threshold": "proactive_threshold",
    "门卫": "proactive_threshold",
    "门槛": "proactive_threshold",
    "冒泡门槛": "proactive_threshold",
    "proactive_cooldown": "proactive_cooldown_sec",
    "proactive_cooldown_sec": "proactive_cooldown_sec",
    "冒泡冷却": "proactive_cooldown_sec",
    "gate_scan": "gate_scan_cooldown_sec",
    "gate_scan_cooldown_sec": "gate_scan_cooldown_sec",
    "扫群间隔": "gate_scan_cooldown_sec",
    "image_chance": "image_reply_chance",
    "image_reply_chance": "image_reply_chance",
    "看图概率": "image_reply_chance",
    "image_cooldown": "image_cooldown_sec",
    "image_cooldown_sec": "image_cooldown_sec",
    "看图冷却": "image_cooldown_sec",
    "followup": "followup_window_sec",
    "followup_window_sec": "followup_window_sec",
    "追问": "followup_window_sec",
    "追问窗口": "followup_window_sec",
    "tease_cooldown": "tease_cooldown_sec",
    "tease_cooldown_sec": "tease_cooldown_sec",
    "嘲讽冷却": "tease_cooldown_sec",
}

_BOUNDS: dict[str, tuple[float, float, bool]] = {
    # key -> (min, max, is_float)
    "snark_level": (0, 100, False),
    "warmth_level": (0, 100, False),
    "humor_level": (0, 100, False),
    "verbosity": (0, 100, False),
    "meme_frequency": (0, 100, False),
    "meme_cooldown_sec": (0, 1800, False),
    "proactive_threshold": (1, 10, False),
    "proactive_cooldown_sec": (30, 3600, False),
    "gate_scan_cooldown_sec": (15, 600, False),
    "image_reply_chance": (0.0, 1.0, True),
    "image_cooldown_sec": (10, 1800, False),
    "followup_window_sec": (0, 180, False),
    "tease_cooldown_sec": (60, 3600, False),
}


def _clamp_knob(key: str, raw_value) -> int | float:
    lo, hi, is_float = _BOUNDS[key]
    val = float(raw_value)
    val = max(lo, min(hi, val))
    return round(val, 2) if is_float else int(round(val))


@dataclass(frozen=True)
class TuningSnapshot:
    snark_level: int = 35
    warmth_level: int = 65
    humor_level: int = 65
    verbosity: int = 30
    meme_frequency: int = 50
    meme_cooldown_sec: int = 120
    proactive_threshold: int = 7
    proactive_cooldown_sec: int = 300
    gate_scan_cooldown_sec: int = 45
    image_reply_chance: float = 0.45
    image_cooldown_sec: int = 90
    followup_window_sec: int = 45
    tease_cooldown_sec: int = 600
    owner_directives: tuple[str, ...] = field(default_factory=tuple)

    @property
    def max_bubbles(self) -> int:
        if self.verbosity <= 25:
            return 2
        return 3

    @property
    def witty_rag_multiplier(self) -> float:
        """Translate snark_level + humor_level into StyleRAG witty-sample weight multiplier."""
        if self.snark_level <= 20:
            return 0.75
        if self.snark_level <= 45:
            return 1.05 if self.humor_level >= 60 else 0.95
        if self.snark_level <= 70:
            return 1.22
        return 1.38

    def format_style_calibration(self) -> str:
        """Deterministically convert numeric dials into concise, well-calibrated behavioral cues."""
        cues: list[str] = []
        # Snark / edge axis
        if self.snark_level <= 20:
            cues.append("语气平和友善，不调侃、不损人")
        elif self.snark_level <= 45:
            cues.append("默认友善自然聊，别人晒成绩或求夸就大方夸；只有真冒出离谱梗或对方先开玩笑时才偶尔轻调侃一句，不无端带刺")
        elif self.snark_level <= 70:
            cues.append("允许明显的冷幽默和熟人轻度互损，但点到即止、不逮着同一个点连损")
        else:
            cues.append("乐子感偏高，犀利机智吐槽积极（仍遵守不带脏字和不伤人底线）")

        # Humor axis (decoupled from snark!)
        if self.humor_level >= 75:
            cues.append("很爱接梗和抖冷幽默包袱（善用两拍停顿和反转）")
        elif self.humor_level <= 30:
            cues.append("偏正经务实，少玩梗")

        # Warmth axis
        if self.warmth_level >= 75:
            cues.append("底色温暖善解人意，群友吐槽倒霉或累了多给实在安慰")
        elif self.warmth_level <= 30:
            cues.append("底色偏冷淡直给，少客套寒暄")

        # Verbosity axis
        if self.verbosity <= 35:
            cues.append("尽量简短利落，通常 1 句（最多 2 短句，10～35 字）说完就停")
        elif self.verbosity <= 70:
            cues.append("篇幅适中，1～3 短句自然说完")
        else:
            cues.append("聊得开时可以自然展开多说两句")

        return "；".join(cues) + "。"

    def format_meme_guidance(self) -> str:
        if self.meme_frequency <= 10:
            return "仅在群友明确让你发表情包时才使用 [MEME:名字]。"
        if self.meme_frequency <= 45:
            return "想缓和气氛、逗乐、调侃或群友让你发图时，偶尔可以顺手配一张 [MEME:名字]（不要连续发）。"
        if self.meme_frequency <= 75:
            return "想缓和气氛、逗乐、调侃、接梗、大笑或群友让你发图时，都很适合顺手配一张 [MEME:名字]（不要连续两轮都发）。"
        return "很爱斗图，缓和气氛、逗乐、调侃、吐槽时都可以顺手配一张 [MEME:名字]（单发图或配短句都行，不要连发）。"

    def format_summary_text(self) -> str:
        lines = [
            "当前依都调参面板：",
            f"冲/损人(snark)={self.snark_level}  友善(warmth)={self.warmth_level}  幽默(humor)={self.humor_level}",
            f"话长(verbosity)={self.verbosity}  表情包(meme)={self.meme_frequency}  表情冷却={self.meme_cooldown_sec}s",
            f"门卫门槛(threshold)={self.proactive_threshold}/10  冒泡冷却={self.proactive_cooldown_sec}s  扫群间隔={self.gate_scan_cooldown_sec}s",
            f"看图概率={self.image_reply_chance}  看图冷却={self.image_cooldown_sec}s  追问窗口={self.followup_window_sec}s  嘲讽冷却={self.tease_cooldown_sec}s",
        ]
        if self.owner_directives:
            lines.append("本体常驻指令：" + "；".join(self.owner_directives))
        return "\n".join(lines)


class TuningPanel:
    """File-backed hot-reloading panel with atomic writes."""

    def __init__(self, file_path: Path):
        self.path = Path(file_path)
        self._mtime_ns: int = 0
        self._raw: dict = dict(DEFAULT_TUNING_DATA)
        self._snapshot: TuningSnapshot = self._build_snapshot(self._raw)
        if not self.path.is_file():
            self._save()
        else:
            self._reload(force=True)

    @staticmethod
    def _build_snapshot(raw: dict) -> TuningSnapshot:
        directives = tuple(
            " ".join(str(x).strip().split())[:140]
            for x in (raw.get("owner_directives") or [])
            if str(x).strip()
        )[:10]
        kwargs: dict = {"owner_directives": directives}
        for key, default_val in DEFAULT_TUNING_DATA.items():
            if key == "owner_directives":
                continue
            try:
                kwargs[key] = _clamp_knob(key, raw.get(key, default_val))
            except (TypeError, ValueError):
                kwargs[key] = default_val
        return TuningSnapshot(**kwargs)

    def _reload(self, *, force: bool = False) -> None:
        if not self.path.is_file():
            return
        try:
            st = self.path.stat()
            if not force and st.st_mtime_ns == self._mtime_ns:
                return
            loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                merged = {**DEFAULT_TUNING_DATA, **loaded}
                self._raw = merged
                self._snapshot = self._build_snapshot(merged)
                self._mtime_ns = st.st_mtime_ns
        except (OSError, json.JSONDecodeError):
            pass

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
                json.dump(self._raw, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.close()
                os.replace(temp, self.path)
                try:
                    self._mtime_ns = self.path.stat().st_mtime_ns
                except OSError:
                    pass
            finally:
                temp.unlink(missing_ok=True)

    def current(self) -> TuningSnapshot:
        self._reload()
        return self._snapshot

    def set_knob(self, name_or_alias: str, raw_value: str | int | float) -> tuple[str, int | float]:
        self._reload()
        canonical = KNOB_ALIASES.get((name_or_alias or "").strip().lower())
        if not canonical:
            raise KeyError(name_or_alias)
        clamped = _clamp_knob(canonical, raw_value)
        self._raw[canonical] = clamped
        self._snapshot = self._build_snapshot(self._raw)
        self._save()
        return canonical, clamped

    def add_owner_directive(self, text: str) -> list[str]:
        self._reload()
        cleaned = " ".join((text or "").strip().split())[:140]
        if not cleaned:
            raise ValueError("指令内容不能为空")
        items = list(self._raw.get("owner_directives") or [])
        if cleaned not in items:
            items.append(cleaned)
        self._raw["owner_directives"] = items[-10:]
        self._snapshot = self._build_snapshot(self._raw)
        self._save()
        return list(self._raw["owner_directives"])

    def clear_owner_directives(self) -> None:
        self._reload()
        self._raw["owner_directives"] = []
        self._snapshot = self._build_snapshot(self._raw)
        self._save()
