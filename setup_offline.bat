@echo off
chcp 65001 > nul
:: ============================================================
:: SmartSuite 离线安装脚本（Windows）
::
:: 双击运行，按数字键选择操作，无需输入命令。
::
:: 典型工作流:
::   有网机器 → 选 [2] 下载 → 复制项目到 U 盘
::   无网机器 → 选 [I] 安装 → 完成
:: ============================================================
setlocal enabledelayedexpansion
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:\=/%"
set "PACKAGES_DIR=%PROJECT_DIR%packages"

:: ── 检测当前 Python ──
set "LOCAL_PY_VER="
python -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor:02d}')" >nul 2>&1
if not errorlevel 1 (
    for /f %%v in ('python -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor:02d}')" 2^>nul') do set "LOCAL_PY_VER=%%v"
)

:: ── 命令行参数兼容 ──
if not "%~1"=="" goto :direct


:: =============================================================
::  主菜单
:: =============================================================
:menu
cls
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║         SmartSuite 离线安装工具                  ║
echo  ╠══════════════════════════════════════════════════╣
echo  ║                                                  ║
echo  ║  ★ 下载依赖（在有网机器上操作）                  ║
echo  ║  ──────────────────────────────────              ║
echo  ║  [1] 当前平台 ^(Win, Python 3.10+^)                ║
echo  ║  [2] Windows x64 + Python 3.12                  ║
echo  ║  [3] Windows x64 + Python 3.11                  ║
echo  ║  [4] Windows x64 + Python 3.10                  ║
echo  ║  [5] Windows x64 + 自定义 Python 版本           ║
echo  ║                                                  ║
echo  ║  ★ 离线安装（在无网目标机器上操作）              ║
echo  ║  ──────────────────────────────────              ║
echo  ║  [I] 一键安装 ^(推荐^)                            ║
echo  ║  [R] requirements.txt 方式安装                   ║
echo  ║  [D] 删除 packages/ 重新下载                     ║
echo  ║  ──────────────────────────────────              ║
echo  ║  [Q] 退出                                        ║
echo  ║                                                  ║
echo  ╚══════════════════════════════════════════════════╝
if defined LOCAL_PY_VER (
    set "PY_DISPLAY=!LOCAL_PY_VER:~0,1!.!LOCAL_PY_VER:~1,2!"
    echo  当前机器: Python !PY_DISPLAY!  已下载:
) else (
    echo  当前机器: Python 未检测到       已下载:
)
:: 显示已有 packages 状态
if exist "%PACKAGES_DIR%" (
    for /f %%c in ('dir /b "%PACKAGES_DIR%\*.whl" 2^>nul ^| find /c /v ""') do set "PKG_COUNT=%%c"
    echo  packages/ 含 !PKG_COUNT! 个 wheel 文件
) else (
    echo  packages/ 不存在 ^(需先下载^)
)
echo.
choice /c 12345IRDQ /n /m "请按键选择: "
if errorlevel 9 goto :eof
if errorlevel 8 goto :clean_packages
if errorlevel 7 goto :install_reqs
if errorlevel 6 goto :install
if errorlevel 5 goto :download_custom
if errorlevel 4 set "TARGET_PY=310" & goto :download_target
if errorlevel 3 set "TARGET_PY=311" & goto :download_target
if errorlevel 2 set "TARGET_PY=312" & goto :download_target
if errorlevel 1 goto :download_current


:: =============================================================
::  下载 — 当前平台
:: =============================================================
:download_current
cls
echo.
echo  ══════════════════════════════════════════════
echo   下载依赖 — 当前平台
echo  ══════════════════════════════════════════════
echo.
if defined LOCAL_PY_VER (
    set "PY_DISPLAY=!LOCAL_PY_VER:~0,1!.!LOCAL_PY_VER:~1,2!"
    echo  当前 Python: !PY_DISPLAY!
) else (
    echo  [警告] 未检测到 Python，下载可能失败
)
echo.
echo  将下载适配本机的 wheel 文件。生成的 packages/
echo  仅能在与本机相同 OS 和 Python 版本的机器上安装。
echo.
echo  ⚠ 如需给其他机器使用，请选择 [2]-[5] 指定目标平台。
echo.
choice /c YN /n /m "确认下载？[Y/N]: "
if errorlevel 2 goto :menu

