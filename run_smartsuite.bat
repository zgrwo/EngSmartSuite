@echo off
chcp 65001 > nul

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

echo   +==============================================+

echo   ^|     SmartSuite — 工艺数据分析工具箱         ^|

echo   ^|     一键启动脚本 v1.0                        ^|

echo   +==============================================+

echo.



:: ── 1. 查找 Python 3.10+ (三级降级策略) ──

echo   [1/4] 检测 Python 环境...



:: ── 策略 1: py launcher (Windows Python Launcher, 覆盖面最广) ──

:: py.exe 随官方 Python 安装器写入 C:\Windows\py.exe ，

:: 可发现本机所有已安装的 Python 版本（含未加入 PATH 的）。

py --version >nul 2>&1

if !errorlevel!==0 (

    for /f "tokens=2" %%v in ('py --version 2^>^&1') do set "PYVER=%%v"

    for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (

        set /a _MJ=%%a 2>nul

        set /a _MN=%%b 2>nul

        if !_MJ! gtr 3 set "PYTHON=py" & goto :python_found

        if !_MJ! equ 3 if !_MN! geq 10 set "PYTHON=py" & goto :python_found

    )

    :: py 启动器可用但默认版本 < 3.10，尝试指定更高版本

    for %%v in (3.13 3.12 3.11 3.10) do (

        py -%%v --version >nul 2>&1

        if !errorlevel!==0 (

            for /f "tokens=2" %%x in ('py -%%v --version 2^>^&1') do set "PYVER=%%x"

            set "PYTHON=py -%%v"

            goto :python_found

        )

    )

)



:: ── 策略 2: where 命令 (PATH 中的 python / python3) ──

for %%p in (python3 python) do (

    where %%p >nul 2>nul

    if !errorlevel!==0 (

        for /f "tokens=2" %%v in ('%%p --version 2^>^&1') do (

            for /f "tokens=1,2 delims=." %%a in ("%%v") do (

                set /a _MJ=%%a 2>nul

                set /a _MN=%%b 2>nul

                if !_MJ! gtr 3 set "PYTHON=%%p" & set "PYVER=%%v" & goto :python_found

                if !_MJ! equ 3 if !_MN! geq 10 set "PYTHON=%%p" & set "PYVER=%%v" & goto :python_found

            )

        )

    )

)



:: ── 策略 3: 扫描常见安装路径 (未加入 PATH 的用户/系统安装) ──

:: %LOCALAPPDATA%  ← 官方安装器默认路径 (仅当前用户)

:: %ProgramFiles%   ← 系统级安装的备选位置

for %%d in (

    "%LOCALAPPDATA%\Programs\Python\Python313"

    "%LOCALAPPDATA%\Programs\Python\Python312"

    "%LOCALAPPDATA%\Programs\Python\Python311"

    "%LOCALAPPDATA%\Programs\Python\Python310"

    "%ProgramFiles%\Python313"

    "%ProgramFiles%\Python312"

    "%ProgramFiles%\Python311"

    "%ProgramFiles%\Python310"

) do (

    if exist "%%~d\python.exe" (

        for /f "tokens=2" %%v in ('"%%~d\python.exe" --version 2^>^&1') do (

            for /f "tokens=1,2 delims=." %%a in ("%%v") do (

                set /a _MJ=%%a 2>nul

                set /a _MN=%%b 2>nul

                if !_MJ! gtr 3 set "PYTHON=%%~d\python.exe" & set "PYVER=%%v" & goto :python_found

                if !_MJ! equ 3 if !_MN! geq 10 set "PYTHON=%%~d\python.exe" & set "PYVER=%%v" & goto :python_found

            )

        )

    )

)



:python_found

if "%PYTHON%"=="" (

    echo   [X] 未找到 Python 3.10+

    echo.

    echo      请从 https://www.python.org/downloads/ 下载安装 Python 3.10+

    echo      安装时请勾选 "Add Python to PATH" 选项

    echo.

    echo      如已安装但未被检测到, 请将 Python 加入系统 PATH 后重试

    pause

    exit /b 1

)

echo   [OK] 找到 Python %PYVER%  (%PYTHON%)



:: ── 2. 创建虚拟环境 (首次) ──

echo   [2/4] 准备虚拟环境...

if not exist "%VENV_DIR%\Scripts\python.exe" (

    echo        首次运行，正在创建虚拟环境...

    %PYTHON% -m venv "%VENV_DIR%" --clear

    if !errorlevel! neq 0 (

        echo   [X] 虚拟环境创建失败，请检查磁盘空间和权限

        pause

        exit /b 1

    )

    set "NEED_INSTALL=1"

) else (

    echo   [OK] 虚拟环境已就绪

)



:: ── 3. 安装/更新依赖 ──

echo   [3/4] 检查依赖...

set "SMARTSUITE_OK=0"

"%VENV_DIR%\Scripts\python" -c "import smartsuite; print(smartsuite.__version__)" >nul 2>&1

if !errorlevel!==0 (set "SMARTSUITE_OK=1")



if "%SMARTSUITE_OK%"=="0" (

    echo        正在安装 SmartSuite 及全部依赖 (约需 2-5 分钟)...

    "%VENV_DIR%\Scripts\python" -m pip install "%PROJECT_DIR%[all]" --quiet

    if !errorlevel! neq 0 (

        echo   [X] 安装失败，请检查网络连接后重试

        echo      或手动运行: pip install .[web]

        pause

        exit /b 1

    )

    echo   [OK] 安装完成

) else (

    echo   [OK] SmartSuite 已安装

)



:: ── 4. 启动 Web UI ──

echo   [4/4] 启动 Web 界面...

echo.

echo   +==============================================+

echo   ^|  浏览器将自动打开 http://127.0.0.1:5050      ^|

echo   ^|  上传 Excel → 选列 → 点按钮 → 看结果         ^|

echo   ^|  按 Ctrl+C 或关闭此窗口停止服务               ^|

echo   +==============================================+

echo.



:: 启动 Flask 应用（会自动打开浏览器）

"%VENV_DIR%\Scripts\python" "%PROJECT_DIR%\run_server.py"



echo.

echo   SmartSuite 已停止。

pause

