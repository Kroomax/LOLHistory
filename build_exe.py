"""LOLhistory GUI - PyInstaller packaging script (Python version).

Replaces build_exe.bat, avoiding bat encoding/escaping issues.
Usage: .venv\\Scripts\\python build_exe.py
"""

import os
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
        print("  [1/3] Installing PyInstaller...")
        # Use `python -m pip` so pip always matches the target python
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
    tcl_root = Path(tcl_root)  # e.g. D:/Software/Miniconda/Library/lib/tcl8.6
    tk_root = tcl_root.parent / f"tk{tcl_root.name[3:]}"  # tk8.6
    conda_bin = tcl_root.parent.parent / "bin"  # D:/Software/Miniconda/Library/bin

    tcl_dll = conda_bin / "tcl86t.dll"
    tk_dll = conda_bin / "tk86t.dll"

    # DLLs that PyInstaller warns about (all in conda_bin, all needed at runtime)
    conda_dlls = [
        tcl_dll,
        tk_dll,
        conda_bin / "sqlite3.dll",      # _sqlite3.pyd → database (core)
        conda_bin / "libexpat.dll",      # pyexpat.pyd → XML parsing
        conda_bin / "ffi.dll",           # _ctypes.pyd → FFI (mitmproxy needs)
        conda_bin / "liblzma.dll",       # _lzma.pyd → compression
        conda_bin / "libbz2.dll",        # _bz2.pyd → compression
        conda_bin / "libmpdec-4.dll",    # _decimal.pyd → decimal math
    ]

    for dll in conda_dlls:
        status = "OK" if dll.exists() else "MISSING"
        print(f"  [{status}] {dll.name}")

    # Tcl/Tk script libraries
    tcl_data = tk_data = None
    if tcl_root.exists():
        tcl_data = (tcl_root, "tcl8.6")
    if tk_root.exists():
        tk_data = (tk_root, "tk8.6")

    # ── Step 3: clean old output (may be locked by AV) ──
    old_exe = ROOT / "dist" / "lolhistory-gui.exe"
    out_name = "lolhistory-gui"
    if old_exe.exists():
        try:
            old_exe.unlink()
            print(f"  [OK] Removed old {old_exe.name}")
        except PermissionError:
            # File locked by AV — output to a temp name instead
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_name = f"lolhistory-gui-{ts}"
            print(f"  [WARN] Old exe locked (AV?), outputting as {out_name}.exe")

    # ── Step 4: package ──
    print("\n  [4/4] Packaging...")

    hidden_imports = [
        "lolhistory._wegame",
        "lolhistory._analysis",
        "lolhistory._export",
        "lolhistory._data",
        "lolhistory._cookie_extract",
        "lolhistory._capture_cookies",
        "lolhistory",
    ]

    cmd = [
        str(PYTHON),
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--name", out_name,
        # mitmproxy: collect all submodules + data + binaries (handles dynamic imports)
        "--collect-submodules", "mitmproxy",
        "--collect-data", "mitmproxy",
        "--collect-binaries", "mitmproxy",
        # mitmproxy_rs: Rust TLS extension (required by mitmproxy on Windows)
        "--collect-submodules", "mitmproxy_rs",
        "--collect-binaries", "mitmproxy_rs",
        # aioquic: QUIC support (mitmproxy uses this for HTTP/3)
        "--collect-submodules", "aioquic",
    ]
    # Bundle conda DLLs that PyInstaller can't resolve
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
    print(f"       First run may need admin rights to install the root cert.")
    print(f"       Subsequent runs do not require admin.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