set "PIP_PLATFORM_ARGS="
set "TARGET_LABEL=当前平台"
goto :do_download


:: =============================================================
::  下载 — 指定目标平台
:: =============================================================
:download_target
set "PY_MAJOR=!TARGET_PY:~0,1!"
set "PY_MINOR=!TARGET_PY:~1,2!"
:: 去除前导零（310 → "3.10" 中的 "10" 正确保留，因为取的是 ~1,2）
set "PY_DISPLAY=!PY_MAJOR!.!PY_MINOR!"
cls
echo.
echo  ══════════════════════════════════════════════
echo   下载依赖 — Windows x64 + Python !PY_DISPLAY!
echo  ══════════════════════════════════════════════
echo.
echo  目标平台: Windows x64
echo  目标 Python: !PY_DISPLAY! ^(cp!TARGET_PY!^)
echo  下载格式: 仅 wheel ^(目标机器无需编译器^)
echo.
echo  离线安装时，目标机器必须为:
echo    • Windows 64 位
echo    • Python !PY_DISPLAY! ^(版本必须精确匹配^)
echo.
choice /c YN /n /m "确认下载？[Y/N]: "
if errorlevel 2 goto :menu

set "PIP_PLATFORM_ARGS=--platform win_amd64 --python-version !TARGET_PY! --implementation cp --abi cp!TARGET_PY! --only-binary=:all:"
set "TARGET_LABEL=Windows x64 + Python !PY_DISPLAY!"
goto :do_download


:: =============================================================
::  下载 — 自定义 Python 版本
:: =============================================================
:download_custom
cls
echo.
echo  ══════════════════════════════════════════════
echo   下载依赖 — 自定义 Python 版本
echo  ══════════════════════════════════════════════
echo.
echo  请输入目标 Python 版本（3 位数字）:
echo.
echo    310 = Python 3.10    311 = Python 3.11
echo    312 = Python 3.12    313 = Python 3.13
echo.
set "TARGET_PY="
set /p "TARGET_PY=版本号: "
:: 验证
echo !TARGET_PY! | findstr /r "^3[01][0-9]$" >nul
if errorlevel 1 (
    echo.
    echo  [错误] 无效输入，请输入 3 位数字（如 312）
    timeout /t 2 >nul
    goto :download_custom
)
goto :download_target


:: =============================================================
::  清理旧 packages
:: =============================================================
:clean_packages
cls
if not exist "%PACKAGES_DIR%" (
    echo packages/ 不存在，无需清理
    timeout /t 2 >nul
    goto :menu
)
echo.
echo  ══════════════════════════════════════════════
echo   删除 packages/ 目录
echo  ══════════════════════════════════════════════
echo.
echo  将删除所有已下载的依赖文件。
echo.
choice /c YN /n /m "确认删除？[Y/N]: "
if errorlevel 2 goto :menu
rmdir /s /q "%PACKAGES_DIR%"
echo 已删除 packages/
timeout /t 2 >nul
goto :menu


:: =============================================================
::  执行下载
:: =============================================================
:do_download
cls
echo.
echo  ══════════════════════════════════════════════
echo   正在下载...
echo   目标: !TARGET_LABEL!
echo  ══════════════════════════════════════════════
echo.

:: 检查并警告已有 packages
if exist "%PACKAGES_DIR%" (
    for /f %%c in ('dir /b "%PACKAGES_DIR%\*.whl" 2^>nul ^| find /c /v ""') do set "EXISTING=%%c"
    if !EXISTING! gtr 0 (
        echo [警告] packages/ 已存在 !EXISTING! 个文件，将追加下载
        echo        如需全新下载，请先返回菜单选 [D] 清空
        echo.
    )
)

echo [1/4] 准备 packages 目录...
if not exist "%PACKAGES_DIR%" mkdir "%PACKAGES_DIR%"

