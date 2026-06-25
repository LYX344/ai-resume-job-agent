@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI 简历求职助手一键启动

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" launch.py %*
) else (
    python launch.py %*
)

echo.
echo 服务已退出，按任意键关闭窗口。
pause >nul
