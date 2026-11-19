import asyncio
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

source = Path(__file__).parents[1] / "AstrBot/data/plugins/astrbot_plugin_ito_daily/daily.py"
spec = importlib.util.spec_from_file_location("ito_daily", source)
daily = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = daily
spec.loader.exec_module(daily)

ACCOUNT = "account-test"
GROUP = "target@chatroom"
NOW = datetime.fromisoformat("2026-11-19T15:05:00+00:00")


class Native:
    def __init__(self, pages=(), fail=False):
        self.pages = iter(pages)
        self.sends = []
        self.fail = fail

    async def messages(self, thread, *, limit, cursor):
        assert thread == GROUP
        return next(self.pages)

    async def send_text(self, thread, text, key):
        self.sends.append((thread, text, key))
        if self.fail:
            raise TimeoutError
        return {"id": "receipt", "state": "accepted"}

    async def send_by_key(self, key):
        return {"id": "receipt", "state": "accepted", "accountId": ACCOUNT, "destination": GROUP}


def message(mid, stamp, **overrides):
    return dict(id=mid, createdAt=stamp, accountId=ACCOUNT, threadId=GROUP,
                senderId="member", body=mid, direction="incoming", type=1) | overrides


class DailyTest(unittest.TestCase):
    def test_beijing_window_and_scope(self):
        window = daily.due_window(NOW)
        self.assertEqual(str(window.start), "2026-11-19 00:00:00+08:00")
        self.assertEqual(str(window.end), "2026-11-19 23:00:00+08:00")
        self.assertIsNone(daily.due_window(datetime.fromisoformat("2026-11-19T14:59:59+00:00")))
        valid = message("confirm", "2026-11-19T14:59:59Z", senderId="wxid_zhao")
        quoted = message(
            "quote-reply",
            "2026-11-19T14:50:00Z",
            type=49,
            appMessageType=57,
            senderId="wxid_ming",
            body="九点半没问题",
            quote={"state": "embedded", "embeddedText": "今晚九点半开黑吗"},
        )
        client = Native([{"items": [
            valid, valid,
            quoted,
            message("midnight", "2026-11-18T16:00:00Z", senderId="wxid_zhao"),
            message("late", "2026-11-19T15:00:00Z"),
            message("recalled", "2026-11-19T14:30:00Z", recall={}),
            message("self", "2026-11-19T14:31:00Z", direction="outgoing"),
        ]}])
        rows, partial = asyncio.run(
            daily.collect(
                client,
                ACCOUNT,
                GROUP,
                window,
                names={"wxid_zhao": "老赵", "wxid_ming": "阿明"},
            )
        )
        self.assertEqual([x["text"] for x in rows], ["midnight", "九点半没问题", "confirm"])
        self.assertEqual([x["sender"] for x in rows], ["老赵", "阿明", "老赵"])
        self.assertEqual(rows[1].get("quote"), "今晚九点半开黑吗")
        self.assertFalse(partial)
        wrong = Native([{"items": [valid | {"threadId": "other@chatroom"}]}])
        with self.assertRaises(ValueError):
            asyncio.run(daily.collect(wrong, ACCOUNT, GROUP, window))

    def test_uncertain_send_is_reconciled_without_duplicate(self):
        client = Native(fail=True)
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "report.json"

            async def run():
                with self.assertRaises(TimeoutError):
                    await daily.deliver(client, ACCOUNT, GROUP, file, "内容")
                await daily.deliver(client, ACCOUNT, GROUP, file)
                await daily.deliver(client, ACCOUNT, GROUP, file)

            asyncio.run(run())
            self.assertEqual(len(client.sends), 1)
            self.assertEqual(daily.read_report(file)["status"], "accepted")

    def test_compute_stats_counts_messages_members_and_peak_hour(self):
        rows = [
            {"time": "00:15", "sender": "老赵", "text": "开黑吗"},
            {"time": "00:40", "sender": "阿明", "text": "马上"},
            {"time": "00:55", "sender": "老赵", "text": "你这马上有点长"},
            {"time": "10:12", "sender": "小周", "text": "早"},
        ]
        stats = daily.compute_stats(rows)
        self.assertEqual(stats["total_messages"], 4)
        self.assertEqual(stats["active_members"], 3)
        self.assertEqual(stats["peak_hour"], "00:00–01:00")


if __name__ == "__main__":
    unittest.main()