echo [2/4] 下载构建依赖 ^(setuptools, wheel^)...
if defined PIP_PLATFORM_ARGS (
    pip download setuptools^>=68.0 wheel !PIP_PLATFORM_ARGS! -d "%PACKAGES_DIR%"
) else (
    pip download setuptools^>=68.0 wheel -d "%PACKAGES_DIR%"
)
if errorlevel 1 (
    echo.
    echo ══════════════════════════════════════════════
    echo  [错误] 构建依赖下载失败
    echo ══════════════════════════════════════════════
    echo  可能原因: 网络不通 / PyPI 不可达 / pip 版本过旧
    echo  请检查网络后重试
    pause
    goto :menu
)

echo [3/4] 下载全部运行时依赖 ^(核心 + Web + 报告 + 开发^)...
if defined PIP_PLATFORM_ARGS (
    pip download .[web,report,dev] !PIP_PLATFORM_ARGS! -d "%PACKAGES_DIR%"
) else (
    pip download .[web,report,dev] -d "%PACKAGES_DIR%"
)
if errorlevel 1 (
    echo.
    echo ══════════════════════════════════════════════
    echo  [错误] 运行时依赖下载失败
    echo ══════════════════════════════════════════════
    echo  可能原因: 部分包无对应平台的 wheel 文件
    echo  请尝试其他 Python 版本或检查网络
    pause
    goto :menu
)

echo [4/4] 生成 requirements.txt...
python scripts/gen_requirements.py "%PACKAGES_DIR%"
if errorlevel 1 (
    echo [警告] requirements.txt 生成失败，[R] 安装方式将不可用
)

echo.
echo ══════════════════════════════════════════════
echo  下载完成！
echo ══════════════════════════════════════════════
echo  目标: !TARGET_LABEL!
echo.
echo  下一步:
echo    1. 将整个项目文件夹复制到 U 盘/共享目录
echo    2. 在目标机器上运行 setup_offline.bat
echo    3. 选择 [I] 一键安装
echo.
echo  已下载文件:
dir /b "%PACKAGES_DIR%\*.whl" 2>nul
echo.
echo  ^(如需精确版本锁定，请重跑: python scripts\gen_requirements.py packages^)
echo ══════════════════════════════════════════════
pause
goto :menu


:: =============================================================
::  离线安装（一键安装，推荐）
:: =============================================================
:install
cls
if not exist "%PACKAGES_DIR%" (
    echo.
    echo ══════════════════════════════════════════════
    echo  [错误] packages/ 文件夹不存在
    echo ══════════════════════════════════════════════
    echo.
    echo  请先在有网机器上运行本脚本:
    echo    1. 选择 [2] 下载 ^(或对应目标平台^)
    echo    2. 将整个项目文件夹复制到本机
    echo    3. 重新运行本脚本并选择 [I] 安装
    echo.
    pause
    goto :menu
)

echo.
echo ══════════════════════════════════════════════
echo  离线安装 — 一键安装
echo ══════════════════════════════════════════════
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python
    echo        SmartSuite 需要 Python ^>=3.10
    echo        请先安装 Python 后再试
    pause
    goto :menu
)
echo Python 版本:
python --version
echo.

echo [1/3] 安装构建依赖 ^(setuptools, wheel^)...
pip install --no-index --find-links="%PACKAGES_DIR%" setuptools wheel
if errorlevel 1 (
    echo.
    echo ══════════════════════════════════════════════
    echo  [错误] 构建依赖安装失败
    echo ══════════════════════════════════════════════
    echo  packages/ 缺少 setuptools / wheel
    echo  请重新下载: 返回有网机器运行本脚本→选 [2]
    pause
    goto :menu
)

echo [2/3] 安装全部运行时依赖...
pip install --no-index --find-links="%PACKAGES_DIR%" --no-build-isolation smartsuite[web,report,dev]
if errorlevel 1 (
    echo.
    echo ══════════════════════════════════════════════
    echo  [错误] 运行时依赖安装失败
    echo ══════════════════════════════════════════════
    echo.
    echo  常见原因:
    echo    • Python 版本与下载时不匹配
    echo    • 当前 Python:
    python --version
    echo.
    echo  请确认 packages/ 中的 wheel 文件与当前 Python 版本兼容。
    echo  如版本不匹配，请回到有网机器重新下载对应版本。
    pause
    goto :menu
)

