@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 打包 AI 简历求职助手启动器 exe

echo 正在准备打包环境（PyInstaller）……
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 (
    echo PyInstaller 安装失败，请检查网络后重试。
    pause
    exit /b 1
)

echo 正在打包 launch.py 为单文件 exe……
".venv\Scripts\python.exe" -m PyInstaller --onefile --console ^
    --name ai-resume-job-agent-launcher ^
    --distpath launcher_dist ^
    --workpath launcher_build ^
    --specpath launcher_build ^
    launch.py

if errorlevel 1 (
    echo 打包失败，请查看上方日志。
    pause
    exit /b 1
)

echo.
echo 打包完成：launcher_dist\ai-resume-job-agent-launcher.exe
echo 请把该 exe 复制到项目根目录（与 app\、frontend\、.venv\ 同级）后运行。
pause
