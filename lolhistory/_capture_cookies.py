"""mitmproxy 内嵌抓包 — 一键提取 WeGame Cookie。

替换 Reqable/Fiddler 手动抓包流程。
用法: python -m lolhistory --capture-cookies [-o cookies.json]

技术方案：系统代理 + mitmproxy HTTP 代理。
WeGame QBCore 走系统代理，Cookie 头中包含完整认证信息（逗号分隔）。
"""

import asyncio
import atexit
import json
import logging
import socket as std_socket
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from mitmproxy import options
from mitmproxy.http import HTTPFlow
from mitmproxy.tools.dump import DumpMaster

logger = logging.getLogger(__name__)

REQUIRED_KEYS = ["puin", "pkey", "tgp_biz_ticket", "tgp_id"]


# ── Cookie 解析 ────────────────────────────────────────────────────────────────

def _parse_cookies(cookie_header: str) -> dict[str, str]:
    """解析 Cookie 头，兼容逗号和分号分隔符。

    WeGame QBCore 使用逗号分隔 cookie（如 "puin=123, pkey=abc, ..."），
    而非标准的 "; " 分隔。此函数兼容两种格式。
    """
    parsed = {}
    for part in cookie_header.split(";"):
        for subpart in part.split(","):
            subpart = subpart.strip()
            if "=" in subpart:
                k, _, v = subpart.partition("=")
                k = k.strip()
                v = v.strip()
                if k and v:
                    parsed[k] = v
    return parsed


# ── Windows 系统代理 ──────────────────────────────────────────────────────────

def _set_windows_proxy(proxy_addr: str = "127.0.0.1:8080", enable: bool = True):
    """设置/取消 Windows 系统代理（注册表）。"""
    try:
        import winreg
    except ImportError:
        return
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                             winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    except OSError:
        return
    try:
        if enable:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_addr)
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
    finally:
        winreg.CloseKey(key)


def _get_windows_proxy() -> Optional[str]:
    """获取当前 Windows 系统代理设置。"""
    try:
        import winreg
    except ImportError:
        return None
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if enabled:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            winreg.CloseKey(key)
            return server
        winreg.CloseKey(key)
    except OSError:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 安全恢复 — 确保无论进程如何退出都会关闭代理
# ═══════════════════════════════════════════════════════════════════════════════

_proxy_was_enabled = False
_original_proxy = None


def _cleanup_proxy():
    """atexit 回调 — 确保系统代理被恢复。"""
    global _proxy_was_enabled
    if _proxy_was_enabled:
        try:
            _set_windows_proxy(enable=False)
            _proxy_was_enabled = False
        except Exception:
            pass


atexit.register(_cleanup_proxy)


# ── mitmproxy Addon ──────────────────────────────────────────────────────────

class WegameCookieCapture:
    """mitmproxy addon — 监听 wegame.com.cn 请求，提取必需 Cookie。

    检测到全部 4 项必需 Cookie 后自动发出完成信号。
    """

    def __init__(self, target_domain: str = "www.wegame.com.cn"):
        self.target_domain = target_domain
        self.cookies: dict[str, str] = {}
        self._done = threading.Event()
        self._request_count = 0

    def request(self, flow: HTTPFlow):
        """拦截每个请求，检查目标域名的 Cookie 头。"""
        if self._done.is_set():
            return

        # 检查是否为目标域名
        if self.target_domain not in flow.request.host:
            return

        cookie_header = flow.request.headers.get("Cookie", "")
        if not cookie_header:
            return

        # 解析 Cookie 头（兼容逗号/分号）
        parsed = _parse_cookies(cookie_header)

        self._request_count += 1

        # DEBUG: 前 3 次显示 cookie keys
        if self._request_count <= 3:
            logger.info("[%d] %s %s — cookie keys: %s",
                        self._request_count, flow.request.method,
                        flow.request.path[:60], list(parsed.keys())[:15])

        # 筛选必需 cookie
        found = {k: parsed[k] for k in REQUIRED_KEYS if k in parsed}
        new_count = len(found) - len(self.cookies)

        if len(found) > len(self.cookies):
            self.cookies.update(found)
            missing = [k for k in REQUIRED_KEYS if k not in found]
            logger.info("提取到 %d 项 cookie (+%d)，仍缺: %s",
                        len(found), new_count,
                        ", ".join(missing) if missing else "无")

        # 全部捕获 → 停止
        if all(k in self.cookies for k in REQUIRED_KEYS):
            logger.info("[OK] 已捕获全部 4 项必需 Cookie！")
            self._done.set()

    def is_done(self) -> bool:
        return self._done.is_set()

    @property
    def missing_keys(self) -> list[str]:
        return [k for k in REQUIRED_KEYS if k not in self.cookies]


# ── 根证书管理 ───────────────────────────────────────────────────────────────