echo [3/3] 安装 smartsuite 本身...
pip install --no-deps --no-build-isolation -e "%PROJECT_DIR%."
if errorlevel 1 (
    echo.
    echo [错误] smartsuite 安装失败，请检查项目文件是否完整
    pause
    goto :menu
)

echo.
echo ══════════════════════════════════════════════
echo  安装完成！
echo ══════════════════════════════════════════════
echo.
echo  验证安装:
python -c "import smartsuite; print('  smartsuite 导入成功')" 2>nul
if errorlevel 1 (
    echo  [警告] 导入验证失败，请检查依赖是否完整
) else (
    echo  [OK] smartsuite 导入成功
)
echo.
echo  启动 Web UI:
echo    python smartsuite/web/app.py
echo.
echo ══════════════════════════════════════════════
pause
goto :menu


:: =============================================================
::  离线安装（requirements.txt 方式）
:: =============================================================
:install_reqs
cls
if not exist "%PACKAGES_DIR%/requirements.txt" (
    echo.
    echo ══════════════════════════════════════════════
    echo  [错误] packages/requirements.txt 不存在
    echo ══════════════════════════════════════════════
    echo.
    echo  请先在有网机器上运行本脚本选 [2] 下载。
    echo  需要 Python 环境以运行 gen_requirements.py。
    pause
    goto :menu
)

echo.
echo ══════════════════════════════════════════════
echo  离线安装 — requirements.txt 方式
echo ══════════════════════════════════════════════
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python
    pause
    goto :menu
)
python --version
echo.

echo [1/3] 安装构建依赖 ^(setuptools, wheel^)...
pip install --no-index --find-links="%PACKAGES_DIR%" setuptools wheel
if errorlevel 1 (
    echo [错误] 构建依赖安装失败
    pause
    goto :menu
)

echo [2/3] 从 requirements.txt 安装依赖...
pip install --no-index --find-links="%PACKAGES_DIR%" -r "%PACKAGES_DIR%/requirements.txt"
if errorlevel 1 (
    echo.
    echo ══════════════════════════════════════════════
    echo  [错误] 依赖安装失败
    echo ══════════════════════════════════════════════
    echo  可能原因: Python 版本与下载时不匹配
    python --version
    pause
    goto :menu
)

echo [3/3] 安装 smartsuite 本身...
pip install --no-deps --no-build-isolation -e "%PROJECT_DIR%."
if errorlevel 1 (
    echo [错误] smartsuite 安装失败
    pause
    goto :menu
)

echo.
echo ══════════════════════════════════════════════
echo  安装完成！
echo ══════════════════════════════════════════════
echo  验证: python -c "import smartsuite; print('OK')"
echo  启动: python smartsuite/web/app.py
pause
goto :menu


:: =============================================================
::  命令行直接调用（兼容旧用法，无菜单）
:: =============================================================
:direct
if /I "%~1"=="download" (
    if /I "%~2"=="--py" (
        set "TARGET_PY=%~3"
        set "PY_MAJOR=!TARGET_PY:~0,1!"
        set "PY_MINOR=!TARGET_PY:~1,2!"
        set "PY_DISPLAY=!PY_MAJOR!.!PY_MINOR!"
        set "PIP_PLATFORM_ARGS=--platform win_amd64 --python-version !TARGET_PY! --implementation cp --abi cp!TARGET_PY! --only-binary=:all:"
        set "TARGET_LABEL=Windows x64 + Python !PY_DISPLAY!"
        goto :do_download
    )
    set "TARGET_LABEL=当前平台"
    goto :do_download
)
if /I "%~1"=="install"     goto :install
if /I "%~1"=="install-reqs" goto :install_reqs
:: 无效参数 → 显示菜单
goto :menu
