import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).parents[1] / "AstrBot/data/plugins/astrbot_plugin_ito_daily"


def load_module(name: str):
    path = PLUGIN_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ito_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ContextBufferTest(unittest.TestCase):
    def test_records_bounded_context_and_formats_with_names_and_quotes(self):
        mod = load_module("context_buffer")
        buf = mod.GroupContextBuffer(max_items=5, max_age_seconds=1800)
        base = 1_763_500_000.0
        buf.record("g1", message_id="m1", sender_id="u1", sender_name="老赵", text="你是找的GitHub项目还是ai手搓", ts=base)
        buf.record("g1", message_id="m2", sender_id="u2", sender_name="阿明", text="肯定结合啊", ts=base + 10)
        buf.record("g1", message_id="m3", sender_id="bot", sender_name="依都", text="两个混着用也行", ts=base + 15, is_bot=True, server_id="srv-bot-1")
        buf.record("g1", message_id="m4", sender_id="u2", sender_name="阿明", text="这句人味不错", ts=base + 20, quote_text="两个混着用也行")

        rendered = buf.format_context("g1", now=base + 30, exclude_message_id="m4")
        self.assertIn("老赵: 你是找的GitHub项目还是ai手搓", rendered)
        self.assertIn("阿明: 肯定结合啊", rendered)
        self.assertIn("依都(你): 两个混着用也行", rendered)
        self.assertNotIn("这句人味不错", rendered)
        self.assertTrue(buf.was_bot_message("g1", server_id="srv-bot-1"))
        self.assertTrue(buf.was_bot_message("g1", text="两个混着用也行"))
        self.assertFalse(buf.was_bot_message("g1", text="肯定结合啊"))


class MemberDirectoryTest(unittest.TestCase):
    def test_resolves_priority_nickname_and_caches(self):
        mod = load_module("members")

        class FakeClient:
            def __init__(self):
                self.calls = 0

            async def group_members(self, group, *, limit=200, cursor="", search=""):
                self.calls += 1
                return {
                    "items": [
                        {
                            "id": "wxid_1",
                            "username": "wxid_1",
                            "roomDisplayName": "航天摸金王",
                            "displayName": "大赵",
                            "nickname": "Zhao",
                        },
                        {
                            "id": "wxid_2",
                            "username": "wxid_2",
                            "roomDisplayName": "",
                            "displayName": "阿明",
                            "nickname": "Ming",
                        },
                    ],
                    "nextCursor": None,
                }

        client = FakeClient()
        directory = mod.MemberDirectory(ttl_seconds=600)
        name1 = asyncio.run(directory.resolve("g1", "wxid_1", client))
        name2 = asyncio.run(directory.resolve("g1", "wxid_2", client))
        name3 = asyncio.run(directory.resolve("g1", "wxid_unknown", client))
        self.assertEqual(name1, "航天摸金王")
        self.assertEqual(name2, "阿明")
        self.assertEqual(name3, "wxid_unknown")
        self.assertEqual(client.calls, 1)


class GroupMemoryTest(unittest.TestCase):
    def test_persists_member_and_group_notes_and_formats_relevant_entries(self):
        mod = load_module("memory")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "group_memory.json"
            store = mod.GroupMemoryStore(path)
            store.remember_member("g1", "wxid_1", name="老赵", notes=["经常上晚班", "擅长航天基地捞队友"])
            store.remember_member("g1", "wxid_2", name="阿明", notes=["嘴里的两分钟通常是二十分钟"])
            store.remember_group_fact("g1", "群里常约每晚九点三排三角洲")

            reloaded = mod.GroupMemoryStore(path)
            prompt = reloaded.format_for_prompt("g1", active_sender_ids=("wxid_1",))
            self.assertIn("老赵", prompt)
            self.assertIn("晚班", prompt)
            self.assertIn("九点三排三角洲", prompt)
            self.assertNotIn("二十分钟", prompt)


