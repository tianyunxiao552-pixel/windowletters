"""Read-only personal knowledge & taste memory backed by 个人信息.sqlite3."""

from __future__ import annotations

import math
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

def configured_kb_path() -> Path | None:
    path = os.environ.get("ITO_PERSONAL_KB_PATH", "").strip()
    return Path(path).expanduser() if path else None


_WORD_RE = re.compile(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", re.I)

# Common shorthand aliases -> canonical title substrings in bangumi_reviews / bilibili_posts
_WORK_ALIASES: dict[str, tuple[str, ...]] = {
    "mygo": ("It's MyGO",),
    "mujica": ("Ave Mujica",),
    "母鸡卡": ("Ave Mujica",),
    "少歌": ("少女☆歌剧",),
    "少女歌剧": ("少女☆歌剧",),
    "莉兹": ("莉兹与青鸟",),
    "青鸟": ("莉兹与青鸟",),
    "小圆": ("魔法少女小圆",),
    "叛逆的物语": ("叛逆的物语",),
    "eva": ("新世纪福音战士",),
    "攻壳": ("攻壳机动队",),
    "双城之战": ("双城之战",),
    "双城": ("双城之战",),
    "博德之门": ("博德之门3",),
    "博德": ("博德之门3",),
    "bg3": ("博德之门3",),
    "樱之诗": ("樱之诗",),
    "樱之刻": ("樱之刻",),
    "魔夜": ("魔法使之夜",),
    "魔女审判": ("魔法少女的魔女审判",),
    "魔裁": ("魔法少女的魔女审判",),
    "边缘行者": ("边缘行者",),
    "赛博朋克": ("边缘行者", "赛博朋克"),
    "吊带袜": ("吊带袜天使",),
    "异国日记": ("异国日记",),
    "孤独摇滚": ("孤独摇滚",),
    "蕾塞": ("蕾塞篇",),
    "链锯人": ("链锯人",),
    "电锯人": ("链锯人",),
    "咒术": ("咒术回战",),
    "死灭回游": ("死灭回游",),
    "回天": ("回天", "魔法少女小圆"),
    "败犬": ("败犬女主",),
    "春宵": ("春宵苦短",),
    "水母": ("夜晚的水母不会游泳",),
    "莉可丽丝": ("莉可丽丝", "Lycoris"),
    "空之境界": ("空之境界",),
    "空境": ("空之境界",),
    "clannad": ("CLANNAD",),
    "推子": ("我推的孩子",),
    "我推": ("我推的孩子",),
    "四叠半": ("四叠半神话大系",),
    "千年女优": ("千年女优",),
    "你的名字": ("你的名字",),
    "巨人": ("进击的巨人",),
    "国王排名": ("国王排名",),
    "赛马娘": ("赛马娘",),
    "动物狂想曲": ("动物狂想曲",),
    "兽娘": ("兽娘动物园",),
    "向日葵马戏团": ("向日葵马戏团",),
    "梦限大": ("梦限大",),
    "millsage": ("millsage",),
    "终末地": ("终末地",),
    "鸣潮": ("鸣潮",),
    "明日方舟": ("明日方舟",),
    "一句顶一万句": ("一句顶一万句",),
    "悲惨世界": ("悲惨世界",),
    "三体": ("三体",),
    "妹妹人生": ("妹妹人生",),
    "与你相恋": ("与你相恋到生命尽头",),
}

_STOP_TITLES = frozenset({"三体", "游戏", "动画", "音乐", "书籍", "日常", "电影", "剧情"})

# Common variant / traditional / homophone-typo pairs so a 1-char slip (e.g. 熏 vs 薰) never misses.
_VARIANT_TRANSLATION = str.maketrans(
    {
        "熏": "薰",
        "凜": "凛",
        "涼": "凉",
        "詠": "咏",
        "櫻": "樱",
        "劍": "剑",
        "戀": "恋",
        "夢": "梦",
        "聲": "声",
        "國": "国",
        "樂": "乐",
        "無": "无",
        "風": "风",
        "愛": "爱",
        "戰": "战",
        "機": "机",
        "龍": "龙",
        "馬": "马",
        "鳥": "鸟",
        "黒": "黑",
        "繪": "绘",
        "學": "学",
        "園": "园",
        "華": "华",
        "麗": "丽",
        "實": "实",
        "際": "际",
        "時": "时",
        "間": "间",
        "與": "与",
        "為": "为",
        "說": "说",
        "話": "话",
        "語": "语",
        "紀": "纪",
        "記": "记",
        "錄": "录",
        "響": "响",
        "戲": "戏",
        "劇": "剧",
        "號": "号",
        "點": "点",
        "線": "线",
        "邊": "边",
        "緣": "缘",
        "異": "异",
        "體": "体",
    }
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_UNSEEN_WORK_PATTERNS = (
    re.compile(r"《([^《》\n]{2,24})》"),
    re.compile(
        r"(?:评价一下|锐评一下|说说(?:你对|我对|对)|怎么看|觉得|看过|读过|推过|玩过)\s*([^\s，。！？,.!?:：()（）]{2,18})(?:吗|没|没有|的评价|怎么样|咋样|好看吗|好玩吗|写得怎么样|如何)?"
    ),
)
_UNSEEN_NON_WORK_WORDS = (
    "这个",
    "那个",
    "一下",
    "什么",
    "怎么",
    "今天",
    "刚才",
    "最近",
    "现在",
    "群里",
    "群友",
    "大家",
    "自己",
    "我们",
    "你们",
    "他们",
    "模型",
    "提示词",
    "人格",
    "人设",
    "数据库",
    "外挂",
    "机器人",
    "天气",
    "游戏",
    "动画",
    "番剧",
    "电影",
    "小说",
)


def _normalize_text(text: str) -> str:
    return text.lower().translate(_VARIANT_TRANSLATION)


def _cjk_bigrams(text: str) -> set[str]:
    grams: set[str] = set()
    for seg in _CJK_RE.findall(text):
        for i in range(len(seg) - 1):
            grams.add(seg[i : i + 2])
    return grams


def _tokenize(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    lower = _normalize_text(text)
    for token in _WORD_RE.findall(lower):
        if token.isascii():
            counts[token] += 1
        else:
            if len(token) <= 4:
                counts[token] += 1
            for i in range(len(token) - 1):
                counts[token[i : i + 2]] += 1
    return counts


@dataclass(frozen=True)
class ReviewEntry:
    media_type: str
    title: str
    original_title: str
    status: str
    rating: int | None
    review: str


@dataclass(frozen=True)
class PostEntry:
    published_at: str
    kind: str
    title: str
    body: str
    tokens: Counter[str]


@dataclass(frozen=True)
class FactItem:
    category: str
    label: str
    statement: str
    tokens: Counter[str]


class PersonalKnowledgeBase:
    """Fast in-memory read-only lookup over 个人信息.sqlite3 and 个人信息补充汇总.md."""

    def __init__(self, db_path: Path | None = None, supplement_path: Path | None = None):
        self.path = Path(db_path) if db_path is not None else configured_kb_path()
        self.supplement_path = (
            Path(supplement_path)
            if supplement_path is not None
            else self.path.parent / "个人信息补充汇总.md" if self.path else None
        )
        self._reviews: list[ReviewEntry] = []
        self._posts: list[PostEntry] = []
        self._items: list[FactItem] = []
        self._post_idf: dict[str, float] = {}
        self._item_idf: dict[str, float] = {}
        self._load()

    @property
    def review_count(self) -> int:
        return len(self._reviews)

    @property
    def post_count(self) -> int:
        return len(self._posts)

    @property
    def item_count(self) -> int:
        return len(self._items)

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        item_df: Counter[str] = Counter()
        try:
            conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error:
            return
        try:
            cur = conn.cursor()
            for row in cur.execute(
                "SELECT media_type, title, original_title, collection_status, personal_rating, personal_review "
                "FROM bangumi_reviews"
            ).fetchall():
                title = (row[1] or "").strip()
                if not title:
                    continue
                rating = int(row[4]) if row[4] is not None and str(row[4]).isdigit() else None
                self._reviews.append(
                    ReviewEntry(
                        media_type=(row[0] or "").strip(),
                        title=title,
                        original_title=(row[2] or "").strip(),
                        status=(row[3] or "").strip(),
                        rating=rating,
                        review=" ".join((row[5] or "").split()),
                    )
                )

            post_df: Counter[str] = Counter()
            for row in cur.execute(
                "SELECT published_at, kind, title, body FROM bilibili_posts"
            ).fetchall():
                title = (row[2] or "").strip()
                body = " ".join((row[3] or "").split())
                if not title and len(body) < 20:
                    continue
                toks = _tokenize(f"{title} {body[:1200]}")
                self._posts.append(
                    PostEntry(
                        published_at=(row[0] or "")[:10],
                        kind=(row[1] or "").strip(),
                        title=title,
                        body=body,
                        tokens=toks,
                    )
                )
                for term in toks:
                    post_df[term] += 1
            n_posts = max(len(self._posts), 1)
            self._post_idf = {t: math.log((n_posts + 1) / (f + 1)) + 1.0 for t, f in post_df.items()}

            for row in cur.execute("SELECT category, label, statement FROM items").fetchall():
                cat, label, stmt = (row[0] or "").strip(), (row[1] or "").strip(), (row[2] or "").strip()
                if not stmt:
                    continue
                toks = _tokenize(f"{label} {stmt}")
                self._items.append(FactItem(category=cat, label=label, statement=stmt, tokens=toks))
                for term in toks:
                    item_df[term] += 1
        except sqlite3.Error:
            pass
        finally:
            conn.close()

        # Also load structured supplement markdown bullets alongside the SQLite DB.
        if self.supplement_path is not None and self.supplement_path.is_file():
            try:
                section = "个人补充"
                for raw_line in self.supplement_path.read_text(encoding="utf-8-sig").splitlines():
                    line = raw_line.strip()
                    if line.startswith("## "):
                        section = line[3:].strip()
                    elif line.startswith("- ") and len(line) > 6:
                        stmt = line[2:].strip()
                        toks = _tokenize(f"{section} {stmt}")
                        self._items.append(
                            FactItem(category="个人补充", label=section, statement=stmt, tokens=toks)
                        )
                        for term in toks:
                            item_df[term] += 1
            except OSError:
                pass

        n_items = max(len(self._items), 1)
        self._item_idf = {t: math.log((n_items + 1) / (f + 1)) + 1.0 for t, f in item_df.items()}

    def _match_reviews(self, query: str, *, limit: int = 3) -> list[ReviewEntry]:
        q_norm = _normalize_text(query)
        q_bigrams = _cjk_bigrams(q_norm)
        canonical_targets: list[str] = []
        for alias, targets in _WORK_ALIASES.items():
            if _normalize_text(alias) in q_norm:
                canonical_targets.extend(_normalize_text(t) for t in targets)

        scored: list[tuple[float, ReviewEntry]] = []
        q_nums = set(re.findall(r"\d+", q_norm))
        for r in self._reviews:
            t_norm = _normalize_text(r.title)
            o_norm = _normalize_text(r.original_title)
            score = 0.0
            if any(ct in t_norm or (o_norm and ct in o_norm) for ct in canonical_targets):
                score += 10.0
            elif len(t_norm) >= 3 and t_norm not in _STOP_TITLES and t_norm in q_norm:
                score += 9.0
            elif len(o_norm) >= 4 and o_norm in q_norm:
                score += 8.0
            else:
                # Match shorthand main/subtitle segments (e.g. "赛博朋克2" -> "赛博朋克：边缘行者2")
                parts = [
                    p.strip()
                    for p in re.split(r"[:：\s·\-—\[\]()（）「」!！?？]+", t_norm)
                    if len(p.strip()) >= 3
                ]
                for seg in parts:
                    if seg not in _STOP_TITLES and seg in q_norm:
                        score += 7.5
                        break
                # Typo-tolerant CJK bigram overlap fallback for >= 4-char titles
                if score == 0.0 and q_bigrams:
                    t_grams = _cjk_bigrams(t_norm)
                    if len(t_grams) >= 3:
                        overlap = len(t_grams & q_bigrams)
                        ratio = overlap / len(t_grams)
                        if overlap >= 3 and ratio >= 0.65:
                            score += 6.0 + ratio * 2.0
            if score > 0:
                t_nums = set(re.findall(r"\d+", t_norm))
                if q_nums and t_nums and (q_nums & t_nums):
                    score += 3.0
                if r.review:
                    score += 1.5
                if r.rating is not None:
                    score += 0.5
                scored.append((score, r))
        scored.sort(key=lambda x: (x[0], len(x[1].review)), reverse=True)
        picked: list[ReviewEntry] = []
        seen: set[str] = set()
        for _, entry in scored:
            if entry.title in seen:
                continue
            seen.add(entry.title)
            picked.append(entry)
            if len(picked) >= limit:
                break
        return picked

    def detect_unseen_work_query(self, message_text: str) -> str | None:
        """If the user explicitly asks about a work not found in personal DB, return a grounded negative cue."""
        cleaned = (message_text or "").strip()
        if len(cleaned) < 4:
            return None
        candidate = ""
        for pat in _UNSEEN_WORK_PATTERNS:
            m = pat.search(cleaned)
            if m:
                candidate = m.group(1).strip("《》「」\"' ")
                break
        if not candidate or len(candidate) < 2:
            return None
        if any(w in candidate for w in _UNSEEN_NON_WORK_WORDS):
            return None
        if self.query_for_prompt(candidate, max_chars=200):
            return None
        return f"个人记忆库未收录《{candidate}》（无你的观看/阅读或评分记录）；若对方问你的观后感或是否看过，如实说没看过或没读过。"

    def _match_posts(self, query: str, *, limit: int = 2) -> list[PostEntry]:
        q_lower = query.lower()
        q_toks = _tokenize(query)
        if not q_toks:
            return []
        scored: list[tuple[float, PostEntry]] = []
        for post in self._posts:
            score = 0.0
            # Direct title hit gets a big boost
            if post.title and len(post.title) >= 3 and post.title.lower() in q_lower:
                score += 20.0
            for alias, targets in _WORK_ALIASES.items():
                if alias in q_lower:
                    hay = f"{post.title} {post.body[:600]}".lower()
                    if any(t.lower() in hay for t in targets):
                        score += 14.0
            for term, cnt in q_toks.items():
                if term in post.tokens:
                    score += self._post_idf.get(term, 1.0) * min(cnt, 2) * (1.0 + 0.4 * math.log(post.tokens[term]))
            # High bar so small talk never pulls random posts
            if score >= 12.0:
                scored.append((score, post))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:limit]]

    def _match_items(self, query: str, *, limit: int = 2) -> list[FactItem]:
        q_toks = _tokenize(query)
        if not q_toks:
            return []
        scored: list[tuple[float, FactItem]] = []
        for item in self._items:
            score = 0.0
            for term, cnt in q_toks.items():
                if term in item.tokens:
                    score += self._item_idf.get(term, 1.0) * min(cnt, 2)
            if score >= 8.5:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[:limit]]

    def query_for_prompt(self, query: str, *, max_chars: int = 950) -> str:
        """Return concise matched personal facts/reviews/posts, or '' when unrelated."""
        cleaned = (query or "").strip()
        if len(cleaned) < 2:
            return ""
        lines: list[str] = []

        reviews = self._match_reviews(cleaned, limit=3)
        for r in reviews:
            rating_str = f"{r.rating}分" if r.rating is not None else r.status
            rev = re.sub(r"^(?:普朗姆布洛森|天韵霄)\s*", "", r.review).strip()
            rev_str = f"（核心看法：{rev[:170]}）" if rev else ""
            lines.append(f"- 《{r.title}》你给过 {rating_str}{rev_str}")

        posts = self._match_posts(cleaned, limit=2)
        for p in posts:
            head = f"《{p.title}》" if p.title else f"{p.published_at}随感"
            lines.append(f"- 你以前写过{head}，大致观点：{p.body[:220]}")

        items = self._match_items(cleaned, limit=2)
        for it in items:
            stmt = it.statement.replace("他", "你")
            lines.append(f"- 你的习惯/标准（{it.label}）：{stmt}")

        if not lines:
            return ""
        out = "\n".join(lines)
        return out[:max_chars]
