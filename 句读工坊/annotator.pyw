import json
import os
import re
import sqlite3
import tkinter as tk
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from tkinter import filedialog, messagebox, ttk
from unicodedata import category


ROOT = Path(__file__).resolve().parent
WECHAT_EXPORTS = ROOT.parent / "拾信" / "exports"
WECHAT_JSON = "chat_full_parsed.json"
FONT = "Microsoft YaHei UI"
INK, MUTED, GREEN, PAPER = "#173b36", "#536963", "#17634f", "#f4f6f1"
TIME = r"(?:(?:\d{4}[-/]\d{1,2}[-/]\d{1,2})[ T])?\d{1,2}:\d{2}(?::\d{2})?"
STAMP = rf"(?:\[({TIME})\]|({TIME}))"
LINE = re.compile(rf"^(?:{STAMP}\s*)?([^：:\n]{{1,80}}?)[：:]\s?(.*)$")
HEADER = re.compile(rf"^(?:{STAMP}\s+([^：:\n]+?)|([^：:\n]+?)\s+({TIME}))$")
GUIDE = "根据群聊前文，以目标说话人的口吻接话。参考示例中的措辞、节奏和分寸，按当前话题自然回复。"
EXAMPLE = """阿宁：周五吃火锅，有人报名吗
小满：我六点能到
我：算我一个
我：先说好，微辣是我的上限
阿宁：那就鸳鸯锅
小满：谁带上次那副牌？
我：在我这儿，我带"""


def parse_chat(raw):
    messages, current = [], None
    for number, line in enumerate(raw.lstrip("\ufeff").splitlines(), 1):
        if not line.strip():
            continue
        # Indented lines explicitly continue the preceding message.
        header = HEADER.fullmatch(line) if not line[:1].isspace() else None
        expecting_body = current is not None and current[2] == ""
        item = LINE.match(line) if not header and not expecting_body and not line[:1].isspace() else None
        if header or item:
            if current and not current[2].strip():
                raise ValueError(f"第 {number} 行之前有一条空消息，请补全或删去该行。")
            if header:
                a, b, name, other, c = header.groups()
                current = [a or b or c, (name or other).strip(), ""]
            else:
                a, b, name, body = item.groups()
                current = [a or b or "", name.strip(), body]
            messages.append(current)
        elif current:
            current[2] = (current[2] + "\n" + line.strip()).lstrip("\n")
        else:
            raise ValueError(f"第 {number} 行无法识别发言人。可使用「昵称：消息」，或「时间 昵称」下一行写消息。")
    if not messages or not messages[-1][2].strip():
        raise ValueError("请至少输入一条带昵称和正文的完整消息。")
    return messages


def wechat_files(folder):
    direct = folder / WECHAT_JSON
    if direct.is_file():
        return [direct]
    return sorted(folder.glob("*/" + WECHAT_JSON), key=lambda p: p.parent.name)