class PersonaLoaderTest(unittest.TestCase):
    SAMPLE_CARD = """# 瀬尾 依都

<!-- ITO:CORE_START -->
你是瀬尾 依都，群友叫你依都。清冷敏锐又带一点腹黑和可爱反差。
<!-- ITO:CORE_END -->

<!-- ITO:MODULE:delta_force -->
## 三角洲语境
懂撤离、跑刀、航天基地、摸大红、五套六套。
<!-- ITO:MODULE_END -->

<!-- ITO:MODULE:pat_and_quote -->
## 拍一拍与引用回复
被拍了拍时自然轻怼或收下，不机械复读。
<!-- ITO:MODULE_END -->

<!-- ITO:MODULE:daily -->
## 日报模式
只输出简洁中文群聊小结。
<!-- ITO:MODULE_END -->
"""

    def test_builds_layered_prompt_by_context_and_mode(self):
        mod = load_module("persona_loader")
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "card.md"
            card.write_text(self.SAMPLE_CARD, encoding="utf-8")
            loader = mod.PersonaLoader(card)

            self.assertIn("你是瀬尾 依都", loader.core_prompt())
            self.assertNotIn("三角洲语境", loader.core_prompt())

            delta_prompt = loader.build_chat_prompt(
                trigger_mode="mention",
                message_text="今晚航天绝密跑刀还是起六套",
            )
            self.assertIn("三角洲语境", delta_prompt)
            self.assertNotIn("日报模式", delta_prompt)

            pat_prompt = loader.build_chat_prompt(
                trigger_mode="pat",
                message_text="（阿明拍了拍你）",
            )
            self.assertIn("拍一拍与引用回复", pat_prompt)
            self.assertNotIn("三角洲语境", pat_prompt)

            daily_prompt = loader.build_daily_prompt()
            self.assertIn("你是瀬尾 依都", daily_prompt)
            self.assertIn("日报模式", daily_prompt)
            self.assertNotIn("拍一拍与引用回复", daily_prompt)


class OutputFilterTest(unittest.TestCase):
    def test_detects_skip_cleans_markdown_and_splits_bubbles(self):
        mod = load_module("output_filter")
        self.assertTrue(mod.is_skip_reply("[SKIP]"))
        self.assertTrue(mod.is_skip_reply("  【skip】 "))
        self.assertFalse(mod.is_skip_reply("在呢"))

        cleaned = mod.clean_wechat_text("### 总结\n**确实**，你这波 `操作` 挺离谱的。\n\n- 下一把别贪包了")
        self.assertNotIn("**", cleaned)
        self.assertNotIn("###", cleaned)
        self.assertNotIn("`", cleaned)

        bubbles = mod.split_natural_bubbles("收下了。\n\n不过熬夜到一点多夸我，听着怪可疑的。\n\n赶紧睡吧你。")
        self.assertEqual(len(bubbles), 3)
        self.assertEqual(bubbles[0], "收下了。")
        self.assertEqual(bubbles[2], "赶紧睡吧你。")


class StyleRagTest(unittest.TestCase):
    def test_loads_sanitized_examples_and_retrieves_topic_relevant_samples(self):
        mod = load_module("style_rag")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "train.jsonl"
            rows = [
                {
                    "messages": [
                        {"role": "user", "content": "Rising：qwen4-max怎么还没上"},
                        {"role": "assistant", "content": "上了啊\n预览版"},
                    ]
                },
                {
                    "messages": [
                        {"role": "user", "content": "卡了电竞王礼豪：你想玩的话我可以给你共享"},
                        {"role": "assistant", "content": "我们家庭有🤣\n还缺个法环 等打折买一下"},
                    ]
                },
                {
                    "messages": [
                        {"role": "user", "content": "隐私测试"},
                        {"role": "assistant", "content": "你下一个这个 25373404 xwt123456"},
                    ]
                },
                {
                    "messages": [
                        {"role": "user", "content": "刷屏测试"},
                        {"role": "assistant", "content": "打电话给客服网络好慢好慢好慢"},
                    ]
                },
            ]
            import json
            p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            retriever = mod.StyleCorpusRetriever([p])
            self.assertEqual(retriever.size, 2)
            hits = retriever.retrieve("Steam法环打折共享玩一下", limit=2)
            self.assertTrue(hits)
            self.assertIn("法环", hits[0][1])
            formatted = retriever.format_for_prompt("Steam法环打折共享玩一下", limit=2)
            self.assertNotIn("25373404", formatted)
            self.assertNotIn("xwt123456", formatted)
            self.assertNotIn("打电话给客服", formatted)


if __name__ == "__main__":
    unittest.main()
