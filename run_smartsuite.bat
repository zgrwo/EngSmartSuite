@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title SmartSuite — 工艺数据分析工具箱

:: ============================================================
::  SmartSuite 一键启动脚本 (Windows)
::  双击即可: 自动检测 → 安装 → 打开浏览器 → 上传Excel → 分析
:: ============================================================

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%\.venv-smartsuite"
set "PYTHON="

echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║     SmartSuite — 工艺数据分析工具箱         ║
echo   ║     一键启动脚本 v1.0                        ║
echo   ╚══════════════════════════════════════════════╝
echo.

:: ── 1. 查找 Python 3.10+ ──
echo   [1/4] 检测 Python 环境...
for %%p in (python python3) do (
    where %%p >nul 2>&1
    if !errorlevel!==0 (
        for /f "tokens=2" %%v in ('%%p --version 2^>^&1') do (
            for /f "tokens=1,2 delims=." %%a in ("%%v") do (
                set /a MAJOR=%%a 2>nul
                set /a MINOR=%%b 2>nul
                if !MAJOR! geq 3 if !MINOR! geq 10 set "PYTHON=%%p"
                if !MAJOR! geq 4 set "PYTHON=%%p"
            )
        )
    )
)

if "%PYTHON%"=="" (
    echo   [✗] 未找到 Python 3.10+，请先安装 Python
    echo       下载地址: https://www.python.org/downloads/
    echo       安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('%PYTHON% --version 2^>^&1') do set "PYVER=%%v"
echo   [✓] 找到 Python %PYVER%

:: ── 2. 创建虚拟环境 (首次) ──
echo   [2/4] 准备虚拟环境...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo         首次运行，正在创建虚拟环境...
    %PYTHON% -m venv "%VENV_DIR%" --clear
    if !errorlevel! neq 0 (
        echo   [✗] 虚拟环境创建失败，请检查磁盘空间和权限
        pause
        exit /b 1
    )
    set "NEED_INSTALL=1"
) else (
    echo   [✓] 虚拟环境已就绪
)

:: ── 3. 安装/更新依赖 ──
echo   [3/4] 检查依赖...
set "SMARTSUITE_OK=0"
"%VENV_DIR%\Scripts\python" -c "import smartsuite; print(smartsuite.__version__)" >nul 2>&1
if !errorlevel!==0 (set "SMARTSUITE_OK=1")

if "%SMARTSUITE_OK%"=="0" (
    echo         正在安装 SmartSuite 及依赖 (约需 2-5 分钟)...
    "%VENV_DIR%\Scripts\python" -m pip install "%PROJECT_DIR%[web]" --quiet
    if !errorlevel! neq 0 (
        echo   [✗] 安装失败，请检查网络连接后重试
        echo       或手动运行: pip install .[web]
        pause
        exit /b 1
    )
    echo   [✓] 安装完成
) else (
    echo   [✓] SmartSuite 已安装
)

:: ── 4. 启动 Web UI ──
echo   [4/4] 启动 Web 界面...
echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║  浏览器将自动打开 http://127.0.0.1:5050      ║
echo   ║  上传 Excel → 选列 → 点按钮 → 看结果         ║
echo   ║  按 Ctrl+C 或关闭此窗口停止服务               ║
echo   ╚══════════════════════════════════════════════╝
echo.

:: 启动 Flask 应用（会自动打开浏览器）
"%VENV_DIR%\Scripts\python" "%PROJECT_DIR%\run_server.py"

echo.
echo   SmartSuite 已停止。
pause