def read_wechat(path, kinds=None):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise ValueError("文件里没有微信导出的 messages 消息列表。")
    messages, targets = [], set()
    for pos, item in enumerate(data["messages"], 1):
        if not isinstance(item, dict) or "is_self" not in item:
            raise ValueError(f"第 {pos} 条消息缺少发言人身份标记。")
        own = item["is_self"] is True
        kind = item.get("type") or "消息"
        sender = "我" if own else (item.get("sender") or "未知发言人")
        if not own and sender == "我":
            sender = "我（其他成员）"
        stamp = item.get("time") or ""
        body = item.get("content") or f"[{kind}]"
        usable = kind == "文本" and bool((item.get("content") or "").strip())
        if kind == "语音" and isinstance(item.get("transcript"), str) and item["transcript"].strip():
            body = item["transcript"]
            usable = True
        if own and kind == "文件/链接/卡片":
            reply, marker, quote = body.partition("\n    ↳ 引用 ")
            if marker and reply.strip():
                messages.append([stamp, "微信引用", quote.strip()])
                if kinds is not None:
                    kinds.append("引用前文")
                body, usable = reply, True
        if own and usable:
            targets.add(len(messages))
        messages.append([stamp, sender, body])
        if kinds is not None:
            kinds.append(kind)
    return data.get("chat_name") or path.parent.name, messages, targets, len(data["messages"]), data.get("chat_type")


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, transcript TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY, chat INTEGER NOT NULL, start INTEGER NOT NULL, stop INTEGER NOT NULL,
                context TEXT NOT NULL, reply TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '待标注');
            CREATE INDEX IF NOT EXISTS sample_chat ON samples(chat, start);
            CREATE TABLE IF NOT EXISTS message_types (chat INTEGER PRIMARY KEY, kinds TEXT NOT NULL);
        """)

    def add(self, name, owner, messages, targets=None):
        wechat = targets is not None
        if targets is None:
            targets = {i for i, msg in enumerate(messages) if msg[1] == owner}
        with self.db:
            chat = self.db.execute("INSERT INTO chats(name,owner,transcript) VALUES(?,?,?)",
                                   (name, owner, json.dumps(messages, ensure_ascii=False))).lastrowid
            i = 0
            while i < len(messages):
                if i not in targets:
                    i += 1
                    continue
                start = i
                i += 1
                while i in targets:
                    if wechat and messages[i][0][:10] != messages[i-1][0][:10]:
                        break
                    i += 1
                self.db.execute("INSERT INTO samples(chat,start,stop,context,reply) VALUES(?,?,?,?,?)",
                                (chat, start, i, json.dumps(list(range(max(0, start-8), start))),
                                 "\n".join(m[2] for m in messages[start:i])))
        return chat

    def samples(self, chat):
        return self.db.execute("SELECT * FROM samples WHERE chat=? ORDER BY start", (chat,)).fetchall()

    def save(self, sid, ids, reply, note, status):
        with self.db:
            self.db.execute("UPDATE samples SET context=?, reply=?, note=?, status=? WHERE id=?",
                            (json.dumps(sorted(ids)), reply, note, status, sid))


def export_text(samples, messages, owner, markdown):
    lines = ["# 我的群聊回复示例", GUIDE, "每组示例的「我的回复」是模仿目标，前文保留了当时的发言人。"] if markdown else []
    for i, row in enumerate(samples, 1):
        selected = [messages[k] for k in json.loads(row["context"])]
        context = "\n".join(f"{'我（此前发言）' if n == owner else n}：{body}" for _, n, body in selected)
        context = context or "（没有选取前文）"
        if markdown:
            lines.extend([f"## 示例 {i}", "群聊前文", context, "我的回复", row["reply"]])
            if row["note"].strip():
                lines.extend(["我的标注", row["note"].strip()])
        else:
            record = {"messages": [{"role": "system", "content": GUIDE},
                                   {"role": "user", "content": context},
                                   {"role": "assistant", "content": row["reply"]}]}
            lines.append(json.dumps(record, ensure_ascii=False))
    return ("\n\n" if markdown else "\n").join(lines) + "\n"


# WeChat's bracketed faces and standalone Unicode emoji are not spoken replies.
MEDIA_ONLY = re.compile(
    r"(?:\s|\[[^\[\]\n]{1,12}\]|[\U0001F000-\U0001FAFF\u2600-\u27bf"
    r"\u200d\ufe0e\ufe0f\u20e3]|[0-9#*]\ufe0f?\u20e3)+"
)


def recent_context(messages, start):
    if start and messages[start-1][1] == "微信引用":
        return [start-1]
    ids = []
    try:
        at = datetime.fromisoformat(messages[start][0])
    except ValueError:
        at = None
    for i in range(start-1, max(-1, start-9), -1):
        stamp, sender, body = messages[i]
        if at and stamp:
            try:
                if at - datetime.fromisoformat(stamp) > timedelta(minutes=10):
                    break
            except ValueError:
                pass
        if sender not in ("微信引用", "系统", "系统消息") and body.strip():
            ids.append(i)
    return ids[::-1]


def reaction(body, kind=None):
    """Recognise standalone reactions without treating [图片] or [语音] as faces."""
    text = body.strip()
    if kind == "动画表情":
        return True
    if kind not in (None, "文本"):
        return False
    if text in {"[图片]", "[语音]", "[视频]", "[文件]", "[链接]", "[位置]", "[卡片]", "[视频号]"}:
        return False
    return bool(text and MEDIA_ONLY.fullmatch(text))


def phrase_list(counter, limit=8):
    return "、".join(f"「{s}」{n} 次" for s, n in counter.most_common(limit) if n >= 2)


def habit_document(samples, ready, messages, owner, name, kinds):
    skipped = {i for r in samples if r["status"] == "已跳过" for i in range(r["start"], r["stop"])}
    own = [i for i, (_, sender, _) in enumerate(messages) if sender == owner and i not in skipped]
    written = [messages[i][2].strip() for r in samples if r["status"] != "已跳过"
               for i in range(r["start"], r["stop"]) if messages[i][2].strip() and not MEDIA_ONLY.fullmatch(messages[i][2].strip())]
    reactions = [i for i in own if reaction(messages[i][2], kinds[i] if kinds else None)]
    if not ready and not reactions:
        raise ValueError("这段记录没有可用的本人文字或表情。")
    lines = [f"# {name} · 我的说话习惯和接话范例", "", "## 我的说话习惯", "",
             f"这份画像来自本会话的 {len(own)} 条本人消息。其中可用于分析措辞的文字气泡有 {len(written)} 条，"
             f"单独发送表情的消息有 {len(reactions)} 条。统计已排除手动跳过的回复。"]
    if written:
        lengths = sorted(map(len, written))
        n = len(lengths)
        def pct(count):
            return f"{count}/{n}（{count/n:.1%}）"
        lines += ["", f"- **长短**　每个文字气泡的长度中位数是 {median(lengths):g} 个字符。"
                  f"单字符回复占 {pct(lengths.count(1))}。",
                  f"- **收尾**　以「。」收尾的占 {pct(sum(s.endswith('。') for s in written))}，"
                  f"以问号收尾的占 {pct(sum(s.endswith(('?', '？')) for s in written))}，"
                  f"末尾没有标点的占 {pct(sum(not category(s[-1]).startswith('P') for s in written))}。"]
        phrases = phrase_list(Counter(s for s in written if len(s) <= 16 and "\n" not in s))
        if phrases:
            lines.append(f"- **反复用过的短回复**　{phrases}。次数按整条消息完全相同计算。")
        particles = Counter()
        for s in written:
            tail = s.rstrip("。！？!?~～…，, ")
            if tail and tail[-1] in "啊呀呢吧嘛哦哈啦哇吗呗诶":
                particles[tail[-1]] += 1
        if endings := phrase_list(particles):
            lines.append(f"- **常见句尾字**　{endings}。")
    else:
        lines.append("本段记录没有足够的文字可统计句长、标点或口头禅。")
    if kinds:
        stickers = sum(kinds[i] == "动画表情" for i in own)
        if stickers:
            lines.append(f"- **微信动画表情**　在 {len(own)} 条本人消息中单独发过 {stickers} 条动画表情，占 {stickers/len(own):.1%}。")
    runs = Counter()
    previous = None
    size = 0
    for i in own:
        consecutive = previous is not None and (
            i == previous+1 or (i == previous+2 and messages[i-1][1] == "微信引用"))
        if consecutive:
            try:
                gap = datetime.fromisoformat(messages[i][0]) - datetime.fromisoformat(messages[previous][0])
                consecutive = timedelta(0) <= gap <= timedelta(minutes=3)
            except ValueError:
                pass
        if not consecutive and size:
            runs[size] += 1
            size = 0
        size += 1
        previous = i
    if size:
        runs[size] += 1
    if runs:
        lines.append(f"- **分条节奏**　共 {sum(runs.values())} 次连续发言，其中只发一条 {runs[1]} 次，"
                     f"连发两条 {runs[2]} 次，三条及以上 {sum(v for k,v in runs.items() if k>=3)} 次。"
                     "按相邻本人消息统计；有完整时间时，间隔超过三分钟另算一次。")

    examples = []
    included_indices = set()
    for row in ready:
        ids = json.loads(row["context"])
        original = [msg[2] for msg in messages[row["start"]:row["stop"]]]
        bubbles = original if row["reply"] == "\n".join(original) else [row["reply"]]
        quote_id = row["start"]-1
        quoted = quote_id in ids and messages[quote_id][1] == "微信引用"
        peer = [i for i in ids if messages[i][1] not in (owner, "微信引用")]
        if quoted:
            group = "引用接话"
        elif len(bubbles) > 1:
            group = "分条连发"
        elif peer and messages[peer[-1]][2].rstrip().endswith(("？","?","吗","么")):
            group = "前文有提问"
        else:
            group = "日常发言"
        basis = ("手动选定的前文" if row["status"] == "已确认" else
                 "明确引用" if quoted else "按时间相邻，回复对象未确认" if ids else "无可用前文")
        examples.append((row["start"], group, ids, bubbles, basis, row["note"]))
        included_indices.update(range(row["start"], row["stop"]))
    for i in reactions:
        # A reaction inside an exported reply already appears as its own bubble.
        if i in included_indices:
            continue
        ids = recent_context(messages, i)
        examples.append((i, "发送表情", ids, [messages[i][2]], "记录中的表情动作，按相邻前文展示", ""))
    lines += ["", "## 怎么用这些范例接话", "",
              "收到新群聊时，先找接法相近的一组。例如有人追问时看提问前文，点名引用时看引用接话。"
              "沿用相近的口吻和分条节奏，用眼前话题的内容续写。频数用来掌握分寸，口头禅不用每句都加。"
              "表情占位符表示当时发送了表情，无法从占位符判断具体表情。", ""]
    examples.sort(key=lambda entry: entry[0])
    lines.extend([f"以下为全部 {len(examples)} 组范例，按聊天顺序排列。", ""])
    for number, (_, kind, ids, bubbles, basis, note) in enumerate(examples, 1):
        lines.extend([f"## 示例 {number} · {kind}", "", basis, ""])
        context = [f"{messages[i][1]}：{messages[i][2]}" for i in ids]
        for content in context or ["（这条发言没有可用前文）"]:
            lines.extend("> " + part for part in content.split("\n"))
            lines.append(">")
        for pos, body in enumerate(bubbles, 1):
            lines.extend([f"**我 · 第 {pos} 条**", "", body, ""])
        if note:
            lines.extend(["我的标注：" + note, ""])
    return "\n".join(lines).rstrip()+"\n", len(examples)


def generate_examples(samples, messages, owner, name, destination, kinds=None):
    ready = []
    for row in samples:
        reply = row["reply"].strip()
        if row["status"] == "已跳过" or not reply:
            continue
        record = dict(row)
        if row["status"] != "已确认":
            if MEDIA_ONLY.fullmatch(reply):
                continue
            start = row["start"]
            initial = list(range(max(0, start-8), start))
            if json.loads(row["context"]) == initial:
                record["context"] = json.dumps(recent_context(messages, start))
        original = [m[2] for m in messages[row["start"]:row["stop"]]]
        # Old imports can group adjacent messages hours apart. Keep manual edits intact.
        if (row["status"] == "待标注" and not row["note"] and row["reply"] == "\n".join(original)
                and json.loads(row["context"]) == list(range(max(0, row["start"]-8), row["start"]))):
            starts = [row["start"]]
            for i in range(row["start"]+1, row["stop"]):
                try:
                    gap = datetime.fromisoformat(messages[i][0]) - datetime.fromisoformat(messages[i-1][0])
                except ValueError:
                    continue
                if gap > timedelta(minutes=3):
                    starts.append(i)
            if len(starts) > 1:
                for a, b in zip(starts, starts[1:]+[row["stop"]]):
                    body = "\n".join(m[2] for m in messages[a:b])
                    if body.strip() and not MEDIA_ONLY.fullmatch(body):
                        ready.append(dict(record, start=a, stop=b, reply=body,
                                          context=json.dumps(recent_context(messages, a))))
                continue
        ready.append(record)
    document, count = habit_document(samples, ready, messages, owner, name, kinds)
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:75]
    folder = destination / (safe_name + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    folder.mkdir(parents=True)
    (folder / "给AI的聊天示例.md").write_text(document, encoding="utf-8")
    if ready:
        (folder / "训练数据.jsonl").write_text(export_text(ready, messages, owner, False), encoding="utf-8")
    return folder, count


def editor(parent, **kwargs):
    return tk.Text(parent, font=(FONT, 11), bg="white", fg=INK, insertbackground=INK, relief="flat",
                   highlightthickness=1, highlightbackground="#c7d3ca", wrap="word", padx=9, pady=6,
                   undo=True, **kwargs)


class WechatDialog(tk.Toplevel):
    def __init__(self, app, folder=WECHAT_EXPORTS):
        super().__init__(app)
        self.app = app
        self.paths = []
        self.source = None
        self.title("导入微信记录")
        self.geometry("630x395")
        self.transient(app)
        self.grab_set()
        pane = ttk.Frame(self, padding=18)
        pane.pack(fill="both", expand=True)
        ttk.Label(pane, text="选择微信会话", style="Head.TLabel").pack(anchor="w")
        bar = ttk.Frame(pane)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="选择导出目录…", command=self.choose_folder).pack(side="right")
        self.location = tk.StringVar()
        ttk.Label(bar, textvariable=self.location, wraplength=380).pack(side="left")
        self.listing = tk.Listbox(pane, height=5, exportselection=False, font=(FONT, 11))
        self.listing.pack(fill="both", expand=True)
        self.listing.bind("<<ListboxSelect>>", lambda _: self.preview())
        self.info = tk.StringVar()
        ttk.Label(pane, textvariable=self.info, wraplength=570).pack(anchor="w", pady=8)
        actions = ttk.Frame(pane)
        actions.pack(fill="x")
        self.generate = ttk.Button(actions, text="生成说话习惯和接话范例", style="Accent.TButton",
                                   command=lambda: self.submit(generate=True))
        self.generate.pack(side="right")
        self.start = ttk.Button(actions, text="手动标注", command=self.submit)
        self.start.pack(side="right", padx=8)
        self.set_folder(folder)

    def choose_folder(self):
        value = filedialog.askdirectory(parent=self, initialdir=self.folder if self.folder.is_dir() else ROOT)
        if value:
            self.set_folder(Path(value))

    def set_folder(self, folder):
        self.folder = folder
        self.location.set(str(folder))
        self.paths = wechat_files(folder)
        self.listing.delete(0, "end")
        for path in self.paths:
            self.listing.insert("end", path.parent.name)
        if self.paths:
            self.listing.selection_set(0)
        self.preview()

    def preview(self):
        self.source = None
        self.start.configure(state="disabled")
        self.generate.configure(state="disabled")
        selection = self.listing.curselection()
        if not selection:
            self.info.set("请选择 exports 总目录，或含 chat_full_parsed.json 的单个会话目录。")
            return
        try:
            self.kinds = []
            self.source = read_wechat(self.paths[selection[0]], self.kinds)
        except (ValueError, OSError) as err:
            self.info.set(f"无法读取这份记录：{err}")
            return
        _, messages, targets, count, chat_type = self.source
        kind = {"group": "群聊", "private": "私聊"}.get(chat_type, "会话")
        if not targets:
            faces = sum(sender == "我" and reaction(body, k) for (_, sender, body), k in zip(messages, self.kinds))
            if faces:
                self.generate.configure(state="normal")
                self.info.set(f"{kind} · 共 {count} 条消息，你发了 {faces} 条独立表情，可生成表情使用记录和范例。")
            else:
                self.info.set(f"{kind} · 共 {count} 条消息。没有识别到你的文字或表情。")
            return
        self.info.set(f"{kind} · 共 {count} 条消息，已识别你的 {len(targets)} 条可读发言。选好会话后直接生成即可。")
        self.start.configure(state="normal")
        self.generate.configure(state="normal")

    def submit(self, generate=False):
        if self.source and (self.source[2] or generate):
            name, messages, targets, _, _ = self.source
            existing = self.app.store.db.execute(
                "SELECT id FROM chats WHERE name=? AND owner=? AND transcript=? ORDER BY id DESC LIMIT 1",
                (name, "我", json.dumps(messages, ensure_ascii=False))).fetchone()
            cid = existing["id"] if existing else self.app.store.add(name, "我", messages, targets)
            with self.app.store.db:
                self.app.store.db.execute("INSERT OR REPLACE INTO message_types VALUES (?,?)",
                                          (cid, json.dumps(self.kinds, ensure_ascii=False)))
            self.destroy()
            self.app.open_chat(cid)
            if generate:
                self.app.auto_export()


class ImportDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("导入群聊记录")
        self.geometry("710x580")
        self.transient(app)
        self.grab_set()
        pad = ttk.Frame(self, padding=20)
        pad.pack(fill="both", expand=True)
        ttk.Label(pad, text="导入一段群聊", style="Head.TLabel").pack(anchor="w")
        ttk.Label(pad, text="每行写成「昵称：消息」。支持带时间的发言；缩进行会接到上一条。").pack(anchor="w", pady=6)
        bar = ttk.Frame(pad)
        bar.pack(fill="x", pady=5)
        ttk.Button(bar, text="打开 TXT 文件", command=self.load).pack(side="left")
        ttk.Button(bar, text="填入示例", command=lambda: self.replace(EXAMPLE, "火锅局（示例）")).pack(side="left", padx=6)
        self.raw = editor(pad, height=10)
        self.raw.pack(fill="both", expand=True)
        self.raw.bind("<<Modified>>", self.invalidate)
        self.name = tk.StringVar()
        self.owner = tk.StringVar()
        row = ttk.Frame(pad)
        row.pack(fill="x", pady=10)
        ttk.Label(row, text="记录名称").pack(side="left")
        ttk.Entry(row, textvariable=self.name, width=22).pack(side="left", padx=5)
        ttk.Button(row, text="识别发言人", command=self.identify).pack(side="left", padx=4)
        ttk.Label(row, text="我的昵称").pack(side="left", padx=4)
        self.combo = ttk.Combobox(row, textvariable=self.owner, state="readonly", width=14)
        self.combo.pack(side="left")
        self.info = tk.StringVar(value="粘贴记录后，点击「识别发言人」并选中自己。")
        ttk.Label(pad, textvariable=self.info, wraplength=620).pack(anchor="w")
        ttk.Button(pad, text="开始标注", command=self.submit, style="Accent.TButton").pack(anchor="e", pady=8)
        self.raw.focus_set()

    def invalidate(self, _=None):
        if self.raw.edit_modified():
            self.raw.edit_modified(False)
            self.owner.set("")
            self.combo["values"] = ()
            self.info.set("文本已更新，请识别发言人。")

    def replace(self, text, name):
        self.raw.delete("1.0", "end")
        self.raw.insert("1.0", text)
        self.name.set(name)
        self.invalidate()
        self.identify()

    def load(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("文本记录", "*.txt"), ("所有文件", "*.*")])
        if path:
            try:
                data = Path(path).read_bytes()
                if data.startswith((b"\xff\xfe", b"\xfe\xff")):
                    content = data.decode("utf-16")
                else:
                    try:
                        content = data.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        content = data.decode("gb18030")
                self.replace(content, Path(path).stem)
            except (OSError, UnicodeError) as err:
                messagebox.showerror("读取失败", str(err), parent=self)

    def identify(self):
        try:
            messages = parse_chat(self.raw.get("1.0", "end-1c"))
        except ValueError as err:
            self.info.set(str(err))
            return
        names = list(dict.fromkeys(m[1] for m in messages))
        self.combo["values"] = names
        if self.owner.get() not in names:
            self.owner.set("我" if "我" in names else (names[0] if len(names) == 1 else ""))
        self.info.set(f"识别到 {len(messages)} 条消息、{len(names)} 位发言人。请选择你在这段记录里的昵称。")
        return messages

    def submit(self):
        messages = self.identify()
        if messages is None:
            return
        if not self.owner.get():
            self.info.set("请先在「我的昵称」中选中自己。")
            return
        cid = self.app.store.add(self.name.get().strip() or "群聊记录", self.owner.get(), messages)
        self.destroy()
        self.app.open_chat(cid)


class App(tk.Tk):
    def __init__(self, dbpath):
        super().__init__()
        self.title("窗边来信 · 句读工坊")
        self.geometry("1140x755")
        self.minsize(900, 600)
        self.store = Store(dbpath)
        self.cid = self.row = None
        self.messages, self.rows, self.shown = [], [], []
        self.checked = {}
        self.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), background=PAPER, foreground=INK)
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", background=GREEN, foreground="white")
        style.map("Accent.TButton", background=[("active", "#23785d")])
        style.configure("Head.TLabel", font=(FONT, 16, "bold"))
        style.configure("Treeview", rowheight=31, background="white", fieldbackground="white")
        style.map("Treeview", background=[("selected", "#cde6d8")], foreground=[("selected", INK)])
        top = tk.Frame(self, bg=INK, padx=18, pady=12)
        top.pack(fill="x")
        tk.Label(top, text="群聊标注台", font=(FONT, 17, "bold"), bg=INK, fg="white").pack(side="left")
        ttk.Button(top, text="＋ 导入记录", command=self.import_chat).pack(side="right")
        ttk.Button(top, text="选择微信会话", command=self.import_wechat).pack(side="right", padx=6)
        ttk.Button(top, text="生成说话习惯和接话范例", command=self.auto_export, style="Accent.TButton").pack(side="right")
        self.chat = ttk.Combobox(top, state="readonly", width=30)
        self.chat.pack(side="right", padx=12)
        self.chat.bind("<<ComboboxSelected>>", lambda _: self.open_chat(self.chats[self.chat.current()]["id"]))
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=255)
        left.pack(side="left", fill="y", padx=(0, 15))
        left.pack_propagate(False)
        ttk.Label(left, text="我的回复", style="Head.TLabel").pack(anchor="w")
        self.stats = tk.StringVar(value="导入记录后，从这里挑选样本。")
        ttk.Label(left, textvariable=self.stats).pack(anchor="w", pady=5)
        self.filter = ttk.Combobox(left, values=("全部", "待标注", "已确认", "已跳过"), state="readonly")
        self.filter.current(0)
        self.filter.pack(fill="x", pady=5)
        self.filter.bind("<<ComboboxSelected>>", lambda _: self.refresh_after_save())
        self.tree = ttk.Treeview(left, columns=("status", "preview"), show="headings", selectmode="browse")
        for col, title, width in [("status", "状态", 62), ("preview", "回复预览", 165)]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=(col=="preview"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.choose)
        ttk.Button(left, text="导出已确认样本…", command=self.export).pack(fill="x", pady=(10, 0))
        self.main = ttk.Frame(body)
        self.main.pack(side="left", fill="both", expand=True)
        self.heading = tk.StringVar(value="从一段群聊开始")
        ttk.Label(self.main, textvariable=self.heading, style="Head.TLabel").pack(anchor="w")
        self.hint = tk.StringVar(value="选择微信会话，即可生成说话习惯和接话范例。")
        ttk.Label(self.main, textvariable=self.hint, foreground=MUTED).pack(anchor="w", pady=(3, 6))
        self.more = ttk.Button(self.main, text="查看更早的消息", command=self.earlier)
        self.more.pack(anchor="w", pady=(0, 5))
        box = ttk.Frame(self.main)
        box.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(box, bg="white", height=120, highlightthickness=0)
        scroll = ttk.Scrollbar(box, command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.timeline = tk.Frame(self.canvas, bg="white")
        window = self.canvas.create_window(0, 0, anchor="nw", window=self.timeline)
        self.timeline.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))
        self.bind_all("<MouseWheel>", self.wheel, add="+")
        ttk.Label(self.main, text="我的回复", font=(FONT, 11, "bold")).pack(anchor="w", pady=(10, 3))
        self.reply = editor(self.main, height=3)
        self.reply.pack(fill="x")
        ttk.Label(self.main, text="标注笔记（可选） · 当时为什么这么回？").pack(anchor="w", pady=(6, 3))
        self.note = editor(self.main, height=2)
        self.note.pack(fill="x")
        actions = ttk.Frame(self.main)
        actions.pack(fill="x", pady=(8, 0))
        self.notice = tk.StringVar()
        ttk.Label(actions, textvariable=self.notice, foreground=GREEN).pack(side="left")
        self.ok = ttk.Button(actions, text="确认并继续", style="Accent.TButton", command=lambda: self.advance("已确认"))
        self.ok.pack(side="right")
        self.skip = ttk.Button(actions, text="跳过", command=lambda: self.advance("已跳过"))
        self.skip.pack(side="right", padx=6)
        self.chats = self.store.db.execute("SELECT id FROM chats ORDER BY id").fetchall()
        if self.chats:
            self.open_chat(self.chats[-1]["id"])
        else:
            self.draw(None)

    def wheel(self, event):
        if event.widget == self.canvas or str(event.widget).startswith(str(self.timeline)):
            self.canvas.yview_scroll(-int(event.delta/120), "units")

    def import_chat(self):
        self.persist()
        ImportDialog(self)

    def import_wechat(self):
        self.persist()
        WechatDialog(self)

    def open_chat(self, cid):
        self.persist()
        self.row = None
        self.chats = self.store.db.execute("SELECT id,name,owner FROM chats ORDER BY id").fetchall()
        self.chat["values"] = [f"{c['name']}  ·  {c['owner']}  (#{c['id']})" for c in self.chats]
        self.chat.current(next(i for i,c in enumerate(self.chats) if c["id"] == cid))
        self.cid = cid
        self.messages = json.loads(self.store.db.execute("SELECT transcript FROM chats WHERE id=?", (cid,)).fetchone()[0])
        self.filter.current(0)
        self.refresh()

    def refresh_after_save(self):
        self.persist()
        self.refresh()

    def refresh(self, prefer=None):
        self.rows = self.store.samples(self.cid)
        self.stats.set(f"已确认 {sum(r['status']=='已确认' for r in self.rows)} / {len(self.rows)} 组回复")
        self.shown = [r for r in self.rows if self.filter.get() in ("全部", r["status"])]
        self.tree.delete(*self.tree.get_children())
        for r in self.shown:
            self.tree.insert("", "end", iid=str(r["id"]), values=(r["status"], r["reply"].replace("\n"," / ")[:70]))
        item = next((r for r in self.shown if r["id"] == prefer), None)
        if item is None:
            item = next((r for r in self.shown if r["status"]=="待标注"), self.shown[0] if self.shown else None)
        self.draw(item)
        if item:
            self.tree.selection_set(str(item["id"]))
            self.tree.see(str(item["id"]))

    def choose(self, _):
        selection = self.tree.selection()
        if not selection:
            return
        sid = int(selection[0])
        if self.row and sid == self.row["id"]:
            return
        self.persist()
        self.refresh(sid)

    def draw(self, row):
        self.row = row
        self.checked = {}
        self.notice.set("")
        self.reply.configure(state="normal")
        self.note.configure(state="normal")
        for widget in (self.reply, self.note):
            widget.delete("1.0", "end")
        for child in self.timeline.winfo_children():
            child.destroy()
        for btn in (self.skip, self.ok):
            btn.configure(state="normal" if row else "disabled")
        if row is None:
            self.reply.configure(state="disabled")
            self.note.configure(state="disabled")
            self.more.configure(state="disabled")
            if self.cid:
                self.heading.set("当前筛选下没有回复")
                self.hint.set("切换左侧状态筛选，可查看其他样本。")
            return
        ids = json.loads(row["context"])
        self.heading.set(f"群聊前文 · 第 {next(i for i,r in enumerate(self.rows, 1) if r['id']==row['id'])} 组")
        self.hint.set("勾选理解这条回复需要的发言。连续发出的多条回复按原顺序分行保留。")
        self.reply.insert("1.0", row["reply"])
        self.note.insert("1.0", row["note"])
        self.first = min([max(0, row["start"]-8)] + ids)
        self.render_context(set(ids))

    def render_context(self, ids):
        for child in self.timeline.winfo_children():
            child.destroy()
        self.checked = {}
        for i in range(self.first, self.row["start"]):
            ts, name, body = self.messages[i]
            var = tk.BooleanVar(value=i in ids)
            self.checked[i] = var
            cell = tk.Frame(self.timeline, bg="white")
            cell.pack(fill="x", padx=7, pady=2)
            tk.Checkbutton(cell, variable=var, text=f"{name}   {ts}", anchor="w", bg="white", fg=GREEN,
                           font=(FONT, 9, "bold")).pack(fill="x")
            label = tk.Label(cell, text=body, justify="left", anchor="w", wraplength=max(360,self.canvas.winfo_width()-65),
                             bg="white", fg=INK, font=(FONT, 11))
            label.pack(fill="x", padx=(24, 5))
            label.bind("<Button-1>", lambda _, v=var: v.set(not v.get()))
            cell.bind("<Configure>", lambda e, w=label: w.configure(wraplength=max(120,e.width-38)))
        if not self.row["start"]:
            tk.Label(self.timeline, text="这是记录的第一条发言，没有更早的前文。", bg="white", fg=MUTED).pack(pady=18)
        self.more.configure(state="normal" if self.first else "disabled")
        self.canvas.yview_moveto(0)

    def earlier(self):
        ids = {i for i,v in self.checked.items() if v.get()}
        self.first = max(0,self.first-20)
        self.render_context(ids)

    def persist(self, status=None):
        if self.row is None:
            return
        ids = [i for i,v in self.checked.items() if v.get()]
        reply = self.reply.get("1.0","end-1c")
        note = self.note.get("1.0","end-1c")
        r = self.row
        changed = (ids,reply,note) != (json.loads(r["context"]),r["reply"],r["note"])
        if changed or status is not None:
            self.store.save(r["id"], ids, reply, note, status or "待标注")
            self.row = self.store.db.execute("SELECT * FROM samples WHERE id=?", (r["id"],)).fetchone()

    def advance(self, status):
        if not self.row:
            return
        if status == "已确认" and not self.reply.get("1.0","end-1c").strip():
            self.notice.set("请先填写回复，或点「跳过」。")
            return
        sid = self.row["id"]
        self.persist(status)
        pending = [r["id"] for r in self.rows if r["status"]=="待标注" and r["id"]!=sid]
        target = next((x for x in pending if x>sid), pending[0] if pending else sid)
        self.refresh(target)
        self.notice.set(f"已保存 · {status}" if pending else "本组记录已处理完，可导出已确认样本。")

    def auto_export(self):
        if self.cid is None:
            self.import_wechat()
            return
        self.persist()
        chat = self.chats[self.chat.current()]
        try:
            types = self.store.db.execute("SELECT kinds FROM message_types WHERE chat=?", (self.cid,)).fetchone()
            folder, count = generate_examples(self.store.samples(self.cid), self.messages, chat["owner"],
                                              chat["name"], ROOT / "自动生成", json.loads(types[0]) if types else None)
        except (ValueError, OSError) as err:
            messagebox.showerror("生成失败", str(err), parent=self)
            return
        self.notice.set(f"已生成 {count} 组示例")
        try:
            os.startfile(str(folder))
        except OSError:
            messagebox.showinfo("生成完成", f"已生成 {count} 组示例，保存于\n{folder}", parent=self)

    def export(self):
        if self.cid is None:
            messagebox.showinfo("导出", "请先导入一段记录。", parent=self)
            return
        sid = self.row["id"] if self.row else None
        self.persist()
        self.refresh(sid)
        confirmed = [r for r in self.rows if r["status"]=="已确认"]
        if not confirmed:
            messagebox.showinfo("导出", "当前记录还没有已确认的样本。", parent=self)
            return
        chat = self.chats[self.chat.current()]
        dlg = tk.Toplevel(self)
        dlg.title("导出已确认样本")
        dlg.transient(self)
        dlg.grab_set()
        pane = ttk.Frame(dlg, padding=22)
        pane.pack(fill="both", expand=True)
        ttk.Label(pane, text=f"导出 {len(confirmed)} 组回复", style="Head.TLabel").pack(anchor="w")
        ttk.Label(pane, text="仅导出当前记录中已确认的样本。").pack(anchor="w", pady=(4,12))
        def write(markdown):
            ext = ".md" if markdown else ".jsonl"
            default_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", chat["name"])[:75]
            path = filedialog.asksaveasfilename(parent=dlg, defaultextension=ext, initialdir=ROOT, initialfile=default_name+"-回复示例"+ext,
                                                filetypes=[("示例文档" if markdown else "训练数据", "*"+ext)])
            if path:
                try:
                    Path(path).write_text(export_text(confirmed, self.messages, chat["owner"], markdown), encoding="utf-8")
                except OSError as err:
                    messagebox.showerror("导出失败", str(err), parent=dlg)
                    return
                dlg.destroy()
                messagebox.showinfo("导出完成", f"已导出 {len(confirmed)} 组样本。\n{path}", parent=self)
        ttk.Button(pane, text="示例文档 .md  ·  可发给 AI，包含标注笔记", command=lambda: write(True)).pack(fill="x", pady=3)
        ttk.Button(pane, text="训练数据 .jsonl  ·  前文与回复，每行一个样本", command=lambda: write(False)).pack(fill="x", pady=3)

    def close(self):
        self.persist()
        self.store.db.close()
        self.destroy()


if __name__ == "__main__":
    app = App(ROOT / "标注记录.sqlite3")
    app.after_idle(app.import_wechat)
    app.mainloop()
