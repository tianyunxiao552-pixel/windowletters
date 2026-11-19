import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

NATIVE_DIR = Path(__file__).parents[1] / "AstrBot/data/plugins/astrbot_plugin_wechat_native"


def load_native_module(name: str):
    if "wechat_native_testpkg" not in sys.modules:
        import types
        pkg = types.ModuleType("wechat_native_testpkg")
        pkg.__path__ = [str(NATIVE_DIR)]
        sys.modules["wechat_native_testpkg"] = pkg
    spec = importlib.util.spec_from_file_location(f"wechat_native_testpkg.{name}", NATIVE_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class LoopGuardGroupStabilityTest(unittest.TestCase):
    def test_segmented_bubbles_for_same_trigger_count_as_one_reply_in_group(self):
        state_mod = load_native_module("state")
        lg_mod = load_native_module("loop_guard")
        with tempfile.TemporaryDirectory() as tmp:
            state = state_mod.StateStore(Path(tmp) / "state.sqlite3")
            clock = [1000.0]
            guard = lg_mod.LoopGuard(state, "acct", clock=lambda: clock[0])
            try:
                # 6 distinct incoming group messages, each replied with 3 segmented bubbles (18 sends total).
                # Previously this tripped hard_limit at send #8 (on message #3)!
                for i in range(6):
                    trig = f"in-{i}"
                    guard.incoming("12345678901@chatroom", trig, f"不同话题消息 {i}")
                    for b in range(3):
                        guard.outgoing(
                            "12345678901@chatroom",
                            f"send-{i}-{b}",
                            f"分段回复 {i} 段 {b}",
                            trigger=trig,
                        )
                self.assertFalse(guard.blocked("12345678901@chatroom"))
            finally:
                state.close()

    def test_group_cooldown_is_shorter_than_ten_minutes(self):
        state_mod = load_native_module("state")
        lg_mod = load_native_module("loop_guard")
        with tempfile.TemporaryDirectory() as tmp:
            state = state_mod.StateStore(Path(tmp) / "state.sqlite3")
            clock = [1000.0]
            guard = lg_mod.LoopGuard(state, "acct", clock=lambda: clock[0])
            try:
                guard.trip("12345678901@chatroom", "hard_limit")
                self.assertTrue(guard.blocked("12345678901@chatroom"))
                clock[0] += 95.0
                self.assertFalse(guard.blocked("12345678901@chatroom"))
            finally:
                state.close()


if __name__ == "__main__":
    unittest.main()
