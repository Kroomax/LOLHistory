"""从抓包导出文件中提取 WeGame Cookie（支持 Fiddler/Charles/浏览器）。

属于方法3（WeGame API）的 Cookie 获取环节。

用法（通过 CLI）:
    python -m lolhistory --extract-cookies                  # 扫描 wegame-api-export/
    python -m lolhistory --extract-cookies ./my-exports/    # 自定义目录
    python -m lolhistory --extract-cookies -c cookies.json  # 自定义输出路径

支持的导出格式:
    HAR (.har)      — Fiddler: File → Export Sessions → HTTP Archive
                       Charles: File → Export → HAR
    Raw request     — Fiddler: File → Export → Raw Files, 或右键 → Save → Request → Raw
    cURL command    — 浏览器 DevTools / Fiddler: Copy as cURL
    Any text file   — 包含 "Cookie: key=value; ..." 行的文本文件
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REQUIRED_COOKIE_KEYS = ["puin", "pkey", "tgp_biz_ticket", "tgp_id"]

# 按优先级排序的扫描文件扩展名
_SCAN_EXTENSIONS = [".har", ".json", ".txt"]


def _read_file(filepath: Path) -> str:
    """读取文件内容，依次尝试 UTF-8、UTF-8-BOM、GBK、Latin-1 编码。"""
    for enc in ["utf-8", "utf-8-sig", "gbk", "latin-1"]:
        try:
            return filepath.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return filepath.read_text(encoding="utf-8", errors="replace")


def parse_cookie_header(cookie_str: str) -> dict[str, str]:
    """解析原始 Cookie 请求头，返回 name→value 字典。

    示例:
        "puin=123; pkey=abc; tgp_biz_ticket=def; tgp_id=456"
        → {"puin": "123", "pkey": "abc", "tgp_biz_ticket": "def", "tgp_id": "456"}
    """
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            name = name.strip()
            value = value.strip()
            if name and value:
                cookies[name] = value
    return cookies


def _score_cookies(cookies: dict[str, str]) -> int:
    """统计匹配到 WeGame 必需 Cookie 的数量。"""
    return sum(1 for k in REQUIRED_COOKIE_KEYS if k in cookies and cookies[k])


def _pick_best(current: dict[str, str], candidate: dict[str, str]) -> dict[str, str]:
    """返回包含更多 WeGame 必需 Cookie 的字典。"""
    if _score_cookies(candidate) > _score_cookies(current):
        return candidate
    return current


# ── HAR 格式 ────────────────────────────────────────────────────────────────

def extract_cookies_from_har(filepath: Path) -> dict[str, str]:
    """从 HAR（HTTP Archive）文件中提取 WeGame Cookie。

    扫描所有请求条目，取包含最多必需 Cookie 的请求。
    同时支持 ``request.cookies``（已解析格式）和 ``request.headers.Cookie``。
    """
    content = _read_file(filepath)
    try:
        har = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"HAR JSON 格式无效 '{filepath}': {e}") from e

    entries = har.get("log", {}).get("entries", [])
    best: dict[str, str] = {}

    for entry in entries:
        request = entry.get("request", {})

        # 方式1：已解析的 cookies 数组（最可靠）
        parsed = request.get("cookies", [])
        if isinstance(parsed, list):
            cookies = {c["name"]: c["value"] for c in parsed
                       if isinstance(c, dict) and "name" in c and "value" in c}
            best = _pick_best(best, cookies)
            if _score_cookies(best) == len(REQUIRED_COOKIE_KEYS):
                return _filter_required(best)

        # 方式2：原始 Cookie 请求头
        for header in request.get("headers", []):
            if not isinstance(header, dict):
                continue
            if header.get("name", "").lower() == "cookie":
                cookies = parse_cookie_header(header.get("value", ""))
                best = _pick_best(best, cookies)

    return best


# ── Raw HTTP 请求导出（Fiddler "Export → Raw Files"） ───────────────────────

def extract_cookies_from_raw(filepath: Path) -> dict[str, str]:
    """从原始 HTTP 请求文本导出中提取 Cookie。

    处理两种常见导出格式:

    1. Fiddler "Export → Raw Files" — 所有 Cookie 在一行::

        Cookie: puin=...; pkey=...; tgp_biz_ticket=...; tgp_id=...

    2. Charles 请求导出 — 每个 Cookie 单独一行::

        cookie: puin=1079564392
        cookie: pkey=0003...
        cookie: tgp_biz_ticket=0100...
        cookie: tgp_id=12460692

    汇总所有匹配行中的 Cookie，重复键以后出现的为准。
    """
    content = _read_file(filepath)

    # 匹配所有 "Cookie: <value>" 行（不区分大小写）
    cookie_re = re.compile(r'^Cookie:\s*(.+)$', re.MULTILINE | re.IGNORECASE)
    matches = cookie_re.findall(content)

    # 从所有匹配行汇总 Cookie（后出现的覆盖先出现的）
    all_cookies: dict[str, str] = {}
    for match in matches:
        all_cookies.update(parse_cookie_header(match))

    return all_cookies


# ── cURL 命令导出 ──────────────────────────────────────────────────────────

def extract_cookies_from_curl(filepath: Path) -> dict[str, str]:
    """从 cURL 命令中提取 Cookie（浏览器 DevTools / Fiddler 复制）。

    支持以下格式::

        curl 'https://...' -H 'Cookie: puin=...; pkey=...; ...'
        curl 'https://...' --cookie 'puin=...; pkey=...; ...'
    """
    content = _read_file(filepath)

    # -H 'Cookie: ...'  或  -H "Cookie: ..."
    cookie_re = re.compile(
        r"(?:-H|--header)\s+['\"]\s*Cookie:\s*(.+?)\s*['\"]",
        re.MULTILINE | re.IGNORECASE,
    )
    matches = cookie_re.findall(content)

    # --cookie '...'  或  --cookie "..."
    cookie_arg_re = re.compile(
        r"--cookie\s+['\"]\s*(.+?)\s*['\"]",
        re.MULTILINE | re.IGNORECASE,
    )
    matches += cookie_arg_re.findall(content)

    best: dict[str, str] = {}
    for match in matches:
        cookies = parse_cookie_header(match)
        best = _pick_best(best, cookies)
        if _score_cookies(best) == len(REQUIRED_COOKIE_KEYS):
            break

    return best


# ── Charles 会话导出（JSON） ─────────────────────────────────────────────────

def extract_cookies_from_charles(filepath: Path) -> dict[str, str]:
    """从 Charles 会话导出文件（.chlsj / JSON）中提取 Cookie。

    Charles 会话文件的结构与 HAR 不同。
    """
    content = _read_file(filepath)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}

    best: dict[str, str] = {}

    def _walk(obj, depth=0):
        nonlocal best
        if depth > 10 or not isinstance(obj, (dict, list)):
            return
        if isinstance(obj, list):
            for item in obj:
                _walk(item, depth + 1)
            return
        # 检查当前层级的 Cookie 请求头
        for key in ("request", "headers", "header"):
            pass
        # 在 headers 中查找 Cookie
        headers = obj.get("headers")
        if isinstance(headers, dict):
            for hk, hv in headers.items():
                if isinstance(hk, str) and hk.lower() == "cookie":
                    best = _pick_best(best, parse_cookie_header(str(hv)))
        if isinstance(headers, list):
            for h in headers:
                if isinstance(h, dict) and h.get("name", "").lower() == "cookie":
                    best = _pick_best(best, parse_cookie_header(h.get("value", "")))
        if isinstance(obj.get("request"), dict):
            # 仅递归进入 request 对象
            for h in obj["request"].get("headers", []):
                if isinstance(h, dict) and h.get("name", "").lower() == "cookie":
                    best = _pick_best(best, parse_cookie_header(h.get("value", "")))
        for v in obj.values():
            if isinstance(v, (dict, list)):
                _walk(v, depth + 1)

    _walk(data)
    return best


# ── 自动识别 & 顶层接口 ─────────────────────────────────────────────────────

def _filter_required(cookies: dict[str, str]) -> dict[str, str]:
    """仅保留 WeGame 必需的四项 Cookie。"""
    return {k: cookies[k] for k in REQUIRED_COOKIE_KEYS if k in cookies and cookies[k]}


def extract_cookies(filepath: Path) -> dict[str, str]:
    """自动识别格式并提取 WeGame Cookie。

    返回所有找到的 Cookie 字典（可能包含非必需键）。
    如需仅保留四项必需 Cookie，请使用 :func:`_filter_required`。
    """
    suffix = filepath.suffix.lower()

    if suffix in (".har",):
        return extract_cookies_from_har(filepath)

    if suffix in (".json",):
        # 先尝试 HAR 格式（含 "log"."entries" 结构）
        cookies = extract_cookies_from_har(filepath)
        if _score_cookies(cookies) > 0:
            return cookies
        # 回退到 Charles 格式
        return extract_cookies_from_charles(filepath)

    # .txt 及未知扩展名：依次尝试 raw HTTP、curl、通用文本
    cookies = extract_cookies_from_raw(filepath)
    if _score_cookies(cookies) >= 2:
        return cookies

    cookies = _pick_best(cookies, extract_cookies_from_curl(filepath))
    return cookies


def find_latest_request_file(export_dir: str = "wegame-api-export") -> Optional[Path]:
    """在导出目录中查找最近修改的请求文件。

    扫描 ``.har``、``.json``、``.txt`` 及无扩展名的文件，
    按修改时间取最新者。目录不存在或为空时返回 ``None``。
    """
    p = Path(export_dir)
    if not p.is_dir():
        return None

    files: list[Path] = []
    for ext in _SCAN_EXTENSIONS:
        files.extend(p.glob(f"*{ext}"))
    # 同时包含未知扩展名的文件（如无扩展名文件）
    seen = set(files)
    for f in p.iterdir():
        if f.is_file() and f not in seen:
            files.append(f)

    if not files:
        return None

    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0]


def auto_extract_and_save(export_dir: str = "wegame-api-export",
                          output: str = "cookies.json") -> dict[str, str]:
    """查找最新请求文件 → 提取 WeGame Cookie → 保存为 JSON。

    这是主入口函数，流程如下:

    1. 扫描 *export_dir* 目录，找到最新的请求文件
    2. 自动识别格式（HAR / raw / curl / Charles）
    3. 提取四项必需 Cookie: ``puin``、``pkey``、``tgp_biz_ticket``、``tgp_id``
    4. 保存到 *output* JSON 文件
    5. 返回 Cookie 字典

    可能抛出的异常:
        FileNotFoundError: *export_dir* 中未找到任何请求文件。
        ValueError: 从最佳文件中未能提取到任何 WeGame Cookie。
    """
    filepath = find_latest_request_file(export_dir)
    if not filepath:
        raise FileNotFoundError(
            f"在 '{export_dir}' 中未找到任何请求文件。\n"
            f"请先从 Fiddler 或 Charles 中导出请求到此目录。\n"
            f"\n"
            f"  Fiddler:  右键会话 → Export → Raw Files\n"
            f"            或 File → Export Sessions → HTTP Archive\n"
            f"  Charles:  右键请求 → Export → HAR\n"
            f"  浏览器:   DevTools → Network → 右键请求 → Copy as cURL → 粘贴到 .txt 文件"
        )

    logger.info("找到文件: %s", filepath)
    logger.info("  修改时间: %s", filepath.stat().st_mtime)

    print(f"找到请求文件: {filepath.name}")
    print(f"  路径: {filepath}")

    # 提取所有 Cookie
    all_cookies = extract_cookies(filepath)
    logger.info("原始提取到的 Cookie: %s", list(all_cookies.keys()))

    # 过滤仅保留必需项
    result = _filter_required(all_cookies)

    if not result:
        found = list(all_cookies.keys())
        raise ValueError(
            f"在 '{filepath.name}' 中未找到 WeGame Cookie。\n"
            f"请确认导出的请求目标为 www.wegame.com.cn，\n"
            f"且包含以下 Cookie: {', '.join(REQUIRED_COOKIE_KEYS)}。\n"
            f"实际找到的键: {found if found else '(无)'}"
        )

    # 打印提取结果
    print(f"\n成功提取 {len(result)}/4 项必需 Cookie:")
    for k in REQUIRED_COOKIE_KEYS:
        if k in result:
            val = result[k]
            preview = val[:40] + "..." if len(val) > 40 else val
            print(f"  [✓] {k} = {preview}")
        else:
            print(f"  [✗] {k}")

    # 保存到 JSON
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nCookie 已保存 → {output_path}")

    # 警告缺失的键
    missing = [k for k in REQUIRED_COOKIE_KEYS if k not in result]
    if missing:
        logger.warning("缺少必需 Cookie: %s", missing)
        print(f"\n[警告] 缺少以下 Cookie: {', '.join(missing)}")
        print(f"   缺少全部 4 项 Cookie 时 API 可能无法正常使用。")

    return result
