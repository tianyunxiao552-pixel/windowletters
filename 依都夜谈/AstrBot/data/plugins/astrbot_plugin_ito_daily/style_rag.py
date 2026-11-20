"""Zero-dependency weighted, banter-routed style retriever over sanitized real chat corpus."""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from pathlib import Path

_SPAM_KEYWORDS = (
    "打电话给客服",
    "网络好慢",
    "傻逼傻逼",
    "蠢材",
    "草包",
    "话话话",
    "脑残",
    "低能",
    "智障",
)
# Only exclude hard profanity / abusive spam; preserve authentic witty group banter.
_AGGRESSIVE_KEYWORDS = (
    "傻逼",
    "我艹",
    "草泥马",
    "泥马",
    "废物",
    "脑残",
    "低能",
    "智障",
    "蠢材",
    "草包",
    "二弟",
    "狗叫",
    "野鸡",
    "畜生",
    "傻🐦",
    "笑成区",
    "够童",
    "招笑",
    "煞笔",
    "臭婊子",
    "去死",
    "去亖",
    "有攻击性",
)
_WITTY_MARKERS = (
    "🤣",
    "难绷",
    "何意味",
    "逆天",
    "绷不住",
    "离谱",
    "笑死",
    "sota",
    "gap",
    "战备",
    "虫豸",
    "鱼腩",
    "野人",
    "典中典",
    "经典",
    "神了",
    "乐死",
    "幽默",
    "卧龙",
    "抽象",
)
_META_NOISE_KEYWORDS = (
    "审查模型",
    "（审查",
    "(审查",
    "人机闭嘴",
    "外挂数据库",
    "系统提示词",
    "system prompt",
    "好感度",
    "人际模块",
    "停服维护",
    "引用才回",
    "不引用没用",
    "依旧没有引用",
    "后台",
    "token",
    "概率",
    "出来吐槽",
    "http://",
    "https://",
)
_PRIVACY_RE = re.compile(
    r"(?:\b\d{7,}\b|[A-Za-z]{2,}\d{5,}|身份证|银行卡|手机号|验证码|密码|收件地址|学住费|航财通)",
    re.I,
)
_WORD_RE = re.compile(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", re.I)


def _tokenize(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    lower = text.lower()
    for token in _WORD_RE.findall(lower):
        if token.isascii():
            counts[token] += 1
        else:
            if len(token) <= 4:
                counts[token] += 1
            for i in range(len(token) - 1):
                counts[token[i : i + 2]] += 1
    return counts


def _classify_tone(reply_text: str) -> str:
    lower = reply_text.lower()
    if any(m in lower for m in _WITTY_MARKERS):
        return "witty"
    return "chill"


def _is_safe_pair(user_text: str, reply_text: str) -> bool:
    combined = f"{user_text}\n{reply_text}"
    if not reply_text or len(reply_text) < 2 or len(reply_text) > 160:
        return False
    if any(k in combined for k in _SPAM_KEYWORDS):
        return False
    if any(k in reply_text for k in _AGGRESSIVE_KEYWORDS):
        return False
    if _PRIVACY_RE.search(combined):
        return False
    if reply_text in {"[图片]", "[动画表情]", "[语音]", "[文件]"}:
        return False
    return True


def is_clean_live_owner_utterance(text: str) -> bool:
    """Return True if an owner group message is clean, non-private, and suitable for live style learning."""
    cleaned = " ".join((text or "").strip().split())
    if not (6 <= len(cleaned) <= 100):
        return False
    lower = cleaned.lower()
    if any(k in lower for k in _META_NOISE_KEYWORDS):
        return False
    if any(k in cleaned for k in _SPAM_KEYWORDS) or any(k in cleaned for k in _AGGRESSIVE_KEYWORDS):
        return False
    if _PRIVACY_RE.search(cleaned):
        return False
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return False
    return True


def _compact_user_context(user_text: str) -> str:
    lines = [ln.strip() for ln in user_text.splitlines() if ln.strip() and ln.strip() != "（没有选取前文）"]
    tail = lines[-2:] if lines else []
    joined = " / ".join(tail)
    return joined[:120]


class StyleCorpusRetriever:
    def __init__(self, sources: list[Path | tuple[Path, float]] | tuple[Path | tuple[Path, float], ...] = ()):
        # Each item: (compact_user, reply_text, weight, tone)
        self._pairs: list[tuple[str, str, float, str]] = []
        self._docs: list[Counter[str]] = []
        self._df: Counter[str] = Counter()
        self._idf: dict[str, float] = {}
        self._seen_keys: set[str] = set()
        self._load(sources)

    @property
    def size(self) -> int:
        return len(self._pairs)

    def _rebuild_idf(self) -> None:
        total = max(len(self._docs), 1)
        self._idf = {term: math.log((total + 1) / (freq + 1)) + 1.0 for term, freq in self._df.items()}

    def _add_entry(self, compact_u: str, reply_text: str, weight: float) -> bool:
        dedup_key = f"{compact_u}||{reply_text}"
        if dedup_key in self._seen_keys:
            return False
        self._seen_keys.add(dedup_key)
        tone = _classify_tone(reply_text)
        self._pairs.append((compact_u, reply_text, weight, tone))
        toks = _tokenize(f"{compact_u} {reply_text}")
        self._docs.append(toks)
        for term in toks:
            self._df[term] += 1
        return True

    def _load(self, sources) -> None:
        for entry in sources:
            if isinstance(entry, tuple):
                p, weight = Path(entry[0]), float(entry[1])
            else:
                p, weight = Path(entry), 1.0
            if not p.is_file() or weight <= 0:
                continue
            try:
                raw_lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line in raw_lines:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msgs = obj.get("messages")
                if not isinstance(msgs, list):
                    continue
                user_text = next(
                    (m.get("content", "") for m in msgs if isinstance(m, dict) and m.get("role") == "user"),
                    "",
                ).strip()
                reply_text = next(
                    (m.get("content", "") for m in msgs if isinstance(m, dict) and m.get("role") == "assistant"),
                    "",
                ).strip()
                if not _is_safe_pair(user_text, reply_text):
                    continue
                self._add_entry(_compact_user_context(user_text), reply_text, weight)
        self._rebuild_idf()

    def learn_live_sample(
        self,
        live_path: Path,
        *,
        user_context: str,
        owner_text: str,
        weight: float = 1.15,
    ) -> bool:
        """Persist and hot-index a new clean utterance from the real owner."""
        cleaned_reply = " ".join((owner_text or "").strip().split())
        if not is_clean_live_owner_utterance(cleaned_reply):
            return False
        compact_u = _compact_user_context(user_context or "")
        if not _is_safe_pair(compact_u, cleaned_reply):
            return False
        added = self._add_entry(compact_u, cleaned_reply, weight)
        if not added:
            return False
        self._rebuild_idf()
        record = {
            "messages": [
                {"role": "user", "content": compact_u or "（群聊发言）"},
                {"role": "assistant", "content": cleaned_reply},
            ]
        }
        try:
            live_path.parent.mkdir(parents=True, exist_ok=True)
            with live_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return True

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 3,
        banter_level: int = 1,
        witty_multiplier: float = 1.25,
    ) -> list[tuple[str, str]]:
        if not self._pairs or not query.strip():
            return []
        q_toks = _tokenize(query)
        if not q_toks:
            return []
        scored: list[tuple[float, int]] = []
        for idx, doc in enumerate(self._docs):
            _, reply, weight, tone = self._pairs[idx]
            if banter_level <= 0 and tone == "witty":
                continue
            score = 0.0
            for term, q_cnt in q_toks.items():
                if term in doc:
                    score += self._idf.get(term, 1.0) * min(q_cnt, 2) * (1.0 + math.log(doc[term]))
            if score > 0:
                score *= weight
                if 4 <= len(reply) <= 45:
                    score *= 1.12
                if banter_level >= 2 and tone == "witty":
                    score *= witty_multiplier
                elif banter_level <= 0 and tone == "chill":
                    score *= 1.15
                scored.append((score, idx))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked: list[tuple[str, str]] = []
        seen_text: set[str] = set()
        for _, idx in scored:
            u, a, _, _ = self._pairs[idx]
            if a in seen_text:
                continue
            seen_text.add(a)
            picked.append((u, a))
            if len(picked) >= limit:
                break
        if len(picked) < limit:
            anchors = [
                (u, a)
                for u, a, w, tone in self._pairs
                if w >= 0.75
                and 6 <= len(a) <= 48
                and a not in seen_text
                and "http" not in a
                and (banter_level > 0 or tone == "chill")
            ]
            if anchors:
                start = sum(ord(c) for c in query) % len(anchors)
                step = max(len(anchors) // max(limit, 1), 1)
                idx = start
                tried = 0
                while len(picked) < limit and tried < len(anchors):
                    u, a = anchors[idx % len(anchors)]
                    if a not in seen_text:
                        seen_text.add(a)
                        picked.append((u, a))
                    idx += step
                    tried += 1
        return picked

    def format_for_prompt(
        self,
        query: str,
        *,
        limit: int = 3,
        banter_level: int = 1,
        witty_multiplier: float = 1.25,
    ) -> str:
        hits = self.retrieve(
            query,
            limit=limit,
            banter_level=banter_level,
            witty_multiplier=witty_multiplier,
        )
        if not hits:
            return ""
        lines = []
        for u, a in hits:
            a_inline = a.replace("\n", " / ")
            if u:
                lines.append(f"- 前文「{u}」 -> 本人实录：「{a_inline}」")
            else:
                lines.append(f"- 本人实录：「{a_inline}」")
        return "\n".join(lines)


def discover_default_corpus(
    root_dir: Path | None = None,
    *,
    live_corpus_path: Path | None = None,
) -> list[tuple[Path, float]]:
    """Load configured labeled corpora and optional live owner utterances."""
    sources: list[tuple[Path, float]] = []
    if live_corpus_path is not None and live_corpus_path.is_file():
        sources.append((live_corpus_path, 1.15))

    if root_dir is None:
        configured = os.environ.get("ITO_STYLE_CORPUS_DIR", "").strip()
        if not configured:
            return sources
        root_dir = Path(configured).expanduser()
    if root_dir.is_dir():
        labeled = {*root_dir.glob("*.jsonl"), *root_dir.glob("*/训练数据.jsonl")}
        sources.extend(
            (path, 1.0) for path in sorted(labeled)
            if path.is_file() and path != live_corpus_path
        )
    return sources
