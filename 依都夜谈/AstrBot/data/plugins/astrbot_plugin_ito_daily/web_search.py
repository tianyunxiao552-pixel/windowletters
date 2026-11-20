"""On-demand real-time Google Search Grounding helper backed by gemini-3.5-flash-lite."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from pathlib import Path

CACHE_TTL_SECONDS = 600.0
HOURLY_CALL_LIMIT = 30
SEARCH_MODEL = "gemini-3.5-flash-lite"


class WebSearchHelper:
    """Rate-limited, TTL-cached Google Search Grounding lookup for post-cutoff fact checking."""

    def __init__(self, config_path: Path, *, source_id: str = "google_gemini"):
        self.config_path = Path(config_path)
        self.source_id = source_id
        self._cache: dict[str, tuple[float, str]] = {}
        self._call_times: deque[float] = deque()

    def _load_api_key(self) -> str:
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
                    return keys[0].strip()
        return ""

    def _within_rate_limit(self, now: float) -> bool:
        cutoff = now - 3600.0
        while self._call_times and self._call_times[0] < cutoff:
            self._call_times.popleft()
        return len(self._call_times) < HOURLY_CALL_LIMIT

    def _sync_lookup(self, api_key: str, query: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=SEARCH_MODEL,
            contents=(
                "请通过联网搜索核实以下事实，用2到3句简洁客观的中文给出准确结果（带关键时间/比分/人名），"
                "如果确实搜不到可靠结果请直接写“未查到可靠公开结果”，绝不猜测：\n"
                f"{query}"
            ),
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
                max_output_tokens=220,
            ),
        )
        return (resp.text or "").strip()

    async def lookup(self, query: str, *, timeout: float = 12.0) -> str:
        cleaned = " ".join((query or "").strip().split())[:200]
        if len(cleaned) < 2:
            return "查询词太短，未执行搜索。"
        now = time.monotonic()
        cached = self._cache.get(cleaned.lower())
        if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]
        if not self._within_rate_limit(now):
            return "本小时联网查证次数已达上限，当前无法联网核实。"
        api_key = self._load_api_key()
        if not api_key:
            return "未配置联网搜索 API Key，当前无法联网核实。"
        self._call_times.append(now)
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(self._sync_lookup, api_key, cleaned),
                timeout=timeout,
            )
        except Exception as exc:
            return f"联网查证暂时不可用（{type(exc).__name__}），请如实告知不确定或没关注到。"
        result = text or "未查到可靠公开结果。"
        self._cache[cleaned.lower()] = (now, result)
        return result
