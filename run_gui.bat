@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 使用 pythonw.exe 启动 GUI（无控制台窗口）
start "" .venv\Scripts\pythonw.exe gui_app.py
