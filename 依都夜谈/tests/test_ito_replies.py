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
            replies.select_reply(False, True, 0.269, 300, text="今晚航天绝密缺个报点的"),
            "proactive",
        )
        self.assertEqual(
            replies.select_reply(False, True, 0.27, 300, text="今晚航天绝密缺个报点的"),
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

    def test_direct_image_bypasses_dice_roll_with_short_cooldown(self):
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.99,
                0,
                has_image=True,
                since_last_image=20.0,
            ),
            "image",
        )
        self.assertEqual(
            replies.select_reply(
                False,
                True,
                0.01,
                999,
                has_image=True,
                since_last_image=5.0,
            ),
            "ignore",
        )


    def test_mention_ignores_severe_abuse(self):
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


if __name__ == "__main__":
    unittest.main()
