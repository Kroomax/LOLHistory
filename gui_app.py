"""LOLhistory GUI — 英雄联盟对局历史分析工具（图形界面）。

一键完成：获取 Cookie → 拉取对局数据 → 生成分析报告。

基于 tkinter + ttk，仅依赖 Python 标准库 + 项目现有模块。
深色 League 主题，与 HTML 分析报告视觉风格统一。

启动方式:
    pythonw gui_app.py          # 无控制台窗口（推荐）
    python gui_app.py           # 带控制台窗口（调试用）

打包为 .exe 后直接双击运行，无需安装 Python 或任何依赖。
"""

from __future__ import annotations

import io
import json
import os
import queue
import re
import sys
import textwrap
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 基础目录：exe 所在目录（打包后）或脚本所在目录（源码运行）──
# 用此替代 Path.cwd()，确保数据库/报告与程序在同一目录，避免
# 因启动方式不同（快捷方式/命令行/任务栏）导致 cwd 不一致，
# 进而使跳过/回填机制失效。
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).resolve().parent

# ── tkinter ──────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ═══════════════════════════════════════════════════════════════════════════════
# 颜色主题 — 与 HTML 报告 Shadow Isles 暗色主题保持一致
# ═══════════════════════════════════════════════════════════════════════════════

THEME = {
    "bg":       "#0a0e14",
    "bg2":      "#111820",
    "card":     "#1a2230",
    "card2":    "#1e2838",
    "border":   "#2a3a4a",
    "text":     "#d4d8dd",
    "text2":    "#8b95a5",
    "text3":    "#5a6575",
    "gold":     "#c8aa6e",
    "gold_dim": "#8a7040",
    "blue":     "#0ac8b9",
    "green":    "#2ecc71",
    "red":      "#e74c3c",
    "blue2":    "#4a9eff",
    "purple":   "#a855f7",
    "orange":   "#f59e0b",
    "input_bg": "#0d1117",
    "hover":    "#212b38",
    "accent":   "#1a3a4a",
}

FONT_TITLE  = ("Microsoft YaHei", 18, "bold")
FONT_H1     = ("Microsoft YaHei", 15, "bold")
FONT_H2     = ("Microsoft YaHei", 13, "bold")
FONT_BODY   = ("Microsoft YaHei", 11)
FONT_SMALL  = ("Microsoft YaHei", 10)
FONT_MONO   = ("Consolas", 10)
FONT_BTN    = ("Microsoft YaHei", 12, "bold")
FONT_BTN_SM = ("Microsoft YaHei", 11)

# ═══════════════════════════════════════════════════════════════════════════════
# Cookie 持久化
# ═══════════════════════════════════════════════════════════════════════════════

def _is_valid_cookie_value(v: str) -> bool:
    """Cookie 值必须是纯 ASCII（HTTP header 要求 latin-1 可编码）。"""
    try:
        v.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False

def _clean_cookies(cookies: dict) -> dict:
    """过滤掉非法 cookie 值（非 ASCII 字符，如占位符文本）。"""
    return {k: v for k, v in cookies.items()
            if v and isinstance(v, str) and _is_valid_cookie_value(v)}

def _appdata_dir() -> Path:
    p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    d = p / "lolhistory"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _save_cookies(cookies: dict) -> None:
    path = _appdata_dir() / "cookies.json"
    clean = _clean_cookies(cookies)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_saved_cookies() -> Optional[dict]:
    path = _appdata_dir() / "cookies.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        clean = _clean_cookies(raw)
        return clean if clean else None
    except Exception:
        return None

# ═══════════════════════════════════════════════════════════════════════════════
# stdout / stderr 捕获器
# ═══════════════════════════════════════════════════════════════════════════════

class OutputCapture(io.TextIOBase):
    """捕获 print / sys.stderr 输出到队列，供 GUI 日志显示。"""

    def __init__(self, q: queue.Queue, orig_stream):
        super().__init__()
        self._q = q
        self._orig = orig_stream
        self._buf = ""

    def write(self, s: str) -> int:
        if s:
            self._q.put(("log", s))
            if self._orig:
                try:
                    self._orig.write(s)
                except Exception:
                    pass
        return len(s)

    def flush(self):
        if self._orig:
            try:
                self._orig.flush()
            except Exception:
                pass


class QueueStringIO(io.StringIO):
    """StringIO 子类，每次 write 同时推送到消息队列，实现抓包实时日志显示。"""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q

    def write(self, s: str) -> int:
        if s and s.strip():
            self._q.put(("capture_log", s))
        return super().write(s)

    def isatty(self) -> bool:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# 主 GUI 类
# ═══════════════════════════════════════════════════════════════════════════════

