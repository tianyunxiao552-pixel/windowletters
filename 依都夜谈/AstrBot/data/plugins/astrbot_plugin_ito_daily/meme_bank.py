"""Manage reaction images in the local meme folder."""

from __future__ import annotations

import random
import re
from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
_CLEAN_RE = re.compile(r"[\s_\-\(\)（）\[\]【】《》]+")
_MEME_TAG_RE = re.compile(r"[\[【]\s*MEME\s*[:：]\s*([^\]】\n]{1,40})\s*[\]】]", re.I)
_EXPLICIT_MEME_RE = re.compile(
    r"(?:表情包|发表情|发个表情|来个表情|来张表情|配个表情|发张图|来张图|发个图|配张图|斗图|回个表情|贴张图)",
    re.I,
)


def is_explicit_meme_request(text: str) -> bool:
    """Return True when the user explicitly asks the bot to send a meme/reaction image."""
    return bool(_EXPLICIT_MEME_RE.search(text or ""))


def can_auto_send_meme(
    *,
    last_reply_had_meme: bool,
    last_meme_ts: float,
    now_mono: float,
    cooldown_sec: float,
) -> bool:
    """Prevent back-to-back meme spam while keeping broad autonomous usage."""
    if last_reply_had_meme:
        return False
    if cooldown_sec > 0 and (now_mono - last_meme_ts) < cooldown_sec:
        return False
    return True


def extract_meme_tags(text: str) -> tuple[str, list[str]]:
    """Extract [MEME:name] tags from LLM output and return (remaining_text, meme_names)."""
    if not text:
        return "", []
    names = [m.group(1).strip() for m in _MEME_TAG_RE.finditer(text) if m.group(1).strip()]
    cleaned = _MEME_TAG_RE.sub("", text).strip()
    return cleaned, names


def _norm(text: str) -> str:
    return _CLEAN_RE.sub("", (text or "").strip().lower())


class LocalMemeBank:
    """Dynamically reads image/GIF memes from a local folder (no restart needed when adding files)."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def ensure_folder(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        return self.folder

    def list_memes(self) -> list[tuple[str, Path]]:
        if not self.folder.is_dir():
            return []
        items: list[tuple[str, Path]] = []
        for p in sorted(self.folder.iterdir()):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and p.stat().st_size > 0:
                items.append((p.stem, p))
        return items

    def names(self) -> list[str]:
        return [name for name, _ in self.list_memes()]

    def format_catalog_hint(self, *, max_items: int = 24, guidance: str = "") -> str:
        all_names = self.names()
        if not all_names:
            return ""
        shown = all_names[:max_items]
        extra = f" 等共{len(all_names)}张" if len(all_names) > max_items else ""
        sample = shown[0]
        extra_rule = guidance or "群友叫你发表情包，或聊天很适合配图时，可以顺手配一张。"
        return (
            f"你本地表情包库现有：{'、'.join(shown)}{extra}。"
            f"{extra_rule}"
            f"发图方式：直接在回复里写 [MEME:{sample}]（把名字换成上面列表里最贴切的一张），程序会自动替换成真图发出；"
            "只想单发表情包就只写这一个标签，想配话就在标签前后加一句简短文字，只写库里实际存在的名字。"
        )

    def save_from_bytes(self, name: str, data: bytes) -> Path:
        """Save raw image/GIF bytes into the local meme folder with magic-byte extension detection."""
        clean_name = re.sub(r'[\\/:*?"<>|\r\n]+', "", (name or "").strip())[:32]
        if not clean_name:
            raise ValueError("表情包名字不能为空")
        if not data:
            raise ValueError("图片内容为空")
        if data[:6] in (b"GIF87a", b"GIF89a"):
            ext = ".gif"
        elif data[:8] == b"\x89PNG\r\n\x1a\n":
            ext = ".png"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            ext = ".webp"
        else:
            ext = ".jpg"
        self.ensure_folder()
        target = self.folder / f"{clean_name}{ext}"
        target.write_bytes(data)
        return target

    def match(self, query: str = "") -> tuple[str, Path] | None:
        items = self.list_memes()
        if not items:
            return None
        q_raw = (query or "").strip()
        q = _norm(q_raw)
        if not q or q in {"随机", "随便", "任意", "表情包", "表情", "图", "来一张"}:
            return random.choice(items)

        # 1. Exact stem match
        for name, path in items:
            if _norm(name) == q:
                return name, path

        # 2. Substring match (either direction)
        sub_hits = [
            (name, path)
            for name, path in items
            if q in _norm(name) or _norm(name) in q
        ]
        if sub_hits:
            # Prefer closest length match
            sub_hits.sort(key=lambda item: abs(len(_norm(item[0])) - len(q)))
            return sub_hits[0]

        # 3. Character overlap fuzzy match
        q_chars = set(q)
        scored: list[tuple[float, str, Path]] = []
        for name, path in items:
            n = _norm(name)
            if not n:
                continue
            overlap = len(q_chars & set(n))
            if overlap > 0:
                score = overlap / max(len(q_chars), 1) + overlap / max(len(set(n)), 1)
                scored.append((score, name, path))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            if scored[0][0] >= 0.45:
                return scored[0][1], scored[0][2]

        return None
