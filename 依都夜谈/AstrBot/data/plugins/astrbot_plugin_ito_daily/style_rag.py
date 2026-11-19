"""Zero-dependency weighted, anti-aggression style retriever over sanitized real chat corpus."""

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
    "闹麻",
    "够童",
    "招笑",
    "煞笔",
    "臭婊子",
    "去死",
    "去亖",
    "有攻击性",
)
_PRIVACY_RE = re.compile(
    r"(?:\b\d{7,}\b|[A-Za-z]{2,}\d{5,}|身份证|银行卡|手机号|验证码|密码|收件地址|学住费|航财通|xwt\d+)",
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


def _compact_user_context(user_text: str) -> str:
    lines = [ln.strip() for ln in user_text.splitlines() if ln.strip() and ln.strip() != "（没有选取前文）"]
    tail = lines[-2:] if lines else []
    joined = " / ".join(tail)
    return joined[:120]


class StyleCorpusRetriever:
    def __init__(self, sources: list[Path | tuple[Path, float]] | tuple[Path | tuple[Path, float], ...] = ()):
        self._pairs: list[tuple[str, str, float]] = []
        self._docs: list[Counter[str]] = []
        self._idf: dict[str, float] = {}
        self._load(sources)

    @property
    def size(self) -> int:
        return len(self._pairs)

    def _load(self, sources) -> None:
        seen_replies: set[str] = set()
        df: Counter[str] = Counter()
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
                compact_u = _compact_user_context(user_text)
                dedup_key = f"{compact_u}||{reply_text}"
                if dedup_key in seen_replies:
                    continue
                seen_replies.add(dedup_key)
                self._pairs.append((compact_u, reply_text, weight))
                toks = _tokenize(f"{compact_u} {reply_text}")
                self._docs.append(toks)
                for term in toks:
                    df[term] += 1

        total = max(len(self._docs), 1)
        self._idf = {term: math.log((total + 1) / (freq + 1)) + 1.0 for term, freq in df.items()}

    def retrieve(self, query: str, *, limit: int = 3) -> list[tuple[str, str]]:
        if not self._pairs or not query.strip():
            return []
        q_toks = _tokenize(query)
        if not q_toks:
            return []
        scored: list[tuple[float, int]] = []
        for idx, doc in enumerate(self._docs):
            score = 0.0
            for term, q_cnt in q_toks.items():
                if term in doc:
                    score += self._idf.get(term, 1.0) * min(q_cnt, 2) * (1.0 + math.log(doc[term]))
            if score > 0:
                _, reply, weight = self._pairs[idx]
                score *= weight
                if 4 <= len(reply) <= 45:
                    score *= 1.12
                scored.append((score, idx))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked: list[tuple[str, str]] = []
        seen_text: set[str] = set()
        for _, idx in scored:
            u, a, _ = self._pairs[idx]
            if a in seen_text:
                continue
            seen_text.add(a)
            picked.append((u, a))
            if len(picked) >= limit:
                break
        # Even on generic queries, anchor the model in the user's real understated rhythm.
        if len(picked) < limit:
            anchors = [
                (u, a)
                for u, a, w in self._pairs
                if w >= 0.75 and 6 <= len(a) <= 48 and a not in seen_text and "http" not in a
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

    def format_for_prompt(self, query: str, *, limit: int = 3) -> str:
        hits = self.retrieve(query, limit=limit)
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


def discover_default_corpus(root_dir: Path | None = None) -> list[tuple[Path, float]]:
    """Load explicitly configured style corpora without scanning private folders."""
    if root_dir is None:
        configured = os.environ.get("ITO_STYLE_CORPUS_DIR", "").strip()
        if not configured:
            return []
        root_dir = Path(configured).expanduser()
    if not root_dir.is_dir():
        return []
    sources = {*root_dir.glob("*.jsonl"), *root_dir.glob("*/训练数据.jsonl")}
    return [(path, 1.0) for path in sorted(sources) if path.is_file()]
