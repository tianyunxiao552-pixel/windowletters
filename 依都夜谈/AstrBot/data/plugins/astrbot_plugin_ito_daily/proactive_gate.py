"""Zero-cost real-time group chat gatekeeper backed by free gemini-3.5-flash-lite."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

GATE_MODEL = "gemini-3.5-flash-lite"
DEFAULT_THRESHOLD = 7
BACKOFF_SECONDS = 180.0
EVAL_TIMEOUT_SECONDS = 6.0

_SCORE_RE = re.compile(r'"score"\s*:\s*(\d{1,2})')
_HOOK_RE = re.compile(r'"hook"\s*:\s*"([^"\n]{0,60})"')


@dataclass(frozen=True)
class GateDecision:
    should_reply: bool
    score: int
    hook: str = ""
    backed_off: bool = False


def parse_gate_response(raw_text: str, *, threshold: int = DEFAULT_THRESHOLD) -> GateDecision:
    """Parse structured JSON (or fallback regex) gatekeeper output safely."""
    cleaned = (raw_text or "").strip()
    if not cleaned:
        return GateDecision(False, 0)
    # Try strict JSON object first
    obj_match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
    if obj_match:
        try:
            data = json.loads(obj_match.group(0))
            if isinstance(data, dict) and "score" in data:
                score = max(0, min(10, int(data.get("score") or 0)))
                hook = " ".join(str(data.get("hook") or "").strip().split())[:60]
                return GateDecision(score >= threshold, score, hook)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    # Regex fallback if truncated JSON
    s_match = _SCORE_RE.search(cleaned)
    if s_match:
        score = max(0, min(10, int(s_match.group(1))))
        h_match = _HOOK_RE.search(cleaned)
        hook = h_match.group(1).strip() if h_match else ""
        return GateDecision(score >= threshold, score, hook)
    return GateDecision(False, 0)


class LiveProactiveGate:
    """Reads recent group chat windows via free Flash-Lite and only wakes the main LLM on genuine hooks."""

    def __init__(
        self,
        config_path: Path,
        *,
        source_id: str = "google_gemini_free",
        threshold: int = DEFAULT_THRESHOLD,
    ):
        self.config_path = Path(config_path)
        self.source_id = source_id
        self.threshold = threshold
        self._backoff_until: float = 0.0
        self._cached_key: str = ""
        self._cached_key_ts: float = 0.0
        self._client = None
        self._client_key: str = ""

    def is_backed_off(self, now: float | None = None) -> bool:
        ref = time.monotonic() if now is None else now
        return ref < self._backoff_until

    def _load_api_key(self) -> str:
        now = time.monotonic()
        if self._cached_key and (now - self._cached_key_ts) < 300.0:
            return self._cached_key
        if not self.config_path.is_file():
            return ""
        try:
            cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        for src in cfg.get("provider_sources") or []:
            if isinstance(src, dict) and src.get("id") == self.source_id:
                keys = src.get("key") or []
                if isinstance(keys, list) and keys and isinstance(keys[0], str):
                    self._cached_key = keys[0].strip()
                    self._cached_key_ts = now
                    return self._cached_key
        return ""

    def _get_client(self, api_key: str):
        if self._client is None or self._client_key != api_key:
            from google import genai

            self._client = genai.Client(api_key=api_key)
            self._client_key = api_key
        return self._client

    def _sync_evaluate(self, api_key: str, snippet: str, latest_line: str) -> str:
        from google.genai import types

        client = self._get_client(api_key)
        prompt = (
            "你是群聊旁观门卫，负责判断熟人群友「依都」此刻有没有必要主动插一句嘴。\n"
            "依都画像：北航理工科、广东人，懂动画/番剧/Gal/单机/影之刃零/LOL/AI模型与工具，爱冷幽默轻吐槽，但绝不强行搭话、不打断别人私事或激烈战术复盘、不对情绪低落/输游戏红温的人拱火。\n"
            "评分标准（0-10）：\n"
            "- 0~3：普通生活琐事（吃饭/在忙/约人）、纯水字数/表情、私事、或者别人正在认真复盘/点名对话。\n"
            "- 4~6：有点意思，但依都不说话也完全正常。\n"
            "- 7~8：明显冒出好玩的反转/神吐槽/离谱笑点，或者正好踩中依都熟悉的番剧、游戏、AI工具话题，顺手接一句很自然出彩。\n"
            "- 9~10：极高笑点或高度契合依都的梗，不接一句太可惜。\n"
            '严格只输出一行 JSON：{"score": 0到10整数, "hook": "如果>=7用15字以内写切入点，否则空字符串"}\n\n'
            f"近期群聊：\n{snippet}\n\n最新一条：\n{latest_line}"
        )
        cfg_kwargs: dict = {
            "temperature": 0.1,
            "max_output_tokens": 64,
            "response_mime_type": "application/json",
        }
        try:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            )
        except Exception:
            pass
        resp = client.models.generate_content(
            model=GATE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
        return (resp.text or "").strip()

    async def evaluate(
        self,
        *,
        recent_snippet: str,
        latest_line: str,
        timeout: float = EVAL_TIMEOUT_SECONDS,
    ) -> GateDecision:
        now = time.monotonic()
        if self.is_backed_off(now):
            return GateDecision(False, 0, backed_off=True)
        api_key = self._load_api_key()
        if not api_key:
            return GateDecision(False, 0)
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(
                    self._sync_evaluate,
                    api_key,
                    (recent_snippet or "")[-700:],
                    (latest_line or "")[:200],
                ),
                timeout=timeout,
            )
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                self._backoff_until = time.monotonic() + BACKOFF_SECONDS
                return GateDecision(False, 0, backed_off=True)
            return GateDecision(False, 0)
        return parse_gate_response(raw, threshold=self.threshold)