def _find_ca_cert() -> Optional[Path]:
    """查找 mitmproxy 根证书路径。"""
    candidates = [
        Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem",
        Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def install_cert() -> bool:
    """安装 mitmproxy 根证书到 Windows 用户级信任存储（certutil -user）。"""
    cert_path = _find_ca_cert()
    if not cert_path:
        print("[错误] 未找到 mitmproxy 根证书。")
        print("  请先运行一次 mitmproxy 以生成证书：")
        print("  python -m lolhistory --capture-cookies")
        print("  （首次运行会自动生成证书，Ctrl+C 中断后重新执行 --install-cert）")
        return False

    import subprocess
    print(f"正在安装根证书: {cert_path}")
    result = subprocess.run(
        ["certutil", "-user", "-addstore", "Root", str(cert_path)],
        capture_output=True, text=True,
    )
    if result.returncode == 0 or "already" in result.stdout.lower():
        print("[OK] 根证书已安装（或已存在）")
        return True
    else:
        print(f"[警告] certutil 返回非零: {result.returncode}")
        print(f"  stdout: {result.stdout}")
        print(f"  stderr: {result.stderr}")
        return False


# ── 主入口 ───────────────────────────────────────────────────────────────────

def run_capture(output: str = "cookies.json",
                timeout: int = 120,
                port: int = 8080) -> dict[str, str]:
    """启动 mitmproxy → 等待 Cookie 捕获 → 保存并返回。

    使用系统代理 + mitmproxy HTTP 代理拦截 QBCore 的 WeGame API 请求。
    无需管理员权限（仅首次需要 --install-cert 安装根证书）。
    WeGame 登录时即发送 Cookie，无需手动导航到对局记录页。

    Args:
        output: Cookie JSON 输出路径
        timeout: 最大等待秒数
        port: mitmproxy 监听端口

    Returns:
        提取到的 Cookie 字典（可能不完整）
    """
    global _proxy_was_enabled, _original_proxy

    # 修复 Windows GBK 终端编码问题 + exe noconsole 模式兼容
    # exe 无控制台时 sys.stdout 为 None，mitmproxy termlog addon 需要 .isatty()
    import io as _io
    import os as _os
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    elif sys.stdout is None:
        sys.stdout = open(_os.devnull, 'w')

    addon = WegameCookieCapture()

    # ── 1. 启动 mitmproxy 后台线程 ──
    opts = options.Options(
        listen_host="127.0.0.1",
        listen_port=port,
        ssl_insecure=True,
    )

    loop = asyncio.new_event_loop()
    master = DumpMaster(opts, loop=loop)
    master.addons.add(addon)

    async def _start():
        await master.run()

    def _run_loop():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_start())
        except Exception as e:
            logger.debug("mitmproxy 退出: %s", e)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    # 等待 mitmproxy 启动就绪
    for _ in range(30):
        time.sleep(0.1)
        s = std_socket.socket(std_socket.AF_INET, std_socket.SOCK_STREAM)
        s.settimeout(0.1)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            break
        except (ConnectionRefusedError, OSError):
            s.close()

    # ── 2. 设置系统代理 ──
    _original_proxy = _get_windows_proxy()
    _set_windows_proxy(f"127.0.0.1:{port}", enable=True)
    _proxy_was_enabled = True

    # ── 3. 提示用户登录 WeGame ──
    print("=" * 60)
    print("  LOLhistory Cookie 抓包工具")
    print("=" * 60)
    print()
    print(f"  [OK] 代理已开启 (127.0.0.1:{port})")
    print(f"  [OK] 正在监听 WeGame 请求...")
    print()
    print("  请登录 WeGame 即可自动完成抓包")
    print(f"  （超时={timeout}s，按 Ctrl+C 取消）")
    print()

    # ── 4. 等待捕获完成或超时 ──
    start_time = time.time()
    last_count = 0
    dots = 0
    while not addon.is_done():
        elapsed = time.time() - start_time
        if elapsed > timeout:
            print(f"\n超时 ({timeout}s)，保存已捕获的 {len(addon.cookies)} 项...")
            break

        if addon._request_count > last_count:
            last_count = addon._request_count
            print(f"\r  已检测到 {last_count} 个目标请求, "
                  f"已提取 {len(addon.cookies)}/4 项 cookie", end="")
        else:
            dots = (dots + 1) % 4
            print(f"\r  等待中{'.' * dots}   ", end="")

        time.sleep(0.5)

    print()

    # 5. 停止并清理
    _cleanup_proxy()
    try:
        master.shutdown()
    except Exception:
        pass
    try:
        loop.call_soon_threadsafe(loop.stop)
    except Exception:
        pass
    thread.join(timeout=3)
    try:
        loop.close()
    except Exception:
        pass

    # 6. 保存结果
    if addon.cookies:
        output_path = Path(output)
        output_path.write_text(
            json.dumps(addon.cookies, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"\n{'=' * 60}")
        print(f"  成功提取 {len(addon.cookies)}/4 项 Cookie → {output_path}")
        print(f"{'=' * 60}")
        for k in REQUIRED_KEYS:
            if k in addon.cookies:
                val = addon.cookies[k]
                preview = val[:50] + "..." if len(val) > 50 else val
                print(f"    [OK] {k} = {preview}")
            else:
                print(f"    [X] {k} — 缺失")
        print()
        print(f"  下一步: python -m lolhistory --cookies {output}")
    else:
        print(f"\n{'=' * 60}")
        print(f"  未捕获到 WeGame Cookie")
        print(f"{'=' * 60}")
        print()
        print("  请检查:")
        print("    1. 是否已登录 WeGame")
        print(f"    2. 系统代理是否为 127.0.0.1:{port}")
        print("    3. mitmproxy 根证书是否已安装（--install-cert）")
        print()
        print("  提示：首次使用需先运行 --install-cert 安装根证书")

    return addon.cookies
