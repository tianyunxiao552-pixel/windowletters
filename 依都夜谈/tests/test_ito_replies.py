import importlib.util
import unittest
from pathlib import Path

source = Path(__file__).parents[1] / "AstrBot/data/plugins/astrbot_plugin_ito_daily/reply_policy.py"
spec = importlib.util.spec_from_file_location("ito_reply_policy", source)
replies = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replies)


class ReplyPolicyTest(unittest.TestCase):
    def test_mention_ignores_probability_and_cooldown(self):
        self.assertEqual(replies.select_reply(True, False, 1, 1), "mention")

    def test_quote_self_always_replies_regardless_of_probability_or_cooldown(self):
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                quoted_self=True,
                text="这句人味不错",
            ),
            "quote_self",
        )

    def test_pat_replies_with_short_antispam_cooldown(self):
        self.assertEqual(
            replies.select_reply(
                False,
                False,
                0.99,
                0,
                patted_self=True,
                since_last_pat=10.0,
            ),
            "pat",
        )
        self.assertEqual(
            replies.select_reply(
                False,
                False,
                0.01,
                999,
                patted_self=True,
                since_last_pat=2.0,
            ),
            "ignore",
        )

    def test_proactive_probability_and_group_interval(self):
        self.assertEqual(
            replies.select_reply(False, True, 0.139, 300, text="今晚航天绝密缺个报点的"),
            "proactive",
        )
        self.assertEqual(
            replies.select_reply(False, True, 0.14, 300, text="今晚航天绝密缺个报点的"),
            "ignore",
        )
        self.assertEqual(
            replies.select_reply(False, True, 0.01, 299, text="今晚航天绝密缺个报点的"),
            "ignore",
        )
        self.assertEqual(
            replies.select_reply(False, False, 0.01, 300, text="今晚航天绝密缺个报点的"),
            "ignore",
        )

    def test_smart_gate_triggers_gate_check_with_cooldown_and_signal_guard(self):
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                300,
                text="我们交大有无限API但只有qwen和4flash",
                use_smart_gate=True,
                since_last_gate_scan=50.0,
                new_msgs_since_scan=2,
            ),
            "gate_check",
        )
        # Respects 45s scan cooldown
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.01,
                300,
                text="我们交大有无限API但只有qwen和4flash",
                use_smart_gate=True,
                since_last_gate_scan=20.0,
                new_msgs_since_scan=5,
            ),
            "ignore",
        )
        # Short single message without enough accumulated messages stays quiet
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.01,
                300,
                text="在吃饭",
                use_smart_gate=True,
                since_last_gate_scan=60.0,
                new_msgs_since_scan=1,
            ),
            "ignore",
        )

    def test_proactive_yields_during_rapid_group_debate_burst(self):
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.01,
                600,
                text="离心一楼还有花园那么多地方能冲",
                recent_burst_count=5,
            ),
            "ignore",
        )

    def test_proactive_skips_low_signal_noise_messages(self):
        for noise in ("？", "??", "额", "呃呃呃呃", "1", "...", "。。。", "ok", "嗯"):
            with self.subTest(noise=noise):
                self.assertEqual(
                    replies.select_reply(False, True, 0.01, 600, text=noise),
                    "ignore",
                )

    def test_quote_self_ignores_hostile_bait_and_rapid_trolling_burst(self):
        for bait in ("丨", "煞笔", "区区区", "略略略", "这叫滚"):
            with self.subTest(bait=bait):
                self.assertEqual(
                    replies.select_reply(
                        False,
                        True,
                        0.01,
                        999,
                        quoted_self=True,
                        text=bait,
                    ),
                    "ignore",
                )
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.01,
                999,
                quoted_self=True,
                text="再来一句",
                recent_quote_count=2,
            ),
            "ignore",
        )

    def test_direct_image_uses_cooldown_and_probability_gate(self):
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.20,
                0,
                has_image=True,
                since_last_image=95.0,
            ),
            "image",
        )
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.80,
                0,
                has_image=True,
                since_last_image=95.0,
            ),
            "ignore",
        )
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.01,
                999,
                has_image=True,
                since_last_image=30.0,
            ),
            "ignore",
        )
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.01,
                999,
                has_image=True,
                since_last_image=300.0,
                duplicate_recent_image=True,
            ),
            "ignore",
        )

    def test_mention_ignores_severe_abuse_for_non_owner(self):
        self.assertEqual(
            replies.select_reply(
                True,
                True,
                0.01,
                999,
                text="臭婊子，去亖吧你",
            ),
            "ignore",
        )

    def test_owner_highest_authority_bypasses_bait_and_quote_burst_on_explicit_wake(self):
        self.assertEqual(
            replies.select_reply(
                True,
                True,
                0.99,
                0,
                text="闭嘴 测试一下",
                is_owner=True,
            ),
            "mention",
        )
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                quoted_self=True,
                text="闭嘴",
                recent_quote_count=5,
                is_owner=True,
            ),
            "quote_self",
        )
        # Non-wake owner message saying "人机闭嘴" should still stay quiet instead of replying back
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.01,
                999,
                text="人机闭嘴",
                is_owner=True,
            ),
            "ignore",
        )

    def test_followup_window_catches_one_unquoted_reply_from_recent_target(self):
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                text="我们交大有无限API，跟我吧",
                is_recent_reply_target=True,
                since_bot_replied_sender=26.0,
                followup_count=0,
            ),
            "followup",
        )
        # Capped after 1 unquoted follow-up turn
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                text="再说一句",
                is_recent_reply_target=True,
                since_bot_replied_sender=10.0,
                followup_count=1,
            ),
            "ignore",
        )
        # Expired after 45s
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                text="过了一分钟才回",
                is_recent_reply_target=True,
                since_bot_replied_sender=50.0,
                followup_count=0,
            ),
            "ignore",
        )
        # Quoting SOMEONE ELSE must NEVER trigger bot follow-up
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                text="没用 我叫他自由发挥就会很懒",
                is_recent_reply_target=True,
                since_bot_replied_sender=20.0,
                followup_count=0,
                is_quoting_other=True,
            ),
            "ignore",
        )
        # Ultra-short fragments without '?' (e.g. "可惜") wait instead of firing prematurely
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                text="可惜",
                is_recent_reply_target=True,
                since_bot_replied_sender=5.0,
                followup_count=0,
            ),
            "ignore",
        )
        # Short direct question ending with '？' still triggers follow-up
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                text="为啥？",
                is_recent_reply_target=True,
                since_bot_replied_sender=10.0,
                followup_count=0,
            ),
            "followup",
        )


if __name__ == "__main__":
    unittest.main()
