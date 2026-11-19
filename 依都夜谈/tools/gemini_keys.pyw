import json
import os
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


def save_keys(config_path, free_key, paid_key):
    if not free_key or not paid_key or free_key == paid_key:
        raise ValueError("请分别填入免费项目和付费项目的两把不同 Key。")

    original = config_path.read_bytes()
    config = json.loads(original.decode("utf-8-sig"))
    source = next(
        (item for item in config["provider_sources"] if item["id"] == "google_gemini"),
        None,
    )
    if source is None:
        raise ValueError("配置里找不到 google_gemini，请联系维护者。")
    source["key"] = [free_key, paid_key]
    source["gm_rate_limit_fallback"] = True

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=config_path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.close()
            if config_path.read_bytes() != original:
                raise ValueError("配置刚被其他操作更新，请再次点击保存。")
            os.replace(temporary, config_path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    config_path = Path(__file__).resolve().parents[1] / "AstrBot/data/cmd_config.json"
    window = tk.Tk()
    window.title("依都 · 填写 Gemini 双 Key")
    window.resizable(False, False)
    panel = ttk.Frame(window, padding=20)
    panel.grid()

    ttk.Label(panel, text="免费项目（Free tier）的 API Key").grid(sticky="w")
    free_entry = ttk.Entry(panel, width=56, show="*")
    free_entry.grid(sticky="ew", pady=(4, 12))
    ttk.Label(panel, text="付费项目（Tier 1）的 API Key").grid(sticky="w")
    paid_entry = ttk.Entry(panel, width=56, show="*")
    paid_entry.grid(sticky="ew", pady=(4, 12))

    def save():
        try:
            save_keys(config_path, free_entry.get().strip(), paid_entry.get().strip())
        except ValueError as exc:
            messagebox.showerror("保存失败", str(exc), parent=window)
            return
        except OSError:
            messagebox.showerror(
                "保存失败", "无法写入本机配置，请再试一次。", parent=window
            )
            return
        messagebox.showinfo(
            "已保存", "两把 Key 已保存到本机配置，重启依都后生效。", parent=window
        )
        window.destroy()

    ttk.Button(panel, text="保存到本机", command=save).grid(sticky="e")
    window.bind("<Return>", lambda _event: save())
    free_entry.focus_set()
    window.mainloop()


if __name__ == "__main__":
    main()
