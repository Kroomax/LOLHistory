@echo off
chcp 65001 >nul
echo ============================================================
echo   LOLhistory GUI — PyInstaller 打包脚本
echo ============================================================
echo.

:: 确保在项目根目录
cd /d "%~dp0"

:: 检查 PyInstaller
.venv\Scripts\python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [1/3] 安装 PyInstaller...
    .venv\Scripts\pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

echo [2/3] 开始打包...

:: 打包参数说明:
::   --onefile     → 单文件 .exe
::   --noconsole   → 不弹出控制台窗口
::   --name        → 输出文件名
::   --add-data    → 打包额外数据文件
::   --hidden-import → 显式包含隐式导入的模块
::   --collect-data → 收集包的数据文件（mitmproxy 需要）

.venv\Scripts\pyinstaller ^
    --onefile ^
    --noconsole ^
    --name lolhistory-gui ^
    --hidden-import lolhistory._wegame ^
    --hidden-import lolhistory._analysis ^
    --hidden-import lolhistory._export ^
    --hidden-import lolhistory._data ^
    --hidden-import lolhistory._cookie_extract ^
    --hidden-import lolhistory._capture_cookies ^
    --hidden-import lolhistory ^
    --hidden-import mitmproxy ^
    --hidden-import mitmproxy.options ^
    --hidden-import mitmproxy.http ^
    --hidden-import mitmproxy.tools.dump ^
    --collect-data mitmproxy ^
    gui_app.py

if errorlevel 1 (
    echo.
    echo [错误] PyInstaller 打包失败
    pause
    exit /b 1
)

echo.
echo [3/3] 打包完成！
echo.
echo 输出文件: dist\lolhistory-gui.exe
echo.
echo 提示：将 dist\lolhistory-gui.exe 复制到任意位置即可使用。
echo       首次使用前可能需要以管理员身份运行以安装根证书。
echo       后续使用无需管理员权限。
echo.
pause