class LOLHistoryApp:
    """LOLhistory 图形界面主应用。

    4 阶段向导式流程:
        ① 欢迎页 — 品牌展示 + 功能说明
        ② Cookie 获取 — 一键抓包 / 选择文件 / 手动粘贴
        ③ 数据拉取 — 实时进度 + 日志
        ④ 完成页 — 统计摘要 + 打开报告
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("LOLhistory — 英雄联盟对局分析")
        self.root.geometry("1060x780")
        self.root.minsize(980, 690)
        self.root.configure(bg=THEME["bg"])

        # 居中窗口
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 1060, 780
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # 设置窗口图标（尝试）
        try:
            icon_path = Path(__file__).parent / "assets" / "icon.ico"
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except Exception:
            pass

        # ── 状态变量 ──────────────────────────────────────────────────────
        self._msg_queue: queue.Queue = queue.Queue()
        self._stage = 0           # 0=Welcome, 1=Cookie, 2=Fetch, 3=Complete
        self._cookies: dict = {}
        self._fetch_thread: Optional[threading.Thread] = None
        self._cancel_flag = threading.Event()
        self._report_path: str = ""
        self._db_path: str = ""
        self._total_games = 0
        self._total_wins = 0
        self._log_lines: list[str] = []

        # ── 尝试加载已保存的 Cookie ──────────────────────────────────────
        self._saved_cookies = _load_saved_cookies()

        # ── 构建 UI ────────────────────────────────────────────────────────
        self._build_styles()
        self._build_header()
        self._build_footer()     # 必须在 _build_pages/_show_page 之前
        self._build_pages()      # 内部调用 _show_page(0) → _update_footer()
        self._setup_close_handler()

        # ── 启动消息轮询 ──────────────────────────────────────────────────
        self._poll_messages()

    # ═══════════════════════════════════════════════════════════════════════════
    # ttk 样式
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # 通用配置
        style.configure(".", background=THEME["bg"], foreground=THEME["text"],
                         font=FONT_BODY, borderwidth=0)

        # 框架
        style.configure("Card.TFrame", background=THEME["card"],
                         relief="flat", borderwidth=1)
        style.configure("Dark.TFrame", background=THEME["bg"])

        # 标签
        style.configure("Title.TLabel", font=FONT_TITLE,
                         foreground=THEME["gold"], background=THEME["bg"])
        style.configure("H1.TLabel", font=FONT_H1,
                         foreground=THEME["text"], background=THEME["bg"])
        style.configure("H2.TLabel", font=FONT_H2,
                         foreground=THEME["gold"], background=THEME["bg"])
        style.configure("Body.TLabel", font=FONT_BODY,
                         foreground=THEME["text2"], background=THEME["bg"])
        style.configure("BodyLight.TLabel", font=FONT_BODY,
                         foreground=THEME["text"], background=THEME["bg"])
        style.configure("Small.TLabel", font=FONT_SMALL,
                         foreground=THEME["text3"], background=THEME["bg"])
        style.configure("Gold.TLabel", font=FONT_BODY,
                         foreground=THEME["gold"], background=THEME["bg"])
        style.configure("Green.TLabel", font=FONT_BODY,
                         foreground=THEME["green"], background=THEME["bg"])
        style.configure("Red.TLabel", font=FONT_BODY,
                         foreground=THEME["red"], background=THEME["bg"])
        style.configure("CardTitle.TLabel", font=FONT_H1,
                         foreground=THEME["text"], background=THEME["card"])
        style.configure("CardBody.TLabel", font=FONT_BODY,
                         foreground=THEME["text2"], background=THEME["card"],
                         wraplength=860)
        style.configure("StepNum.TLabel", font=("Consolas", 14, "bold"),
                         foreground=THEME["gold"], background=THEME["card2"])
        style.configure("StageTitle.TLabel", font=FONT_H1,
                         foreground=THEME["gold"], background=THEME["bg"])
        style.configure("StageSub.TLabel", font=FONT_SMALL,
                         foreground=THEME["text2"], background=THEME["bg"])

        # 按钮
        style.configure("Primary.TButton", font=FONT_BTN,
                         background=THEME["gold"], foreground=THEME["bg"],
                         borderwidth=0, relief="flat", padding=(24, 10))
        style.map("Primary.TButton",
                   background=[("active", "#d4b87a"), ("disabled", THEME["card"])],
                   foreground=[("disabled", THEME["text3"])])

        style.configure("Secondary.TButton", font=FONT_BTN_SM,
                         background=THEME["card"], foreground=THEME["text"],
                         borderwidth=1, relief="flat", padding=(16, 8))
        style.map("Secondary.TButton",
                   background=[("active", THEME["hover"])])

        style.configure("Link.TButton", font=FONT_BTN_SM,
                         background=THEME["bg"], foreground=THEME["blue2"],
                         borderwidth=0, relief="flat", padding=(8, 4))
        style.map("Link.TButton",
                   foreground=[("active", THEME["blue"])])

        # 进度条
        style.configure("Primary.Horizontal.TProgressbar",
                         thickness=8, troughcolor=THEME["card"],
                         background=THEME["gold"], borderwidth=0,
                         lightcolor=THEME["gold"], darkcolor=THEME["gold"])

        # 输入框
        style.configure("Dark.TEntry", fieldbackground=THEME["input_bg"],
                         foreground=THEME["text"], bordercolor=THEME["border"],
                         insertcolor=THEME["text"], relief="flat",
                         padding=6)

        # 滚动条
        style.configure("Dark.Vertical.TScrollbar",
                         background=THEME["card"], troughcolor=THEME["bg"],
                         bordercolor=THEME["bg"], arrowcolor=THEME["text2"],
                         relief="flat", width=8)
        style.map("Dark.Vertical.TScrollbar",
                   background=[("active", THEME["border"])])

    # ═══════════════════════════════════════════════════════════════════════════
    # 顶部 Header — Logo + 步骤指示器
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_header(self):
        header = tk.Frame(self.root, bg=THEME["bg"], height=90)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        inner = tk.Frame(header, bg=THEME["bg"])
        inner.pack(fill="both", expand=True, padx=28, pady=(16, 0))

        # Logo
        logo_frame = tk.Frame(inner, bg=THEME["bg"])
        logo_frame.pack(side="left")

        logo = tk.Label(logo_frame, text="⚔", font=("Segoe UI Symbol", 22),
                         bg=THEME["bg"], fg=THEME["gold"])
        logo.pack(side="left", padx=(0, 8))

        title = tk.Label(logo_frame, text="LOLhistory", font=FONT_TITLE,
                          bg=THEME["bg"], fg=THEME["gold"])
        title.pack(side="left")

        sub = tk.Label(inner, text="英雄联盟对局历史分析", font=FONT_SMALL,
                        bg=THEME["bg"], fg=THEME["text2"])
        sub.place(x=200, y=28)

        # 步骤指示器
        steps_frame = tk.Frame(inner, bg=THEME["bg"])
        steps_frame.pack(side="right")

        self._step_labels: list[tk.Label] = []
        self._step_connectors: list[tk.Label] = []

        step_names = ["① 欢迎", "② 获取凭据", "③ 拉取数据", "④ 完成"]
        for i, name in enumerate(step_names):
            if i > 0:
                conn = tk.Label(steps_frame, text=" ─ ", font=FONT_SMALL,
                                 bg=THEME["bg"], fg=THEME["text3"])
                conn.pack(side="left")
                self._step_connectors.append(conn)

            lbl = tk.Label(steps_frame, text=name, font=FONT_SMALL,
                            bg=THEME["bg"], fg=THEME["text3"])
            lbl.pack(side="left")
            self._step_labels.append(lbl)

        # 底部分隔线
        sep = tk.Frame(header, bg=THEME["border"], height=1)
        sep.pack(side="bottom", fill="x")

    def _update_step_indicator(self, stage: int):
        """高亮当前步骤。"""
        for i, lbl in enumerate(self._step_labels):
            if i == stage:
                lbl.configure(fg=THEME["gold"], font=("Microsoft YaHei", 10, "bold"))
            elif i < stage:
                lbl.configure(fg=THEME["green"], font=FONT_SMALL)
            else:
                lbl.configure(fg=THEME["text3"], font=FONT_SMALL)

        for i, conn in enumerate(self._step_connectors):
            if i < stage:
                conn.configure(fg=THEME["green"])
            else:
                conn.configure(fg=THEME["text3"])

    # ═══════════════════════════════════════════════════════════════════════════
    # 页面容器
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_pages(self):
        """内容区域 — 4 个页面 frame，切换时显示/隐藏。"""
        self._content = tk.Frame(self.root, bg=THEME["bg"])
        self._content.pack(fill="both", expand=True, padx=28, pady=(0, 8))

        self._pages: dict[int, tk.Frame] = {}

        # 页面 0: 欢迎
        self._pages[0] = self._build_welcome_page()
        # 页面 1: Cookie
        self._pages[1] = self._build_cookie_page()
        # 页面 2: 拉取数据
        self._pages[2] = self._build_fetch_page()
        # 页面 3: 完成
        self._pages[3] = self._build_complete_page()

        # 默认显示第 0 页
        self._show_page(0)

    def _show_page(self, stage: int):
        """切换当前页面。"""
        for s, frame in self._pages.items():
            if s == stage:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        self._stage = stage
        self._update_step_indicator(stage)
        self._update_footer(stage)

        # 切换到 Cookie 页面时自动检测根证书状态
        if stage == 1:
            self.root.after(200, lambda: self._update_cert_status_ui(
                self._check_cert_status()))

    # ═══════════════════════════════════════════════════════════════════════════
    # 底部导航按钮
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_footer(self):
        footer = tk.Frame(self.root, bg=THEME["bg"], height=56)
        footer.pack(fill="x", side="bottom", padx=28, pady=(0, 16))
        footer.pack_propagate(False)

        self._footer_left = tk.Frame(footer, bg=THEME["bg"])
        self._footer_left.pack(side="left")

        self._footer_right = tk.Frame(footer, bg=THEME["bg"])
        self._footer_right.pack(side="right")

        # 按钮在 _update_footer 中动态创建

    def _update_footer(self, stage: int):
        """根据当前阶段更新底部按钮。"""
        for w in self._footer_left.winfo_children():
            w.destroy()
        for w in self._footer_right.winfo_children():
            w.destroy()

        if stage == 0:
            # 欢迎页: 只有 "开始使用" 按钮
            self._btn_primary = tk.Button(
                self._footer_right, text="开始使用 →", font=FONT_BTN,
                bg=THEME["gold"], fg=THEME["bg"], activebackground="#d4b87a",
                activeforeground=THEME["bg"], relief="flat",
                padx=28, pady=10, cursor="hand2", borderwidth=0,
                command=self._go_to_cookie)
            self._btn_primary.pack(side="right")

        elif stage == 1:
            # Cookie 页: 后退 + 下一步
            tk.Button(
                self._footer_left, text="← 返回", font=FONT_BTN_SM,
                bg=THEME["card"], fg=THEME["text2"], activebackground=THEME["hover"],
                activeforeground=THEME["text"], relief="flat",
                padx=16, pady=8, cursor="hand2", borderwidth=0,
                command=lambda: self._show_page(0)
            ).pack(side="left")

            self._btn_primary = tk.Button(
                self._footer_right, text="连接并拉取数据 →", font=FONT_BTN,
                bg=THEME["gold"], fg=THEME["bg"], activebackground="#d4b87a",
                activeforeground=THEME["bg"], relief="flat",
                padx=28, pady=10, cursor="hand2", borderwidth=0,
                command=self._start_fetch, state="disabled")
            self._btn_primary.pack(side="right")

            # 检查是否已有可用 Cookie
            self.root.after(100, self._update_cookie_button)

        elif stage == 2:
            # 拉取页: 取消按钮
            tk.Button(
                self._footer_left, text="✕ 取消", font=FONT_BTN_SM,
                bg=THEME["card"], fg=THEME["red"], activebackground=THEME["hover"],
                activeforeground=THEME["red"], relief="flat",
                padx=16, pady=8, cursor="hand2", borderwidth=0,
                command=self._cancel_fetch
            ).pack(side="left")

        elif stage == 3:
            # 完成页: 仅保留重新拉取按钮（打开报告/文件夹在页面内）
            tk.Button(
                self._footer_left, text="🔄 重新获取数据", font=FONT_BTN_SM,
                bg=THEME["card"], fg=THEME["text"], activebackground=THEME["hover"],
                activeforeground=THEME["text"], relief="flat",
                padx=16, pady=8, cursor="hand2", borderwidth=0,
                command=lambda: self._show_page(1)
            ).pack(side="left")

    # ═══════════════════════════════════════════════════════════════════════════
    # 页面 0: 欢迎页
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_welcome_page(self) -> tk.Frame:
        page = tk.Frame(self._content, bg=THEME["bg"])

        # 居中容器
        center = tk.Frame(page, bg=THEME["bg"])
        center.place(relx=0.5, rely=0.5, anchor="center", width=860, height=420)

        # 大图标
        icon = tk.Label(center, text="⚔", font=("Segoe UI Symbol", 56),
                         bg=THEME["bg"], fg=THEME["gold"])
        icon.pack(pady=(0, 12))

        # 标题
        slogan = tk.Label(center, text="你的每一场召唤师峡谷之战，都值得被记住",
                           font=("Microsoft YaHei", 16, "bold"),
                           bg=THEME["bg"], fg=THEME["text"])
        slogan.pack(pady=(0, 28))

        # 功能卡片
        cards_frame = tk.Frame(center, bg=THEME["bg"])
        cards_frame.pack(fill="x", pady=(0, 24))

        features = [
            ("📊", "500+ 场对局", "一键导出全部对局历史"),
            ("📈", "30+ 分析维度", "胜率因子 · 游戏节奏 · 玩家水平"),
            ("🎯", "专属报告", "交互式 HTML 报告，支持筛选与排序"),
            ("⚡", "2 分钟上手", "全自动流程，无需编程基础"),
        ]

        for i, (icon_text, title, desc) in enumerate(features):
            card = tk.Frame(cards_frame, bg=THEME["card"],
                             highlightbackground=THEME["border"],
                             highlightthickness=1, padx=2, pady=2)
            card.pack(side="left", fill="both", expand=True, padx=(0 if i == 0 else 6, 0 if i == 3 else 6))

            inner_card = tk.Frame(card, bg=THEME["card"])
            inner_card.pack(fill="both", expand=True, padx=14, pady=14)

            tk.Label(inner_card, text=icon_text, font=("Segoe UI Symbol", 22),
                      bg=THEME["card"], fg=THEME["gold"]).pack(pady=(0, 6))
            tk.Label(inner_card, text=title, font=("Microsoft YaHei", 11, "bold"),
                      bg=THEME["card"], fg=THEME["text"]).pack()
            tk.Label(inner_card, text=desc, font=("Microsoft YaHei", 9),
                      bg=THEME["card"], fg=THEME["text2"]).pack(pady=(2, 0))

        # 准备清单
        prep = tk.Label(center, text="需要：WeGame 账号 + 2 分钟  |  数据仅保存在本地，不上传任何服务器",
                         font=FONT_SMALL, bg=THEME["bg"], fg=THEME["text3"])
        prep.pack()

        return page

    # ═══════════════════════════════════════════════════════════════════════════
    # 页面 1: Cookie 获取页
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_cookie_page(self) -> tk.Frame:
        page = tk.Frame(self._content, bg=THEME["bg"])

        # 标题
        stage_title = tk.Label(page, text="获取 WeGame 登录凭据", font=FONT_H1,
                                bg=THEME["bg"], fg=THEME["gold"])
        stage_title.pack(anchor="w", pady=(0, 4))

        stage_sub = tk.Label(page, text="登录凭据用于读取你的对局数据，仅保存在本机，不会上传到任何服务器",
                              font=FONT_SMALL, bg=THEME["bg"], fg=THEME["text2"])
        stage_sub.pack(anchor="w", pady=(0, 10))

        # ── 方式一：一键抓包（推荐）──────────────────────────────────────────
        self._capture_card = tk.Frame(page, bg=THEME["card"],
                                       highlightbackground=THEME["gold"],
                                       highlightthickness=1)
        self._capture_card.pack(fill="x", pady=(0, 6))

        cap_inner = tk.Frame(self._capture_card, bg=THEME["card"])
        cap_inner.pack(fill="both", expand=True, padx=20, pady=10)

        cap_header = tk.Frame(cap_inner, bg=THEME["card"])
        cap_header.pack(fill="x")

        tk.Label(cap_header, text="⭐ 方式一：一键抓包", font=("Microsoft YaHei", 13, "bold"),
                  bg=THEME["card"], fg=THEME["gold"]).pack(side="left")
        tk.Label(cap_header, text="推荐  |  无需任何操作，登录 WeGame 即自动完成",
                  font=FONT_SMALL, bg=THEME["card"], fg=THEME["text3"]).pack(side="left", padx=(10, 0))

        cap_steps = [
            "1. 首次使用需先点击下方「安装 HTTPS 证书」（仅需一次，无需管理员）",
            "2. 点击「开始抓包」→ 等待引擎启动（约 3 秒）",
            "3. 看到「代理引擎已就绪」提示后，打开并登录 WeGame",
            "4. 登录成功后凭据自动获取，无需任何额外操作",
        ]
        for step in cap_steps:
            tk.Label(cap_inner, text=step, font=FONT_BODY,
                      bg=THEME["card"], fg=THEME["text2"]).pack(anchor="w", pady=(3, 0))

        # ── 根证书状态 ───────────────────────────────────────────────────
        cert_frame = tk.Frame(cap_inner, bg=THEME["card"])
        cert_frame.pack(fill="x", pady=(6, 2))

        self._cert_status_icon = tk.Label(cert_frame, text="", font=FONT_BODY,
                                          bg=THEME["card"], fg=THEME["text2"])
        self._cert_status_icon.pack(side="left")

        self._cert_status_text = tk.Label(cert_frame, text="正在检测 HTTPS 证书...",
                                          font=FONT_SMALL, bg=THEME["card"],
                                          fg=THEME["text2"])
        self._cert_status_text.pack(side="left", padx=(4, 12))

        self._btn_install_cert = tk.Button(
            cert_frame, text="🔒 安装 HTTPS 证书（仅需一次）", font=FONT_SMALL,
            bg=THEME["card2"], fg=THEME["blue2"], activebackground=THEME["hover"],
            activeforeground=THEME["blue"], relief="flat",
            padx=12, pady=4, cursor="hand2", borderwidth=1,
            command=self._install_cert)
        self._btn_install_cert.pack(side="left")

        # ── 抓包状态 + 按钮 ──────────────────────────────────────────────
        self._capture_status = tk.Label(cap_inner, text="",
                                         font=("Microsoft YaHei", 10, "bold"),
                                         bg=THEME["card"], fg=THEME["green"])
        self._capture_status.pack(anchor="w", pady=(4, 4))

        btn_row = tk.Frame(cap_inner, bg=THEME["card"])
        btn_row.pack(fill="x")

        self._btn_capture = tk.Button(
            btn_row, text="🔍 开始抓包", font=FONT_BTN,
            bg=THEME["gold"], fg=THEME["bg"], activebackground="#d4b87a",
            activeforeground=THEME["bg"], relief="flat",
            padx=20, pady=8, cursor="hand2", borderwidth=0,
            command=self._run_capture)
        self._btn_capture.pack(side="left")

        # ── 方式二：选择已有文件 / 手动填入 ─────────────────────────────────
        self._manual_card = tk.Frame(page, bg=THEME["card"],
                                      highlightbackground=THEME["border"],
                                      highlightthickness=1)
        self._manual_card.pack(fill="x")

        man_inner = tk.Frame(self._manual_card, bg=THEME["card"])
        man_inner.pack(fill="both", expand=True, padx=20, pady=10)

        tk.Label(man_inner, text="方式二：选择凭据文件或手动填入",
                  font=("Microsoft YaHei", 13, "bold"),
                  bg=THEME["card"], fg=THEME["text"]).pack(anchor="w")

        # 选择文件按钮
        file_row = tk.Frame(man_inner, bg=THEME["card"])
        file_row.pack(fill="x", pady=(6, 2))

        tk.Button(file_row, text="📂 选择凭据文件（cookies.json）", font=FONT_BTN_SM,
                   bg=THEME["card2"], fg=THEME["blue2"], activebackground=THEME["hover"],
                   activeforeground=THEME["blue"], relief="flat",
                   padx=14, pady=6, cursor="hand2", borderwidth=1,
                   command=self._select_cookie_file).pack(side="left")

        self._file_status = tk.Label(man_inner, text="",
                                      font=FONT_SMALL, bg=THEME["card"], fg=THEME["text3"])
        self._file_status.pack(anchor="w")

        # 如果有已保存的 Cookie，显示提示
        if self._saved_cookies:
            saved_info = tk.Label(man_inner,
                                   text=f"💾 检测到已保存的登录凭据（可直接下一步）",
                                   font=FONT_SMALL, bg=THEME["card"], fg=THEME["gold_dim"])
            saved_info.pack(anchor="w", pady=(6, 0))

        # 手动输入区域（可折叠）
        self._manual_toggle = tk.Label(man_inner, text="▸ 手动填写凭据（高级）",
                                        font=FONT_SMALL, bg=THEME["card"],
                                        fg=THEME["text3"], cursor="hand2")
        self._manual_toggle.pack(anchor="w", pady=(4, 0))
        self._manual_toggle.bind("<Button-1>", self._toggle_manual_input)

        self._manual_frame = tk.Frame(man_inner, bg=THEME["card"])
        # 默认隐藏

        fields = [
            ("puin", "数字用户 ID（如 123456789）"),
            ("pkey", "加密密钥（以 0003 开头）"),
            ("tgp_biz_ticket", "业务票据（以 0100 开头）"),
            ("tgp_id", "TGP 用户 ID（数字）"),
        ]

        self._cookie_placeholders = {ph for _, ph in fields}
        self._cookie_entries: dict[str, tuple[tk.Entry, tk.Label]] = {}

        for name, placeholder in fields:
            row = tk.Frame(self._manual_frame, bg=THEME["card"])
            row.pack(fill="x", pady=3)

            tk.Label(row, text=name, font=FONT_MONO, width=20, anchor="e",
                      bg=THEME["card"], fg=THEME["gold"]).pack(side="left", padx=(0, 8))
            entry = tk.Entry(row, font=FONT_MONO, bg=THEME["input_bg"],
                              fg=THEME["text"], insertbackground=THEME["text"],
                              relief="flat", width=66, show="*")
            entry.insert(0, placeholder)
            entry.bind("<FocusIn>", lambda e, ph=placeholder: self._on_entry_focus(e, ph))
            entry.bind("<FocusOut>", lambda e, ph=placeholder: self._on_entry_blur(e, ph))
            entry.pack(side="left", fill="x", expand=True)
            self._cookie_entries[name] = (entry, row)

            # 显示/隐藏切换
            show_btn = tk.Label(row, text="👁", font=FONT_SMALL,
                                 bg=THEME["card"], fg=THEME["text3"], cursor="hand2")
            show_btn.pack(side="left", padx=(6, 0))
            show_btn.bind("<Button-1>", lambda e, en=entry: self._toggle_entry_visibility(en))

        # 粘贴 cURL 文本区
        curl_frame = tk.Frame(self._manual_frame, bg=THEME["card"])
        curl_frame.pack(fill="x", pady=(8, 0))

        tk.Label(curl_frame, text="或粘贴 cURL 请求（从浏览器复制）：", font=FONT_SMALL,
                  bg=THEME["card"], fg=THEME["text3"]).pack(anchor="w")

        self._curl_text = tk.Text(curl_frame, font=FONT_MONO, bg=THEME["input_bg"],
                                    fg=THEME["text"], insertbackground=THEME["text"],
                                    relief="flat", height=3, wrap="word")
        self._curl_text.pack(fill="x", pady=(4, 4))
        self._curl_text.bind("<<Modified>>", self._on_curl_modified)

        self._curl_status = tk.Label(curl_frame, text="",
                                      font=FONT_SMALL, bg=THEME["card"], fg=THEME["green"])
        self._curl_status.pack(anchor="w")

        return page

    def _toggle_manual_input(self, event=None):
        if self._manual_frame.winfo_ismapped():
            self._manual_frame.pack_forget()
            self._manual_toggle.configure(text="▸ 手动填写凭据（高级）")
        else:
            self._manual_frame.pack(fill="x", pady=(0, 4))
            self._manual_toggle.configure(text="▾ 手动填写凭据（高级）")

    def _on_entry_focus(self, event, placeholder: str):
        entry: tk.Entry = event.widget
        if entry.get() == placeholder:
            entry.delete(0, "end")
            entry.configure(fg=THEME["text"])

    def _on_entry_blur(self, event, placeholder: str):
        entry: tk.Entry = event.widget
        if not entry.get().strip():
            entry.delete(0, "end")
            entry.insert(0, placeholder)
            entry.configure(fg=THEME["text3"])

    def _toggle_entry_visibility(self, entry: tk.Entry):
        if entry.cget("show") == "*":
            entry.configure(show="")
        else:
            entry.configure(show="*")

    def _on_curl_modified(self, event=None):
        """解析粘贴的 cURL 文本。"""
        text = self._curl_text.get("0.0", "end").strip()
        if not text or len(text) < 10:
            self._curl_text.edit_modified(False)
            return

        self._curl_text.edit_modified(False)

        if "curl" not in text.lower():
            return

        self._curl_status.configure(text="正在解析凭据...", fg=THEME["orange"])

        try:
            # 临时写入文件，使用现有函数解析
            import tempfile
            tmp = Path(tempfile.gettempdir()) / "_lolhistory_curl.tmp"
            tmp.write_text(text, encoding="utf-8")

            from lolhistory._cookie_extract import extract_cookies_from_curl
            from lolhistory._cookie_extract import _filter_required

            cookies = extract_cookies_from_curl(tmp)
            cookies = _filter_required(cookies)
            tmp.unlink(missing_ok=True)

            if cookies:
                self._fill_cookie_fields(cookies)
                self._curl_status.configure(
                    text=f"✅ 已解析 {len(cookies)}/4 项凭据", fg=THEME["green"])
            else:
                self._curl_status.configure(
                    text="⚠ 未能解析到凭据，请确认复制的是 www.wegame.com.cn 的请求",
                    fg=THEME["orange"])
        except Exception as e:
            self._curl_status.configure(text=f"❌ 解析失败: {e}", fg=THEME["red"])

    def _fill_cookie_fields(self, cookies: dict):
        """将 Cookie 填入输入框。"""
        for key, (entry, row) in self._cookie_entries.items():
            if key in cookies and cookies[key]:
                entry.delete(0, "end")
                entry.insert(0, cookies[key])
                entry.configure(fg=THEME["text"])

        # 更新按钮状态
        self._update_cookie_button()

        # 自动展开手动输入区
        if not self._manual_frame.winfo_ismapped():
            self._toggle_manual_input()

    def _update_cookie_button(self):
        """根据当前 Cookie 状态更新「下一步」按钮。"""
        if not hasattr(self, '_btn_primary') or self._btn_primary is None:
            return
        cookies = self._collect_cookies()
        if cookies and len(cookies) >= 4:
            self._btn_primary.configure(state="normal", text="连接并拉取数据 →")
        else:
            self._btn_primary.configure(state="disabled",
                                         text=f"还需 {4 - len(cookies)} 项凭据")

    def _collect_cookies(self) -> dict:
        """从各种来源收集 Cookie。"""
        cookies = {}

        # 1. 优先使用一键抓包的结果
        if self._cookies:
            cookies.update(self._cookies)

        # 2. 从手动输入框获取（排除占位符文本）
        for key, (entry, _) in self._cookie_entries.items():
            val = entry.get().strip()
            if val and val not in self._cookie_placeholders:
                cookies[key] = val

        # 3. 从已保存的 Cookie 获取（作为补充）
        if self._saved_cookies:
            for k, v in self._saved_cookies.items():
                if k not in cookies and v:
                    cookies[k] = v

        return _clean_cookies(cookies)

    def _select_cookie_file(self):
        """打开文件选择对话框。"""
        path = filedialog.askopenfilename(
            title="选择凭据文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return

        try:
            from lolhistory._wegame import load_cookies
            cookies = load_cookies(path)
            self._cookies = cookies
            self._fill_cookie_fields(cookies)
            self._file_status.configure(
                text=f"✅ 已加载: {Path(path).name} ({len(cookies)} 项)",
                fg=THEME["green"])
            self._update_cookie_button()
        except Exception as e:
            self._file_status.configure(text=f"❌ 加载失败: {e}", fg=THEME["red"])

    def _run_capture(self):
        """在后台线程启动一键抓包。"""
        # 前置检查：根证书状态
        cert_status = self._check_cert_status()
        if cert_status == "missing":
            # 证书文件不存在，阻止抓包并提示用户先安装
            self._update_cert_status_ui(cert_status)
            self._capture_status.configure(
                text="⚠ 请先点击上方「安装 HTTPS 证书」按钮（仅需一次）",
                fg=THEME["orange"])
            return
        elif cert_status == "exists":
            # 证书存在但未安装 — 刷新 UI 提示，但不阻止（用户可自行决定）
            self._update_cert_status_ui(cert_status)
            self._capture_status.configure(
                text="⚠ HTTPS 证书尚未安装（仍可尝试抓包，但可能失败）",
                fg=THEME["orange"])
            # 不 return，允许继续

        self._btn_capture.configure(state="disabled", text="启动中...")

        def worker():
            try:
                # 使用 QueueStringIO 实现实时日志输出
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                captured = QueueStringIO(self._msg_queue)
                sys.stdout = captured
                sys.stderr = captured

                try:
                    from lolhistory._capture_cookies import run_capture
                    cookies = run_capture(output="cookies.json", timeout=120)
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr

                if cookies and all(k in cookies for k in ["puin", "pkey", "tgp_biz_ticket", "tgp_id"]):
                    self._cookies = cookies
                    _save_cookies(cookies)
                    self._msg_queue.put(("capture_done", cookies))
                else:
                    missing = [k for k in ["puin", "pkey", "tgp_biz_ticket", "tgp_id"]
                               if k not in cookies]
                    self._msg_queue.put(("capture_fail", missing))
            except ImportError as e:
                self._msg_queue.put(("capture_error", f"抓包组件缺失，请重新安装本程序"))
            except Exception as e:
                self._msg_queue.put(("capture_error", f"抓包失败: {e}\n{traceback.format_exc()}"))

        threading.Thread(target=worker, daemon=True).start()

    # ── 错误消息映射 ──────────────────────────────────────────────────────────
    _ERROR_MAP = {
        "8025009": ("登录凭据已过期", "请重新获取凭据"),
        "8000002": ("请求过于频繁", "请稍等 30 秒后重试"),
        "Connection refused": ("无法连接服务器", "请检查网络连接"),
        "ConnectionError": ("网络连接失败", "请检查网络是否正常"),
        "timeout": ("请求超时", "服务器响应慢，请稍后重试"),
        "mitmproxy": ("抓包组件异常", "请重新启动程序"),
        "certificate": ("HTTPS 证书问题", "请尝试重新安装证书"),
    }

    def _friendly_error(self, raw_msg: str) -> str:
        """将技术错误转为用户可理解的提示。"""
        for keyword, (title, suggestion) in self._ERROR_MAP.items():
            if keyword.lower() in raw_msg.lower():
                return f"{title}\n→ {suggestion}"
        # 未匹配到，截断过长的 traceback
        if len(raw_msg) > 300:
            return raw_msg[:300] + "\n…(更多详情见日志)"
        return raw_msg

    def _handle_capture_done(self, cookies: dict):
        """处理抓包完成。"""
        puin = cookies.get('puin', '')
        self._capture_status.configure(
            text=f"✅ 成功获取 {len(cookies)}/4 项登录凭据！"
                 f"puin={puin[:20]}{'…' if len(puin) > 20 else ''}  |  "
                 f"凭据已自动保存，可进入下一步",
            fg=THEME["green"])
        self._btn_capture.configure(state="normal", text="🔄 重新抓包")

        self._fill_cookie_fields(cookies)
        self._update_cookie_button()

        # 刷新手动输入区的 cookies
        self._saved_cookies = cookies

    def _handle_capture_fail(self, missing: list):
        """处理抓包部分失败。"""
        self._capture_status.configure(
            text=f"⚠ 部分凭据未获取: 缺少 {', '.join(missing)}\n"
                 f"请确认: ① WeGame 已登录  ② HTTPS 证书已安装",
            fg=THEME["orange"])
        self._btn_capture.configure(state="normal", text="🔄 重新抓包")
        self._update_cookie_button()
        # 刷新证书状态
        self._update_cert_status_ui(self._check_cert_status())

    def _handle_capture_error(self, msg: str):
        """处理抓包错误。"""
        friendly = self._friendly_error(msg)
        self._capture_status.configure(text=f"❌ {friendly}", fg=THEME["red"])
        self._btn_capture.configure(state="normal", text="🔄 重试抓包")

    # ═══════════════════════════════════════════════════════════════════════════
    # 根证书管理
    # ═══════════════════════════════════════════════════════════════════════════

    def _check_cert_status(self) -> str:
        """检测根证书状态。返回 'installed' | 'exists' | 'missing'。"""
        try:
            from lolhistory._capture_cookies import _find_ca_cert
            cert_path = _find_ca_cert()
            if cert_path:
                # 证书文件存在，尝试检查是否已安装到信任存储
                import subprocess
                result = subprocess.run(
                    ["certutil", "-user", "-store", "Root"],
                    capture_output=True, text=True,
                )
                if "mitmproxy" in result.stdout:
                    return "installed"
                return "exists"
            return "missing"
        except ImportError:
            return "missing"
        except Exception:
            return "missing"

    def _update_cert_status_ui(self, status: str):
        """根据证书状态更新 UI 元素。"""
        if status == "installed":
            self._cert_status_icon.configure(text="✅", fg=THEME["green"])
            self._cert_status_text.configure(
                text="HTTPS 证书已就绪 — 可开始抓包",
                fg=THEME["green"])
            self._btn_install_cert.configure(
                text="🔒 重新安装 HTTPS 证书",
                state="normal")
        elif status == "exists":
            self._cert_status_icon.configure(text="⚠", fg=THEME["orange"])
            self._cert_status_text.configure(
                text="HTTPS 证书已生成，点击右侧按钮完成安装（无需管理员）",
                fg=THEME["orange"])
            self._btn_install_cert.configure(
                text="🔒 安装 HTTPS 证书（仅需一次）",
                state="normal")
        else:  # missing
            self._cert_status_icon.configure(text="❌", fg=THEME["red"])
            self._cert_status_text.configure(
                text="HTTPS 证书尚未生成 — 点击右侧按钮生成（仅需一次，约 5 秒）",
                fg=THEME["red"])
            self._btn_install_cert.configure(
                text="🔒 生成并安装 HTTPS 证书",
                state="normal")

    def _install_cert(self):
        """在后台线程生成并安装 HTTPS 证书。"""
        self._btn_install_cert.configure(state="disabled", text="⏳ 处理中...")
        self._cert_status_text.configure(
            text="正在处理 HTTPS 证书，请稍候...", fg=THEME["orange"])

        def worker():
            try:
                from lolhistory._capture_cookies import _find_ca_cert, install_cert

                cert_path = _find_ca_cert()

                if not cert_path:
                    # 证书文件不存在 — 需要先启动 mitmproxy 生成证书
                    self._msg_queue.put(("log", "HTTPS 证书文件不存在，正在启动代理引擎生成证书...\n"))
                    self._msg_queue.put(("cert_status", "generating"))

                    # GUI/exe 模式下 sys.stdout 可能为 None（noconsole），
                    # mitmproxy termlog addon 需要 .isatty() — 临时设置 dummy stdout
                    import os as _os
                    _saved_stdout = sys.stdout
                    if sys.stdout is None:
                        sys.stdout = open(_os.devnull, 'w')

                    import asyncio
                    import socket as _socket
                    from mitmproxy import options as _opts
                    from mitmproxy.tools.dump import DumpMaster

                    # 找一个空闲端口
                    port = 8081
                    opts = _opts.Options(
                        listen_host="127.0.0.1",
                        listen_port=port,
                        ssl_insecure=True,
                    )
                    loop = asyncio.new_event_loop()
                    master = DumpMaster(opts, loop=loop)

                    async def _start():
                        await master.run()

                    def _run_loop():
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(_start())
                        except Exception:
                            pass

                    t = threading.Thread(target=_run_loop, daemon=True)
                    t.start()

                    # 等待证书文件生成（最多等 10 秒）
                    cert_path = None
                    for _ in range(100):
                        time.sleep(0.1)
                        cert_path = _find_ca_cert()
                        if cert_path:
                            break

                    # 停止 mitmproxy
                    try:
                        master.shutdown()
                    except Exception:
                        pass
                    try:
                        loop.call_soon_threadsafe(loop.stop)
                    except Exception:
                        pass
                    t.join(timeout=3)
                    try:
                        loop.close()
                    except Exception:
                        pass

                    # 恢复原始 stdout
                    if _saved_stdout is None:
                        try:
                            sys.stdout.close()
                        except Exception:
                            pass
                    sys.stdout = _saved_stdout

                if not cert_path:
                    self._msg_queue.put(("cert_error", "未能生成 HTTPS 证书文件，请检查代理引擎是否正确安装"))
                    return

                # 安装证书
                self._msg_queue.put(("cert_status", "installing"))
                result = install_cert()

                if result:
                    self._msg_queue.put(("cert_done",))
                else:
                    self._msg_queue.put(("cert_error",
                        "证书安装失败，请尝试以管理员身份运行，或手动安装"))

            except ImportError as e:
                self._msg_queue.put(("cert_error",
                    f"抓包组件缺失，请重新安装本程序"))
            except Exception as e:
                self._msg_queue.put(("cert_error",
                    f"证书操作失败: {e}\n{traceback.format_exc()}"))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_cert_done(self):
        """证书安装完成。"""
        self._update_cert_status_ui("installed")
        self._capture_status.configure(
            text="✅ HTTPS 证书已安装，可以开始抓包了！", fg=THEME["green"])

    def _handle_cert_error(self, msg: str):
        """证书操作失败。"""
        # 重新检测当前状态
        status = self._check_cert_status()
        self._update_cert_status_ui(status)
        friendly = self._friendly_error(msg)
        self._capture_status.configure(
            text=f"❌ {friendly}", fg=THEME["red"])

    def _go_to_cookie(self):
        """从欢迎页跳到 Cookie 页。"""
        self._show_page(1)

    # ═══════════════════════════════════════════════════════════════════════════
    # 页面 2: 数据拉取页
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_fetch_page(self) -> tk.Frame:
        page = tk.Frame(self._content, bg=THEME["bg"])

        self._fetch_title = tk.Label(page, text="正在拉取对局数据...", font=FONT_H1,
                                      bg=THEME["bg"], fg=THEME["gold"])
        self._fetch_title.pack(anchor="w", pady=(0, 4))

        self._fetch_sub = tk.Label(page, text="准备连接 WeGame 服务器", font=FONT_SMALL,
                                    bg=THEME["bg"], fg=THEME["text2"])
        self._fetch_sub.pack(anchor="w", pady=(0, 16))

        # ── 状态卡片 ────────────────────────────────────────────────────────
        status_card = tk.Frame(page, bg=THEME["card"],
                                highlightbackground=THEME["border"],
                                highlightthickness=1)
        status_card.pack(fill="x", pady=(0, 12))

        sc_inner = tk.Frame(status_card, bg=THEME["card"])
        sc_inner.pack(fill="both", expand=True, padx=20, pady=16)

        # 连接状态
        self._status_connect = tk.Label(sc_inner, text="⏳ 等待开始...",
                                         font=FONT_BODY, bg=THEME["card"],
                                         fg=THEME["text2"])
        self._status_connect.pack(anchor="w", pady=2)

        # 召唤师信息
        self._status_summoner = tk.Label(sc_inner, text="",
                                          font=FONT_BODY, bg=THEME["card"],
                                          fg=THEME["text2"])
        self._status_summoner.pack(anchor="w", pady=2)

        # 对局列表
        self._status_list = tk.Label(sc_inner, text="",
                                      font=FONT_BODY, bg=THEME["card"],
                                      fg=THEME["text2"])
        self._status_list.pack(anchor="w", pady=2)

        # 详情获取
        self._status_detail = tk.Label(sc_inner, text="",
                                        font=FONT_BODY, bg=THEME["card"],
                                        fg=THEME["text2"])
        self._status_detail.pack(anchor="w", pady=2)

        # 分析报告
        self._status_report = tk.Label(sc_inner, text="",
                                        font=FONT_BODY, bg=THEME["card"],
                                        fg=THEME["text2"])
        self._status_report.pack(anchor="w", pady=2)

        # ── 进度条 ──────────────────────────────────────────────────────────
        prog_frame = tk.Frame(page, bg=THEME["card"],
                               highlightbackground=THEME["border"],
                               highlightthickness=1)
        prog_frame.pack(fill="x", pady=(0, 12))

        pf_inner = tk.Frame(prog_frame, bg=THEME["card"])
        pf_inner.pack(fill="both", expand=True, padx=20, pady=14)

        tk.Label(pf_inner, text="总体进度", font=FONT_SMALL,
                  bg=THEME["card"], fg=THEME["text3"]).pack(anchor="w")

        self._progress = ttk.Progressbar(pf_inner, style="Primary.Horizontal.TProgressbar",
                                          orient="horizontal", mode="determinate", length=100)
        self._progress.pack(fill="x", pady=(6, 4))

        self._progress_text = tk.Label(pf_inner, text="0%",
                                        font=FONT_SMALL, bg=THEME["card"], fg=THEME["text2"])
        self._progress_text.pack(anchor="e")

        # ── 日志区域（可折叠）───────────────────────────────────────────────
        log_header_frame = tk.Frame(page, bg=THEME["bg"])
        log_header_frame.pack(fill="x")

        self._log_toggle = tk.Label(log_header_frame, text="▸ 显示技术日志（调试用）",
                                     font=FONT_SMALL, bg=THEME["bg"],
                                     fg=THEME["text3"], cursor="hand2")
        self._log_toggle.pack(side="left")
        self._log_toggle.bind("<Button-1>", self._toggle_log)

        self._log_frame = tk.Frame(page, bg=THEME["input_bg"],
                                    highlightbackground=THEME["border"],
                                    highlightthickness=1)
        # 默认隐藏

        log_inner = tk.Frame(self._log_frame, bg=THEME["input_bg"])
        log_inner.pack(fill="both", expand=True, padx=2, pady=2)

        self._log_text = tk.Text(log_inner, font=("Consolas", 9),
                                   bg=THEME["input_bg"], fg=THEME["text2"],
                                   insertbackground=THEME["text"], relief="flat",
                                   wrap="word", state="disabled", height=10)
        self._log_text.pack(side="left", fill="both", expand=True)

        log_scroll = tk.Scrollbar(log_inner, orient="vertical",
                                   command=self._log_text.yview,
                                   bg=THEME["card"], troughcolor=THEME["bg"],
                                   activebackground=THEME["border"])
        log_scroll.pack(side="right", fill="y")
        self._log_text.configure(yscrollcommand=log_scroll.set)

        return page

    def _toggle_log(self, event=None):
        if self._log_frame.winfo_ismapped():
            self._log_frame.pack_forget()
            self._log_toggle.configure(text="▸ 显示技术日志（调试用）")
        else:
            self._log_frame.pack(fill="both", expand=True, pady=(4, 0))
            self._log_toggle.configure(text="▾ 隐藏技术日志")

    def _append_log(self, text: str):
        """追加文本到日志区。"""
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")
        self._log_lines.append(text)

    def _update_progress(self, value: float, text: str = ""):
        """更新进度条。"""
        self._progress.configure(value=value)
        self._progress_text.configure(text=text if text else f"{value:.0f}%")

    def _start_fetch(self):
        """开始拉取数据。"""
        cookies = self._collect_cookies()

        from lolhistory._wegame import validate_cookies
        missing = validate_cookies(cookies)
        if missing:
            messagebox.showwarning(
                "登录凭据不完整",
                f"缺少必需凭据: {', '.join(missing)}\n\n"
                f"请返回上一步完成凭据获取。")
            return

        # 保存 Cookie
        self._cookies = cookies
        _save_cookies(cookies)

        self._show_page(2)
        self._cancel_flag.clear()
        self._log_lines.clear()
        self._log_text.configure(state="normal")
        self._log_text.delete("0.0", "end")
        self._log_text.configure(state="disabled")
        self._update_progress(0, "准备连接...")
        self._fetch_title.configure(text="正在拉取对局数据...")

        # 后台线程执行
        self._fetch_thread = threading.Thread(target=self._fetch_worker, daemon=True)
        self._fetch_thread.start()

    def _cancel_fetch(self):
        """取消数据拉取。"""
        if messagebox.askyesno("确认取消", "确定要取消当前的数据拉取吗？"):
            self._cancel_flag.set()
            self._fetch_title.configure(text="已取消")
            self._fetch_sub.configure(text="数据拉取已被用户中止")
            self._status_connect.configure(text="⏹ 已取消", fg=THEME["red"])

    def _fetch_worker(self):
        """后台线程 — 执行完整的数据拉取 + 分析流程。"""
        try:
            cookies = self._cookies
            delay = 200
            skip_tft = True
            area = 1

            # 捕获 stdout/stderr
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            capture = OutputCapture(self._msg_queue, old_stdout)
            sys.stdout = capture
            sys.stderr = capture

            try:
                from lolhistory._wegame import (
                    WegameApiClient, WegameApiError,
                    fetch_battle_list, fetch_battle_details,
                    parse_battle_summary, parse_summoner_info,
                    parse_player_recent_stat, parse_champions,
                    parse_battle_report,
                )
                from lolhistory._data import get_wegame_tier_name
                from lolhistory._export import export_sqlite
                from lolhistory._analysis import generate_report

                # ── 阶段 1: 连接 ────────────────────────────────────────────
                self._msg_queue.put(("status", "connect", "⏳ 正在连接 WeGame 服务器..."))
                self._msg_queue.put(("progress", 2, ""))

                client = WegameApiClient(cookies)

                if not client.test_connection():
                    self._msg_queue.put(("error", "连接失败，请检查登录凭据是否有效"))
                    self._msg_queue.put(("status", "connect", "❌ 连接失败", THEME["red"]))
                    return

                self._msg_queue.put(("status", "connect", "✅ 连接成功", THEME["green"]))
                self._msg_queue.put(("progress", 5, ""))

                # ── 阶段 2: 召唤师信息 ───────────────────────────────────────
                self._msg_queue.put(("status", "summoner", "⏳ 获取召唤师信息..."))
                self._msg_queue.put(("progress", 8, ""))

                summoner_profile = None
                summoner_career = None
                champions_data = None
                battle_report_data = None
                openid = ""

                try:
                    si = client.get_summoner_info(area=area)
                    summoner_profile = parse_summoner_info(si)
                    name = summoner_profile.get("召唤师名称", "Unknown")
                    tag = summoner_profile.get("标签", "")
                    level = summoner_profile.get("等级", 0)
                    tier = summoner_profile.get("段位", 0)
                    lp = summoner_profile.get("胜点", 0)
                    season_wins = summoner_profile.get("赛季胜场", 0)
                    season_total = summoner_profile.get("赛季总场次", 0)
                    display = f"{name}#{tag}" if tag else name
                    tier_name = get_wegame_tier_name(tier) if tier else "无段位"
                    if lp and tier:
                        tier_name = f"{tier_name} {lp}LP"
                    wr = (season_wins / max(season_total, 1) * 100) if season_total else 0

                    self._msg_queue.put(("status", "summoner",
                        f"✅ 召唤师: {display}  |  Lv.{level}  |  {tier_name}  |  "
                        f"赛季: {season_wins}W/{season_total - season_wins}L ({wr:.1f}%)",
                        THEME["green"]))
                    self._msg_queue.put(("progress", 12, ""))

                    openid = summoner_profile.get("openid", "")
                    if openid and not client.openid:
                        client.set_openid(openid)

                    # 获取生涯统计
                    if openid:
                        sc = client.get_player_recent_stat(openid, area=area)
                        summoner_career = parse_player_recent_stat(sc)
                        total_k = summoner_career.get("生涯总击杀", 0)
                        total_v = summoner_career.get("生涯MVP", 0)
                        total_p = summoner_career.get("生涯五杀", 0)
                        max_ws = summoner_career.get("最长连胜", 0)
                        self._msg_queue.put(("status", "summoner",
                            f"✅ 生涯: {total_k}击杀 | MVP×{total_v} | 五杀×{total_p} | 最长连胜{max_ws}",
                            THEME["green"]))

                        # 获取英雄熟练度
                        self._msg_queue.put(("progress", 15, ""))
                        cr = client.get_champions(openid, area=area)
                        champions_data = parse_champions(cr)
                        self._msg_queue.put(("log", f"英雄熟练度: {len(champions_data)} 个英雄\n"))

                    # 获取赛季报告
                    self._msg_queue.put(("progress", 18, ""))
                    br = client.get_battle_report(area=area)
                    battle_report_data = parse_battle_report(br)
                    bc = battle_report_data.get("battle_count", {})
                    self._msg_queue.put(("log",
                        f"战斗报告: 全模式 {bc.get('全部总场', 0)} 场\n"))

                except WegameApiError as e:
                    self._msg_queue.put(("log", f"⚠ 召唤师/生涯信息获取失败: {e}\n"))
                except Exception as e:
                    self._msg_queue.put(("log", f"⚠ 意外错误: {e}\n"))

                # ── 阶段 3: 对局列表 ─────────────────────────────────────────
                self._msg_queue.put(("status", "list", "⏳ 正在获取对局列表..."))
                self._msg_queue.put(("progress", 20, "获取对局列表中..."))

                max_games = 501

                # 查询已有对局 ID 以跳过重复获取（与 CLI 保持一致）
                existing_ids = set()
                db_path_for_check = str(BASE_DIR / "wegame_matches.db")
                if Path(db_path_for_check).exists():
                    try:
                        import sqlite3 as _sqlite3
                        conn = _sqlite3.connect(db_path_for_check)
                        rows = conn.execute(
                            "SELECT game_id FROM match_summary WHERE area = ?",
                            (area,)
                        ).fetchall()
                        existing_ids = {r[0] for r in rows}
                        conn.close()
                        if existing_ids:
                            self._msg_queue.put(
                                ("log", f"数据库已有 {len(existing_ids)} 条记录，将跳过重复获取\n"))
                    except Exception:
                        pass

                try:
                    all_battles = fetch_battle_list(
                        client, area=area, max_games=max_games,
                        skip_tft=skip_tft, delay_ms=delay,
                        existing_ids=existing_ids if existing_ids else None,
                    )
                except Exception as e:
                    self._msg_queue.put(
                        ("error", f"获取对局列表失败: {e}\n{traceback.format_exc()}"))
                    return

                total = len(all_battles)
                self._total_games = total
                wins = sum(1 for b in all_battles if b.get("win") == "Win")
                self._total_wins = wins
                wr_all = (wins / total * 100) if total > 0 else 0
                self._msg_queue.put(("status", "list",
                    f"✅ 获取完成: {total} 场  |  {wins}W/{total - wins}L  |  {wr_all:.1f}%",
                    THEME["green"]))
                self._msg_queue.put(("progress", 40, f"已获取 {total} 场对局"))

                if self._cancel_flag.is_set():
                    return
                if total == 0:
                    self._msg_queue.put(("error", "未找到对局记录"))
                    return

                # ── 阶段 4: 对局详情 ─────────────────────────────────────────
                self._msg_queue.put(("status", "detail", "⏳ 正在获取对局详情..."))
                detail_data = {}
                game_ids = [str(b.get("game_id", "")) for b in all_battles
                           if b.get("game_id")]
                game_ids_set = set(game_ids)

                # 查询已有详情 + 回填缺失详情（与 CLI 保持一致）
                existing_detail_ids: set[str] = set()
                backfill_ids: set[str] = set()
                db_detail_path = str(BASE_DIR / "wegame_matches.db")
                if Path(db_detail_path).exists():
                    try:
                        import sqlite3 as _sqlite3
                        conn = _sqlite3.connect(db_detail_path)
                        rows = conn.execute(
                            "SELECT DISTINCT game_id FROM match_detail WHERE area = ?",
                            (area,)
                        ).fetchall()
                        existing_detail_ids = {r[0] for r in rows}
                        # 回填：match_summary 有但 match_detail 缺失的对局
                        rows2 = conn.execute("""
                            SELECT DISTINCT ms.game_id FROM match_summary ms
                            WHERE ms.area = ?
                            AND ms.game_id NOT IN (
                                SELECT DISTINCT game_id FROM match_detail WHERE area = ?
                            )
                        """, (area, area)).fetchall()
                        backfill_ids = {r[0] for r in rows2}
                        conn.close()
                    except Exception:
                        pass

                # 合并：当前获取的对局在前，历史缺失详情的对局在后
                new_backfill = backfill_ids - game_ids_set - existing_detail_ids
                if new_backfill:
                    self._msg_queue.put(
                        ("log", f"发现 {len(new_backfill)} 场历史对局缺少详情，将一并补获取\n"))
                all_detail_ids = game_ids + sorted(new_backfill)

                new_game_ids = [gid for gid in all_detail_ids
                                if gid not in existing_detail_ids]
                skipped = len(all_detail_ids) - len(new_game_ids)
                if skipped:
                    self._msg_queue.put(
                        ("log", f"详情: {skipped} 场已有，跳过；需获取 {len(new_game_ids)} 场\n"))

                self._msg_queue.put(("progress", 45,
                    f"正在获取详情: 0/{len(new_game_ids)}"))

                if new_game_ids:
                    try:
                        detail_data = fetch_battle_details(
                            client, new_game_ids, area=area, delay_ms=delay)
                    except Exception as e:
                        self._msg_queue.put(
                            ("error", f"获取对局详情失败: {e}\n{traceback.format_exc()}"))
                        return

                    detail_ok = sum(1 for v in detail_data.values()
                                   if "error" not in v)
                    self._msg_queue.put(("status", "detail",
                        f"✅ 详情: {detail_ok}/{len(new_game_ids)} 场",
                        THEME["green"] if detail_ok == len(new_game_ids) else THEME["orange"]))
                    self._msg_queue.put(("progress", 75,
                        f"详情: {detail_ok}/{len(new_game_ids)} 场"))
                else:
                    self._msg_queue.put(("status", "detail",
                        "✅ 详情: 全部已有，无需获取", THEME["green"]))
                    self._msg_queue.put(("progress", 75, "详情: 全部已有"))

                # ── 阶段 5: 导出 ────────────────────────────────────────────
                self._msg_queue.put(("status", "export", "⏳ 正在导出数据..."))
                self._msg_queue.put(("progress", 80, "导出中..."))

                parsed = [parse_battle_summary(b, area=area) for b in all_battles]
                db_path = str(BASE_DIR / "wegame_matches.db")
                self._db_path = db_path

                try:
                    export_sqlite(parsed, detail_data or None, db_path,
                                self_openid=client.openid or "",
                                summoner_info=summoner_profile,
                                summoner_career=summoner_career,
                                puin=client.puin,
                                champions=champions_data,
                                battle_report=battle_report_data,
                                area=area)
                except Exception as e:
                    self._msg_queue.put(
                        ("error", f"导出数据失败: {e}\n{traceback.format_exc()}"))
                    return

                self._msg_queue.put(("status", "export",
                    f"✅ 已导出到 {db_path}", THEME["green"]))
                self._msg_queue.put(("progress", 88, "数据已导出"))

                # ── 阶段 6: 分析报告 ────────────────────────────────────────
                self._msg_queue.put(("status", "report", "⏳ 正在生成分析报告..."))
                self._msg_queue.put(("progress", 90, "生成报告中..."))

                try:
                    report_path = generate_report(
                        db_path=db_path,
                        output_path="report.html",
                    )
                except Exception as e:
                    self._msg_queue.put(
                        ("error", f"生成分析报告失败: {e}\n{traceback.format_exc()}"))
                    return

                self._report_path = report_path
                self._msg_queue.put(("status", "report",
                    f"✅ 报告已生成: {report_path}", THEME["green"]))
                self._msg_queue.put(("progress", 100, "完成！"))

                # ── 完成 ────────────────────────────────────────────────────
                client.close()
                self._msg_queue.put(("fetch_done", total, wins, report_path))

            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        except Exception as e:
            self._msg_queue.put(("error", f"数据拉取失败: {e}\n{traceback.format_exc()}"))

    def _handle_fetch_done(self, total: int, wins: int, report_path: str):
        """拉取完成，切换到完成页。"""
        self._total_games = total
        self._total_wins = wins
        self._report_path = report_path
        self._fetch_title.configure(text="拉取完成！")
        self._fetch_sub.configure(text=f"共获取 {total} 场对局记录")
        self._show_page(3)

    def _handle_error(self, msg: str):
        """处理全局错误。"""
        friendly = self._friendly_error(msg)
        messagebox.showerror("错误", friendly)
        self._show_page(1)

    # ═══════════════════════════════════════════════════════════════════════════
    # 页面 3: 完成页
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_complete_page(self) -> tk.Frame:
        page = tk.Frame(self._content, bg=THEME["bg"])

        self._complete_title = tk.Label(page, text="🎉 分析报告已生成！",
                                         font=FONT_TITLE, bg=THEME["bg"],
                                         fg=THEME["gold"])
        self._complete_title.pack(anchor="w", pady=(0, 16))

        # ── 统计概览卡片 ────────────────────────────────────────────────────
        stats_card = tk.Frame(page, bg=THEME["card"],
                               highlightbackground=THEME["border"],
                               highlightthickness=1)
        stats_card.pack(fill="x", pady=(0, 20))

        sc_inner = tk.Frame(stats_card, bg=THEME["card"])
        sc_inner.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(sc_inner, text="数据概览", font=FONT_H2,
                  bg=THEME["card"], fg=THEME["gold"]).pack(anchor="w", pady=(0, 6))

        self._hero_grid = tk.Frame(sc_inner, bg=THEME["card"])
        self._hero_grid.pack(fill="x")

        # 6 个 hero stat 卡片
        hero_items = [
            ("对局总数", "0", "场"),
            ("胜率", "0", "%"),
            ("胜场 / 负场", "0 / 0", ""),
            ("数据库", "wegame_matches.db", ""),
            ("报告文件", "report.html", ""),
            ("时间", datetime.now().strftime("%Y-%m-%d %H:%M"), ""),
        ]
        self._hero_labels: dict[str, tk.Label] = {}

        for i, (label, value, unit) in enumerate(hero_items):
            item = tk.Frame(self._hero_grid, bg=THEME["card2"],
                             highlightbackground=THEME["border"],
                             highlightthickness=1)
            item.grid(row=i // 3, column=i % 3, sticky="nsew",
                       padx=(0 if (i % 3) == 2 else 6, 0 if (i % 3) == 2 else 6),
                       pady=(0 if i // 3 == 0 else 6, 0))

            for col in range(3):
                self._hero_grid.grid_columnconfigure(col, weight=1)

            item_inner = tk.Frame(item, bg=THEME["card2"])
            item_inner.pack(fill="both", expand=True, padx=14, pady=12)

            val_lbl = tk.Label(item_inner, text=f"{value} {unit}",
                                font=("Microsoft YaHei", 18, "bold"),
                                bg=THEME["card2"], fg=THEME["gold"])
            val_lbl.pack()
            self._hero_labels[label] = val_lbl

            tk.Label(item_inner, text=label, font=FONT_SMALL,
                      bg=THEME["card2"], fg=THEME["text2"]).pack(pady=(2, 0))

        # ── 操作按钮区 ──────────────────────────────────────────────────────
        btn_card = tk.Frame(page, bg=THEME["card"],
                             highlightbackground=THEME["border"],
                             highlightthickness=1)
        btn_card.pack(fill="x")

        bc_inner = tk.Frame(btn_card, bg=THEME["card"])
        bc_inner.pack(fill="both", expand=True, padx=24, pady=16)

        tk.Label(bc_inner, text="下一步操作", font=FONT_H2,
                  bg=THEME["card"], fg=THEME["gold"]).pack(anchor="w", pady=(0, 10))

        btn_row = tk.Frame(bc_inner, bg=THEME["card"])
        btn_row.pack(fill="x")

        self._btn_open_report = tk.Button(
            btn_row, text="📊 在浏览器中打开分析报告", font=FONT_BTN,
            bg=THEME["gold"], fg=THEME["bg"], activebackground="#d4b87a",
            activeforeground=THEME["bg"], relief="flat",
            padx=24, pady=12, cursor="hand2", borderwidth=0,
            command=self._open_report)
        self._btn_open_report.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self._btn_open_folder = tk.Button(
            btn_row, text="📁 打开输出文件夹", font=FONT_BTN,
            bg=THEME["card2"], fg=THEME["text"], activebackground=THEME["hover"],
            activeforeground=THEME["text"], relief="flat",
            padx=24, pady=12, cursor="hand2", borderwidth=1,
            command=self._open_folder)
        self._btn_open_folder.pack(side="left", fill="x", expand=True)

        return page

    def _update_complete_stats(self, total: int, wins: int, report_path: str):
        """更新完成页的统计数据。"""
        from pathlib import Path
        losses = total - wins
        wr = (wins / total * 100) if total > 0 else 0

        stats = {
            "对局总数": (str(total), "场"),
            "胜率": (f"{wr:.1f}", "%"),
            "胜场 / 负场": (f"{wins} / {losses}", ""),
            "数据库": (Path(self._db_path).name if self._db_path else "wegame_matches.db", ""),
            "报告文件": (Path(report_path).name, ""),
            "时间": (datetime.now().strftime("%Y-%m-%d %H:%M"), ""),
        }

        for label, (value, unit) in stats.items():
            if label in self._hero_labels:
                self._hero_labels[label].configure(text=f"{value} {unit}".strip())

    # ═══════════════════════════════════════════════════════════════════════════
    # 操作
    # ═══════════════════════════════════════════════════════════════════════════

    def _open_report(self):
        """在浏览器中打开分析报告。"""
        if self._report_path and Path(self._report_path).exists():
            webbrowser.open(f"file:///{Path(self._report_path).resolve()}")
        else:
            messagebox.showinfo("提示", "报告尚未生成。")

    def _open_folder(self):
        """打开输出文件夹。"""
        import subprocess
        p = str(BASE_DIR.resolve())
        try:
            os.startfile(p)
        except Exception:
            subprocess.run(["explorer", p], shell=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # 消息轮询 — 线程安全的 GUI 更新
    # ═══════════════════════════════════════════════════════════════════════════

    def _poll_messages(self):
        """定时检查消息队列，在主线程更新 GUI。"""
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == "log":
                    self._append_log(msg[1])
                    # 解析进度信息，实时更新进度条
                    text = msg[1]
                    m = re.search(r'已获取:\s*(\d+)\s*场对局', text)
                    if m:
                        count = int(m.group(1))
                        pct = min(20 + (count / max(self._total_games or 1, 1)) * 20, 40)
                        self._update_progress(pct, f"已获取 {count} 场对局")
                    m = re.search(r'获取详情:\s*(\d+)/(\d+)', text)
                    if m:
                        cur, total = int(m.group(1)), int(m.group(2))
                        pct = min(45 + (cur / max(total, 1)) * 30, 75)
                        self._update_progress(pct, f"详情: {cur}/{total}")

                elif msg_type == "capture_log":
                    # 抓包实时日志 → 更新状态提示
                    text = msg[1]
                    self._append_log(text)
                    if "代理已开启" in text or "正在监听" in text:
                        self._capture_status.configure(
                            text="✅ 代理引擎已就绪 — 请打开并登录 WeGame",
                            fg=THEME["green"])
                        self._btn_capture.configure(text="⏳ 等待登录...")
                    elif "等待中" in text:
                        self._capture_status.configure(
                            text="⏳ 等待 WeGame 登录… 请打开 WeGame 客户端并登录您的账号",
                            fg=THEME["orange"])
                    elif "成功提取" in text or "已捕获全部" in text:
                        self._capture_status.configure(
                            text="🎉 已获取全部凭据！正在保存…",
                            fg=THEME["blue"])

                elif msg_type == "status":
                    _, key, text, *rest = msg
                    color = rest[0] if rest else THEME["text2"]
                    if key == "connect":
                        self._status_connect.configure(text=text, fg=color)
                    elif key == "summoner":
                        self._status_summoner.configure(text=text, fg=color)
                    elif key == "list":
                        self._status_list.configure(text=text, fg=color)
                    elif key == "detail":
                        self._status_detail.configure(text=text, fg=color)
                    elif key == "report":
                        self._status_report.configure(text=text, fg=color)
                    elif key == "export":
                        pass  # 不显示额外状态

                elif msg_type == "progress":
                    _, value, text = msg
                    self._update_progress(value, text)

                elif msg_type == "capture_done":
                    self._handle_capture_done(msg[1])

                elif msg_type == "capture_fail":
                    self._handle_capture_fail(msg[1])

                elif msg_type == "capture_error":
                    self._handle_capture_error(msg[1])

                elif msg_type == "cert_status":
                    # 证书操作进度更新
                    if msg[1] == "generating":
                        self._cert_status_text.configure(
                            text="正在生成 HTTPS 证书文件...", fg=THEME["orange"])
                    elif msg[1] == "installing":
                        self._cert_status_text.configure(
                            text="正在安装 HTTPS 证书到系统...", fg=THEME["orange"])

                elif msg_type == "cert_done":
                    self._handle_cert_done()

                elif msg_type == "cert_error":
                    self._handle_cert_error(msg[1])

                elif msg_type == "fetch_done":
                    self._handle_fetch_done(msg[1], msg[2], msg[3])
                    self._update_complete_stats(msg[1], msg[2], msg[3])

                elif msg_type == "error":
                    self._handle_error(msg[1])

        except queue.Empty:
            pass

        self.root.after(100, self._poll_messages)

    def _setup_close_handler(self):
        """窗口关闭时的清理。"""
        def on_close():
            if self._fetch_thread and self._fetch_thread.is_alive():
                if messagebox.askyesno("确认退出", "数据拉取正在进行中，确定要退出吗？"):
                    self._cancel_flag.set()
                    self.root.after(500, self.root.destroy)
            else:
                self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", on_close)

    def run(self):
        """启动 GUI 主循环。"""
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    # 修复 Windows GBK 终端编码问题
    import io as _io
    if hasattr(sys.stdout, 'buffer'):
        try:
            sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        except Exception:
            pass

    app = LOLHistoryApp()
    app.run()


if __name__ == "__main__":
    main()
