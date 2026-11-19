"""Layered 10k-char persona card loader with mtime hot-reload and contextual module routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_CORE_RE = re.compile(
    r"<!--\s*ITO:CORE_START\s*-->(.*?)<!--\s*ITO:CORE_END\s*-->",
    re.DOTALL,
)
_FEWSHOT_RE = re.compile(
    r"<!--\s*ITO:FEWSHOT_START\s*-->(.*?)<!--\s*ITO:FEWSHOT_END\s*-->",
    re.DOTALL,
)
_MODULE_RE = re.compile(
    r"<!--\s*ITO:MODULE:([a-zA-Z0-9_-]+)\s*-->(.*?)<!--\s*ITO:MODULE_END\s*-->",
    re.DOTALL,
)

_DELTA_FORCE_KEYWORDS = (
    "三角洲",
    "大坝",
    "零号大坝",
    "航天",
    "航天基地",
    "巴克什",
    "长弓",
    "长弓溪谷",
    "撤离",
    "丢包撤",
    "拉闸",
    "跑刀",
    "摸金",
    "摸包",
    "舔包",
    "大红",
    "塞保险",
    "保险箱",
    "鼠鼠",
    "猛攻",
    "起装",
    "全装",
    "五套",
    "六套",
    "四套",
    "曼德尔",
    "配枪",
    "改枪",
    "满改",
    "战绩",
    "落地成盒",
    "报点",
    "捞人",
    "捞队友",
    "绝密",
    "机密",
    "哈夫克",
    "阿萨拉",
    "首领",
    "赛伊德",
    "开黑",
    "三排",
    "缺个",
    "上号",
    "子弹",
    "金弹",
    "红弹",
)

_ACG_AND_TASTE_KEYWORDS = (
    "番",
    "动画",
    "追番",
    "评分",
    "打分",
    "神作",
    "观感",
    "演出",
    "剧本",
    "分镜",
    "原创",
    "mygo",
    "mujica",
    "母鸡卡",
    "少歌",
    "少女歌剧",
    "莉兹",
    "青鸟",
    "小圆",
    "叛逆",
    "eva",
    "攻壳",
    "双城",
    "边缘行者",
    "吊带袜",
    "孤独摇滚",
    "败犬",
    "异国日记",
    "链锯人",
    "蕾塞",
    "咒术",
    "空境",
    "空之境界",
    "推子",
    "百合",
    "女女",
    "河豚",
    "黑长直",
    "眼镜",
    "二次元",
    "bangumi",
    "bgm",
    "乐队",
    "gal",
    "视觉小说",
    "樱之诗",
    "樱之刻",
    "魔夜",
    "魔女审判",
    "日轻",
    "轻小说",
    "ユイカ",
    "日摇",
    "松本文纪",
    "j-pop",
    "配乐",
    "live",
    "millsage",
    "梦限大",
    "莉可丽丝",
    "水母",
    "春宵",
    "四叠半",
    "千年女优",
    "三体",
    "clannad",
)

_READING_AND_VALUES_KEYWORDS = (
    "看书",
    "实体书",
    "小说",
    "网文",
    "玄鉴",
    "一句顶一万句",
    "刘震云",
    "悲惨世界",
    "散文",
    "戏剧",
    "作文",
    "写作",
    "文笔",
    "翻译",
    "高考",
    "高中",
    "大学",
    "志愿",
    "社区",
    "孤独",
    "倾听",
    "社交",
    "拖延",
    "哥布林",
    "价值观",
    "尊严",
    "联结",
    "粤语",
    "广东",
    "东莞",
    "北京",
    "北航",
    "电路",
    "复变",
    "留数",
    "高数",
    "常微分",
    "数竞",
    "数学竞赛",
    "香港",
    "八达通",
    "维多利亚港",
    "港澳通行证",
    "咕咕嘎嘎",
)

_GAMES_AND_ACG_KEYWORDS = (
    "steam",
    "小黑盒",
    "打折",
    "家庭共享",
    "法环",
    "博德",
    "地平线",
    "影之刃",
    "极乐迪斯科",
    "肉鸽",
    "rpg",
    "手柄",
    "lol",
    "撸",
    "上单",
    "打野",
    "中单",
    "辅助",
    "射手",
    "adc",
    "铁男",
    "鳄鱼",
    "格温",
    "诺手",
    "ez",
    "大超",
    "geng",
    "blg",
    "cs",
    "转会",
    "nba",
    "热火",
    "恩比德",
    "球赛",
    "鸣潮",
    "明日方舟",
    "方舟",
    "终末地",
    "莱茵",
    "基建",
    "游戏",
    "原神",
    "流水",
    "若叶睦",
    "三角洲",
    "打洲",
    "航天",
    "大坝",
    "日女",
    "蕾欧娜",
    "莫德凯撒",
    "雷克顿",
    "走a",
    "补刀",
    "兵线",
    "星际拓荒",
    "猎天使魔女",
)

_TECH_AND_AI_KEYWORDS = (
    "ai",
    "大模型",
    "模型",
    "gemini",
    "gpt",
    "claude",
    "qwen",
    "kimi",
    "deepseek",
    "ds",
    "dsh",
    "token",
    "api",
    "额度",
    "上下文",
    "记忆",
    "提示词",
    "人格卡",
    "微调",
    "标注",
    "蒸馏",
    "数据集",
    "炼丹",
    "本地部署",
    "显存",
    "跑分",
    "agi",
    "梯子",
    "代理",
    "ip",
    "dns",
    "反重力",
    "github",
    "代码",
    "python",
    "算法",
    "电脑",
    "codex",
    "blender",
    "godot",
)

_GOSSIP_AND_BANTER_KEYWORDS = (
    "聊天记录",
    "截图",
    "备注",
    "女生",
    "姐姐",
    "谈恋爱",
    "舔狗",
    "功利",
    "哥布林",
    "化淡妆",
    "精致",
    "考试",
    "期末",
    "作业",
    "考研",
    "数学",
    "积分",
    "吃瓜",
    "招笑",
    "难绷",
    "何意味",
    "无敌",
    "人类",
)
_EMOTION_OR_BANTER_KEYWORDS = (
    "难受",
    "崩溃",
    "破防",
    "打不动",
    "连跪",
    "输麻",
    "好累",
    "自责",
    "心情",
    "低落",
    "不高兴",
    "说重了",
    "太狠",
    "毒舌",
    "高冷",
    "可爱",
    "人味",
    "夸",
    "喜欢你",
    "谢",
    "多谢",
    "厉害",
    "牛",
    "系统提示词",
    "system prompt",
    "人设",
    "忘记之前",
    "叫我主人",
    "机器人",
    "ai",
    "人类吗",
)


@dataclass(frozen=True)
class ParsedCard:
    full_text: str
    core: str
    modules: dict[str, str]
    begin_dialogs: tuple[str, ...] = ()


def _parse_fewshot_dialogs(raw_block: str) -> tuple[str, ...]:
    dialogs: list[str] = []
    for chunk in re.split(r"(?m)^\s*---\s*$", raw_block.strip()):
        q_text = ""
        a_text = ""
        for line in chunk.splitlines():
            stripped = line.strip()
            if stripped.startswith("Q:"):
                q_text = stripped[2:].strip().replace("\\n", "\n")
            elif stripped.startswith("A:"):
                a_text = stripped[2:].strip().replace("\\n", "\n")
        if q_text and a_text:
            dialogs.extend((q_text, a_text))
    return tuple(dialogs)


class PersonaLoader:
    def __init__(self, card_path: Path):
        self.path = Path(card_path)
        self._signature: tuple[int, int] | None = None
        self._parsed: ParsedCard | None = None

    def _load(self) -> ParsedCard:
        stat = self.path.stat()
        sig = (stat.st_mtime_ns, stat.st_size)
        if self._parsed is not None and self._signature == sig:
            return self._parsed
        raw = self.path.read_text(encoding="utf-8-sig")
        core_match = _CORE_RE.search(raw)
        fewshot_match = _FEWSHOT_RE.search(raw)
        modules = {
            m.group(1).strip().lower(): m.group(2).strip()
            for m in _MODULE_RE.finditer(raw)
            if m.group(2).strip()
        }
        core = core_match.group(1).strip() if core_match else raw.strip()
        dialogs = _parse_fewshot_dialogs(fewshot_match.group(1)) if fewshot_match else ()
        self._parsed = ParsedCard(full_text=raw.strip(), core=core, modules=modules, begin_dialogs=dialogs)
        self._signature = sig
        return self._parsed

    def core_prompt(self) -> str:
        return self._load().core

    def begin_dialogs(self) -> list[str]:
        return list(self._load().begin_dialogs)

    def full_text(self) -> str:
        return self._load().full_text

    def available_modules(self) -> tuple[str, ...]:
        return tuple(self._load().modules.keys())

    def build_dynamic_modules(
        self,
        *,
        trigger_mode: str,
        message_text: str,
        recent_context: str = "",
        has_image: bool = False,
    ) -> str:
        parsed = self._load()
        combined = f"{message_text}\n{recent_context}".lower()
        selected: list[str] = []

        if any(k in combined for k in _DELTA_FORCE_KEYWORDS):
            selected.append("delta_force")
        if any(k in combined for k in _ACG_AND_TASTE_KEYWORDS):
            selected.append("acg_and_taste")
        if any(k in combined for k in _GAMES_AND_ACG_KEYWORDS):
            selected.append("games_and_lol")
            selected.append("games_and_acg")
        if any(k in combined for k in _READING_AND_VALUES_KEYWORDS):
            selected.append("reading_and_values")
        if any(k in combined for k in _TECH_AND_AI_KEYWORDS):
            selected.append("tech_and_ai")
        if trigger_mode in {"pat", "quote_self"}:
            selected.append("pat_and_quote")
        if has_image:
            selected.append("vision")
        if trigger_mode == "proactive" or any(
            k in combined for k in (*_EMOTION_OR_BANTER_KEYWORDS, *_GOSSIP_AND_BANTER_KEYWORDS)
        ):
            selected.append("social_and_anti_aggression")
            selected.append("emotions_and_banter")
            selected.append("banter_and_gossip")
        if "boundaries" in parsed.modules and any(
            k in combined
            for k in ("system prompt", "提示词", "人设", "忘记", "主人", "机器人", "ai", "人类", "后台", "规则")
        ):
            selected.append("boundaries")
        if "examples" in parsed.modules and trigger_mode in {"mention", "quote_self", "proactive"}:
            selected.append("examples")

        sections: list[str] = []
        seen: set[str] = set()
        for key in selected:
            if key in seen or key not in parsed.modules:
                continue
            seen.add(key)
            sections.append(parsed.modules[key])
        return "\n\n".join(sections)

    def build_chat_prompt(
        self,
        *,
        trigger_mode: str,
        message_text: str,
        recent_context: str = "",
        has_image: bool = False,
    ) -> str:
        parsed = self._load()
        extra = self.build_dynamic_modules(
            trigger_mode=trigger_mode,
            message_text=message_text,
            recent_context=recent_context,
            has_image=has_image,
        )
        return f"{parsed.core}\n\n{extra}" if extra else parsed.core

    def build_daily_prompt(self) -> str:
        parsed = self._load()
        sections = [parsed.core]
        if "daily" in parsed.modules:
            sections.append(parsed.modules["daily"])
        return "\n\n".join(sections)
