import importlib.util
import sys
import unittest
from pathlib import Path

PAT_PATH = (
    Path(__file__).parents[1]
    / "AstrBot/data/plugins/astrbot_plugin_wechat_native/pat.py"
)


def load_pat():
    spec = importlib.util.spec_from_file_location("wechat_native_pat", PAT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PatParserTest(unittest.TestCase):
    def test_xml_sysmsg_pat_targeting_bot(self):
        pat = load_pat()
        raw = {
            "id": "m1",
            "type": 10002,
            "direction": "incoming",
            "senderId": "",
            "body": (
                '<sysmsg type="pat"><pat>'
                "<fromusername>wxid_alice</fromusername>"
                "<chatusername>12345678901@chatroom</chatusername>"
                "<pattedusername>wxid_bot</pattedusername>"
                "<template><![CDATA[${wxid_alice} 拍了拍 ${wxid_bot} 的头]]></template>"
                "</pat></sysmsg>"
            ),
        }
        event = pat.parse_pat(raw, "wxid_bot", bot_names=("依都", "瀬尾 依都"))
        self.assertIsNotNone(event)
        self.assertTrue(event.target_is_self)
        self.assertEqual(event.sender_id, "wxid_alice")
        self.assertEqual(event.target_id, "wxid_bot")

    def test_appmsg_type_62_pat_targeting_bot(self):
        pat = load_pat()
        raw = {
            "id": "m2",
            "type": 49,
            "appMessageType": 62,
            "direction": "incoming",
            "senderId": "wxid_bob",
            "body": (
                "<msg><appmsg><type>62</type><patMsg>"
                "<chatUser>12345678901@chatroom</chatUser>"
                "<records><recordNum>2</recordNum>"
                "<record><fromUser>wxid_other</fromUser><pattedUser>wxid_bob</pattedUser><template>old</template></record>"
                "<record><fromUser>wxid_bob</fromUser><pattedUser>wxid_bot</pattedUser><template><![CDATA[老赵拍了拍我]]></template></record>"
                "</records></patMsg></appmsg></msg>"
            ),
        }
        event = pat.parse_pat(raw, "wxid_bot", bot_names=("依都",))
        self.assertIsNotNone(event)
        self.assertTrue(event.target_is_self)
        self.assertEqual(event.sender_id, "wxid_bob")

    def test_plain_system_notice_pat_targeting_me_and_custom_suffix(self):
        pat = load_pat()
        raw = {
            "id": "m3",
            "type": 10000,
            "direction": "system",
            "senderId": "",
            "body": '<_wc_custom_link_ href="weixin://">阿明</_wc_custom_link_> 拍了拍我的脑门并说别睡了',
        }
        event = pat.parse_pat(raw, "wxid_bot", bot_names=("依都",))
        self.assertIsNotNone(event)
        self.assertTrue(event.target_is_self)
        self.assertEqual(event.sender_name, "阿明")
        self.assertIn("拍了拍我的脑门并说别睡了", event.raw_text)

    def test_ignores_self_pat_and_other_members_pat_and_normal_text(self):
        pat = load_pat()
        # Bot patting someone else
        self.assertIsNone(
            pat.parse_pat(
                {"type": 10000, "direction": "system", "body": '你拍了拍"阿明"'},
                "wxid_bot",
                bot_names=("依都",),
            )
        )
        # Someone patting themselves
        self.assertIsNone(
            pat.parse_pat(
                {"type": 10000, "direction": "incoming", "body": '"阿明" 拍了拍自己'},
                "wxid_bot",
                bot_names=("依都",),
            )
        )
        # Someone patting another group member
        self.assertIsNone(
            pat.parse_pat(
                {"type": 10000, "direction": "incoming", "body": '"阿明" 拍了拍 "老赵"'},
                "wxid_bot",
                bot_names=("依都",),
            )
        )
        # Normal text message mentioning 拍了拍我 must NOT be treated as a pat
        self.assertIsNone(
            pat.parse_pat(
                {"type": 1, "direction": "incoming", "senderId": "wxid_a", "body": "哈哈他拍了拍我"},
                "wxid_bot",
                bot_names=("依都",),
            )
        )


if __name__ == "__main__":
    unittest.main()
