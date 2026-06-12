"""LOLhistory GUI - PyInstaller packaging script (Python version).

Replaces build_exe.bat, avoiding bat encoding/escaping issues.
Usage: .venv\\Scripts\\python build_exe.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def run(cmd: list[str], description: str) -> bool:
    """Run a command, print error and return False on failure."""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"{'='*60}")
    print(f"  -> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"\n  [FAIL] {description}")
        return False
    print(f"  [OK] {description}")
    return True


def find_upx() -> str | None:
    """Locate UPX executable for binary compression (30-50% reduction)."""
    candidates = [
        ROOT / ".venv" / "Scripts" / "upx.exe",
        Path(os.environ.get("USERPROFILE", "")) / "scoop" / "shims" / "upx.exe",
        Path(os.environ.get("ProgramFiles", "")) / "upx" / "upx.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "upx" / "upx.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    which = shutil.which("upx")
    if which:
        return which
    return None


def main() -> int:
    # Force UTF-8 output to avoid GBK encode errors on Windows
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("  LOLhistory GUI - PyInstaller Packager")
    print("=" * 60)
    print(f"  Python: {PYTHON}")
    print(f"  Entry:  {ROOT / 'gui_app.py'}")

    # ── Step 1: check / install PyInstaller ──
    check = subprocess.run(
        [str(PYTHON), "-c", "import PyInstaller"],
        capture_output=True,
    )
    if check.returncode == 0:
        print("  [OK] PyInstaller already installed")
    else:
        print("  [1/4] Installing PyInstaller...")
        if not run(
            [str(PYTHON), "-m", "pip", "install", "pyinstaller"],
            "Install PyInstaller",
        ):
            return 1

    # ── Step 2: locate conda DLLs (PyInstaller can't resolve these from Miniconda) ──
    tcl_root = subprocess.run(
        [str(PYTHON), "-c",
         "from tkinter import Tcl; r=Tcl(); print(r.eval('info library'))"],
        capture_output=True, text=True, cwd=str(ROOT),
    ).stdout.strip()
    tcl_root = Path(tcl_root)
    tk_root = tcl_root.parent / f"tk{tcl_root.name[3:]}"
    conda_bin = tcl_root.parent.parent / "bin"

    tcl_dll = conda_bin / "tcl86t.dll"
    tk_dll = conda_bin / "tk86t.dll"

    conda_dlls = [
        tcl_dll,
        tk_dll,
        conda_bin / "sqlite3.dll",
        conda_bin / "libexpat.dll",
        conda_bin / "ffi.dll",
        conda_bin / "liblzma.dll",
        conda_bin / "libbz2.dll",
        conda_bin / "libmpdec-4.dll",
    ]

    for dll in conda_dlls:
        status = "OK" if dll.exists() else "MISSING"
        print(f"  [{status}] {dll.name}")

    tcl_data = tk_data = None
    if tcl_root.exists():
        tcl_data = (tcl_root, "tcl8.6")
    if tk_root.exists():
        tk_data = (tk_root, "tk8.6")

    # ── Step 3: locate UPX (optional but ~30-50% binary compression) ──
    upx_exe = find_upx()
    if upx_exe:
        print(f"  [OK] UPX found: {upx_exe}")
    else:
        print("  [WARN] UPX not found — skipping binary compression")
        print("         Install: winget install upx/upx")

    # ── Step 4: clean old output ──
    old_exe = ROOT / "dist" / "LOLhistory.exe"
    out_name = "LOLhistory"
    if old_exe.exists():
        try:
            old_exe.unlink()
            print(f"  [OK] Removed old {old_exe.name}")
        except PermissionError:
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_name = f"LOLhistory-{ts}"
            print(f"  [WARN] Old exe locked (AV?), outputting as {out_name}.exe")

    # ── Step 5: package ──
    print("\n  [5/5] Packaging...")

    hidden_imports = [
        "lolhistory._wegame",
        "lolhistory._analysis",
        "lolhistory._export",
        "lolhistory._data",
        "lolhistory._cookie_extract",
        "lolhistory._capture_cookies",
        "lolhistory",
        # mitmproxy 官方 PyInstaller hook 推荐
        "mitmproxy.script",
    ]

    cmd = [
        str(PYTHON), "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--name", out_name,
        "--icon", str(ROOT / "archive" / "exe-icon.ico"),
        # ── mitmproxy: 只收集 data + binaries，不收集全部子模块 ──
        #   原因：addons/__init__.py 已显式导入所有 addon，PyInstaller 可自动追踪。
        #   全部 --collect-submodules 会把 Console UI (urwid)、Web UI 等打包进去。
        "--collect-data", "mitmproxy",
        "--collect-binaries", "mitmproxy",
        # ── mitmproxy_rs: 只需 .pyd 文件，无需子模块 ──
        "--collect-binaries", "mitmproxy_rs",
        # ── 排除明确不用的模块（减小 exe 体积）──
        "--exclude-module", "mitmproxy.tools.console",
        "--exclude-module", "mitmproxy.tools.web",
        "--exclude-module", "urwid",
    ]
    # UPX binary compression
    if upx_exe is not None:
        cmd += ["--upx-dir", str(Path(upx_exe).parent)]
    # Bundle conda DLLs
    for dll in conda_dlls:
        if dll.exists():
            cmd += ["--add-binary", f"{dll}{os.pathsep}."]
    # Bundle Tcl/Tk script libraries
    if tcl_data is not None:
        cmd += ["--add-data", f"{tcl_data[0]}{os.pathsep}{tcl_data[1]}"]
    if tk_data is not None:
        cmd += ["--add-data", f"{tk_data[0]}{os.pathsep}{tk_data[1]}"]
    for mod in hidden_imports:
        cmd += ["--hidden-import", mod]
    cmd.append("gui_app.py")

    if not run(cmd, "PyInstaller build"):
        return 1

    # ── Done ──
    exe = ROOT / "dist" / f"{out_name}.exe"
    print(f"\n  Done!")
    print(f"\n  Output: {exe}")
    if exe.exists():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"  Size:   {size_mb:.1f} MB")
    else:
        print("  [WARN] exe not found")
    print(f"\n  Tip: Copy dist\\{out_name}.exe anywhere to use it.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
