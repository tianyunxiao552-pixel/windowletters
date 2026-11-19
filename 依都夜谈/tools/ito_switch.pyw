import json
import os
import socket
import subprocess
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parents[1]
NATIVE_DIR = ROOT / "agent-wechat"
WX_EXE = NATIVE_DIR / "wx-v2.7.1-win32-x64.exe"
API_TOKEN_FILE = NATIVE_DIR / "api-token"
BOT_TOKEN_FILE = NATIVE_DIR / "bot-token"
LOGIN_QR_PATH = NATIVE_DIR / "login.png"
NATIVE_API_BASE = "http://127.0.0.1:6174/v1"

POWERSHELL = (
    Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
)
PORTS = (6174, 6186)
DASHBOARD_URL = "http://127.0.0.1:6186"


def configured_account_id():
    config_path = ROOT / "AstrBot/data/cmd_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    platform = next(item for item in config["platform"] if item["id"] == "ito_wechat")
    account_id = platform.get("account_id")
    if not account_id:
        raise ValueError("请先在 AstrBot 中填写微信账号 ID")
    return account_id


def listeners():
    active = set()
    for port in PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                active.add(port)
        except OSError:
            pass
    return active


def _native_get(path, *, admin=False):
    token_file = API_TOKEN_FILE if admin else BOT_TOKEN_FILE
    token = token_file.read_text(encoding="utf-8").strip()
    req = urllib.request.Request(
        NATIVE_API_BASE + path,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        return resp.read()


def wechat_online_state():
    try:
        data = json.loads(_native_get(f"/accounts/{configured_account_id()}").decode("utf-8"))
        if data.get("authenticated") and data.get("connection") == "online":
            return "online"
        return "offline"
    except Exception:
        return "unknown"


def main():
    window = tk.Tk()
    window.title("窗边来信 · 依都开关")
    window.resizable(False, False)
    panel = ttk.Frame(window, padding=22)
    panel.grid()
    status = tk.StringVar()
    busy = {"flag": False}

    def describe(active):
        if len(active) == len(PORTS):
            wx_state = wechat_online_state()
            if wx_state == "online":
                return "服务已开启 · 微信小号已在线"
            if wx_state == "offline":
                return "服务已开启 · 微信未登录（点「扫码登录」）"
            return "服务已开启（微信接入 + AstrBot 均运行中）"
        if active:
            return "部分服务正在运行"
        return "依都已关闭"

    def refresh_status():
        if not busy["flag"]:
            status.set(describe(listeners()))
        window.after(3000, refresh_status)

    ttk.Label(panel, textvariable=status, wraplength=320).grid(
        row=3, column=0, columnspan=2, pady=(14, 0)
    )
    status.set(describe(listeners()))

    def set_buttons(enabled):
        state_flag = "!disabled" if enabled else "disabled"
        for btn in (start, stop, qr_login):
            btn.state([state_flag])

    def finish(text):
        busy["flag"] = False
        status.set(text)
        set_buttons(True)

    def launch(starting):
        busy["flag"] = True
        set_buttons(False)
        status.set("正在开启…" if starting else "正在关闭…")
        script = ROOT / ("Start.ps1" if starting else "Stop.ps1")
        operation = "开启" if starting else "关闭"
        try:
            process = subprocess.Popen(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    script,
                ],
                cwd=ROOT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            finish(f"{operation}失败，请检查本地启动脚本")
            return

        def poll_process():
            result = process.poll()
            if result is None:
                window.after(150, poll_process)
            elif result:
                finish(f"{operation}失败，可以再试一次")
            else:
                poll_listeners(time.monotonic() + 20)

        def poll_listeners(deadline):
            active_ports = listeners()
            expected = set(PORTS) if starting else set()
            if active_ports == expected:
                finish(describe(active_ports) if starting else "依都已关闭")
            elif time.monotonic() < deadline:
                window.after(250, poll_listeners, deadline)
            else:
                finish(f"{operation}未确认，请检查本机服务")

        window.after(150, poll_process)

    def start_qr_login():
        if 6174 not in listeners():
            status.set("请先点击「开启依都」，再点扫码登录")
            return
        busy["flag"] = True
        set_buttons(False)
        status.set("正在生成微信登录二维码…")

        def worker():
            try:
                proc = subprocess.run(
                    [
                        str(WX_EXE),
                        "--server",
                        "http://127.0.0.1:6174",
                        "--token-file",
                        str(API_TOKEN_FILE),
                        "--account",
                        "ito",
                        "auth",
                        "login",
                        "--force-qr",
                        "--detach",
                        "--json",
                    ],
                    cwd=NATIVE_DIR,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=15,
                )
                if proc.returncode != 0:
                    msg = (proc.stderr or proc.stdout or "无法发起登录").strip()
                    window.after(0, finish, f"发起登录失败：{msg[:80]}")
                    return
                op = json.loads(proc.stdout)
                op_id = op["id"]
                deadline = time.monotonic() + 240
                qr_shown = False
                while time.monotonic() < deadline:
                    cur = json.loads(
                        _native_get(
                            f"/accounts/{configured_account_id()}/operations/{op_id}", admin=True
                        ).decode("utf-8")
                    )
                    state = cur.get("state")
                    res = cur.get("result") or {}
                    if state == "awaiting_scan" and res.get("qrAvailable") and not qr_shown:
                        img = _native_get(
                            f"/accounts/{configured_account_id()}/operations/{op_id}/qr", admin=True
                        )
                        LOGIN_QR_PATH.write_bytes(img)
                        os.startfile(str(LOGIN_QR_PATH))
                        qr_shown = True
                        window.after(0, status.set, "二维码已弹出，请用微信小号扫码并确认")
                    elif state == "authenticating":
                        window.after(0, status.set, "已扫码，正在手机确认登录…")
                    elif state == "succeeded":
                        window.after(0, finish, "微信小号登录成功，已在线！")
                        return
                    elif state in {"failed", "expired", "cancelled"}:
                        code = res.get("code") or state
                        window.after(0, finish, f"登录未完成（{code}），可再点一次重试")
                        return
                    time.sleep(0.8)
                window.after(0, finish, "扫码超时，请重新点击「扫码登录」")
            except Exception as exc:
                window.after(0, finish, f"扫码登录出错：{type(exc).__name__}")

        threading.Thread(target=worker, daemon=True).start()

    start = ttk.Button(panel, text="开启依都", command=lambda: launch(True))
    stop = ttk.Button(panel, text="关闭依都", command=lambda: launch(False))
    qr_login = ttk.Button(panel, text="扫码登录", command=start_qr_login)
    open_ui = ttk.Button(
        panel, text="管理面板", command=lambda: webbrowser.open(DASHBOARD_URL)
    )
    open_logs = ttk.Button(
        panel, text="查看日志", command=lambda: os.startfile(str(ROOT / "logs"))
    )

    start.grid(row=0, column=0, padx=(0, 8), sticky="ew")
    stop.grid(row=0, column=1, padx=(8, 0), sticky="ew")
    qr_login.grid(row=1, column=0, columnspan=2, pady=(10, 0), sticky="ew")
    open_ui.grid(row=2, column=0, padx=(0, 8), pady=(10, 0), sticky="ew")
    open_logs.grid(row=2, column=1, padx=(8, 0), pady=(10, 0), sticky="ew")

    window.after(3000, refresh_status)
    window.mainloop()


if __name__ == "__main__":
    main()
