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
LOGS_DIR = ROOT / "logs"
WX_EXE = NATIVE_DIR / "wx-v2.7.1-win32-x64.exe"
API_TOKEN_FILE = NATIVE_DIR / "api-token"
BOT_TOKEN_FILE = NATIVE_DIR / "bot-token"
LOGIN_QR_PATH = NATIVE_DIR / "login.png"
NATIVE_STDERR = NATIVE_DIR / "native.stderr.log"
ASTRBOT_STDERR = LOGS_DIR / "astrbot.stderr.log"
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


def _port_open(port: int, timeout: float = 0.08) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def listeners() -> set[int]:
    """Check both ports concurrently so closed Windows loopback ports don't stall serially."""
    results: dict[int, bool] = {}

    def probe(p: int):
        results[p] = _port_open(p)

    threads = [threading.Thread(target=probe, args=(p,), daemon=True) for p in PORTS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=0.25)
    return {p for p, ok in results.items() if ok}


def _native_get(path: str, *, admin: bool = False, timeout: float = 1.5) -> bytes:
    token_file = API_TOKEN_FILE if admin else BOT_TOKEN_FILE
    token = token_file.read_text(encoding="utf-8").strip()
    req = urllib.request.Request(
        NATIVE_API_BASE + path,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def wechat_online_state() -> str:
    try:
        data = json.loads(_native_get(f"/accounts/{configured_account_id()}", timeout=1.5).decode("utf-8"))
        if data.get("authenticated") and data.get("connection") == "online":
            return "online"
        return "offline"
    except Exception:
        return "unknown"


def _tail_error(path: Path) -> str:
    try:
        if not path.is_file():
            return ""
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        return lines[-1][:90] if lines else ""
    except OSError:
        return ""


def probe_status_text() -> str:
    active = listeners()
    p_wx = 6174 in active
    p_bot = 6186 in active
    if p_wx and p_bot:
        wx_state = wechat_online_state()
        if wx_state == "online":
            return "全部就绪 · 微信小号已在线 (6174 + 6186)"
        if wx_state == "offline":
            return "服务已开启 · 微信未登录（请点「扫码登录」）"
        return "服务已开启 (6174 + 6186 运行中)"
    if p_wx and not p_bot:
        return "仅微信接入在线 (6174) · AstrBot (6186) 未运行"
    if p_bot and not p_wx:
        hint = _tail_error(NATIVE_STDERR)
        suffix = f"\n原因：{hint}" if hint else ""
        return f"仅 AstrBot 在线 (6186) · 微信接入 (6174) 未运行{suffix}"
    return "依都已关闭"


def _run_ps1(script_name: str, timeout: int = 20) -> tuple[int, str]:
    """Run a PowerShell script redirecting output to a log file (never a pipe) so
    detached child daemons (wx / AstrBot) cannot hold open stdout pipes and stall return."""
    script = ROOT / script_name
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = LOGS_DIR / "launcher.last.log"
    with out_file.open("w", encoding="utf-8", errors="ignore") as fp:
        proc = subprocess.run(
            [
                str(POWERSHELL),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=fp,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=timeout,
        )
    try:
        err = out_file.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        err = ""
    return proc.returncode, err


def main():
    window = tk.Tk()
    window.title("窗边来信 · 依都开关")
    window.resizable(False, False)
    panel = ttk.Frame(window, padding=20)
    panel.grid()
    status = tk.StringVar(value="正在检测服务状态…")
    busy = {"flag": False}
    refresh_in_flight = {"flag": False}

    def set_buttons(enabled: bool):
        state_flag = "!disabled" if enabled else "disabled"
        for btn in (start_btn, restart_btn, stop_btn, qr_btn):
            btn.state([state_flag])

    def finish(text: str):
        busy["flag"] = False
        status.set(text)
        set_buttons(True)

    def refresh_status_async():
        if not busy["flag"] and not refresh_in_flight["flag"]:
            refresh_in_flight["flag"] = True

            def worker():
                try:
                    text = probe_status_text()
                except Exception:
                    text = "状态检测异常"
                finally:
                    refresh_in_flight["flag"] = False
                if not busy["flag"]:
                    window.after(0, status.set, text)

            threading.Thread(target=worker, daemon=True).start()
        window.after(3000, refresh_status_async)

    def run_lifecycle(action: str):
        """action in {'start', 'stop', 'restart'} — fully off main GUI thread."""
        busy["flag"] = True
        set_buttons(False)
        labels = {"start": "正在开启依都…", "stop": "正在关闭依都…", "restart": "正在重启依都…"}
        status.set(labels[action])

        def worker():
            try:
                if action in ("stop", "restart"):
                    code, err = _run_ps1("Stop.ps1", timeout=15)
                    if code != 0 and action == "stop":
                        window.after(0, finish, f"关闭失败：{err[:90] or '请检查进程'}")
                        return
                    # Wait up to 4s for ports to clear
                    deadline = time.monotonic() + 4.0
                    while time.monotonic() < deadline and listeners():
                        time.sleep(0.15)
                    if action == "stop":
                        window.after(0, finish, "依都已关闭" if not listeners() else probe_status_text())
                        return
                    window.after(0, status.set, "已停止旧进程，正在重新启动…")

                # Start flow
                code, err = _run_ps1("Start.ps1", timeout=15)
                if code != 0:
                    msg = err.splitlines()[-1][:100] if err else "请检查日志"
                    window.after(0, finish, f"启动失败：{msg}")
                    return

                # Poll ports with live progress (AstrBot takes ~5-9s to cold-boot)
                deadline = time.monotonic() + 25.0
                while time.monotonic() < deadline:
                    active = listeners()
                    if active == set(PORTS):
                        window.after(0, finish, probe_status_text())
                        return
                    if 6174 in active and 6186 not in active:
                        window.after(0, status.set, "微信接入(6174)已就绪，正在等待 AstrBot 启动…")
                    elif 6186 in active and 6174 not in active:
                        hint = _tail_error(NATIVE_STDERR)
                        if hint:
                            window.after(0, finish, f"微信接入(6174)异常退出：{hint}")
                            return
                    time.sleep(0.25)
                window.after(0, finish, probe_status_text())
            except Exception as exc:
                window.after(0, finish, f"操作出错：{type(exc).__name__}")

        threading.Thread(target=worker, daemon=True).start()

    def start_qr_login():
        busy["flag"] = True
        set_buttons(False)
        status.set("正在检查微信接入并生成二维码…")

        def worker():
            try:
                if 6174 not in listeners():
                    window.after(0, finish, "请先点击「开启依都」，等 6174 就绪后再扫码")
                    return
                proc = subprocess.run(
                    [
                        str(WX_EXE),
                        "--server",
                        "http://127.0.0.1:6174",
                        "--token-file",
                        str(API_TOKEN_FILE),
                        "--account",
                        configured_account_id(),
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
                            f"/accounts/{configured_account_id()}/operations/{op_id}", admin=True, timeout=3.0
                        ).decode("utf-8")
                    )
                    state = cur.get("state")
                    res = cur.get("result") or {}
                    if state == "awaiting_scan" and res.get("qrAvailable") and not qr_shown:
                        img = _native_get(
                            f"/accounts/{configured_account_id()}/operations/{op_id}/qr", admin=True, timeout=3.0
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

    start_btn = ttk.Button(panel, text="开启依都", command=lambda: run_lifecycle("start"))
    restart_btn = ttk.Button(panel, text="重启依都", command=lambda: run_lifecycle("restart"))
    stop_btn = ttk.Button(panel, text="关闭依都", command=lambda: run_lifecycle("stop"))
    qr_btn = ttk.Button(panel, text="扫码登录", command=start_qr_login)
    open_ui = ttk.Button(
        panel, text="管理面板", command=lambda: webbrowser.open(DASHBOARD_URL)
    )
    open_logs = ttk.Button(
        panel, text="查看日志", command=lambda: os.startfile(str(LOGS_DIR))
    )

    start_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")
    restart_btn.grid(row=0, column=1, padx=3, sticky="ew")
    stop_btn.grid(row=0, column=2, padx=(6, 0), sticky="ew")
    qr_btn.grid(row=1, column=0, columnspan=3, pady=(10, 0), sticky="ew")
    open_ui.grid(row=2, column=0, columnspan=2, padx=(0, 6), pady=(10, 0), sticky="ew")
    open_logs.grid(row=2, column=2, padx=(6, 0), pady=(10, 0), sticky="ew")

    ttk.Label(panel, textvariable=status, wraplength=340, justify="center").grid(
        row=3, column=0, columnspan=3, pady=(14, 0)
    )

    window.after(50, refresh_status_async)
    window.mainloop()


if __name__ == "__main__":
    main()
