@echo off
chcp 65001 > nul
:: ============================================================
:: SmartSuite 离线安装脚本（Windows）
:: 用法:
::   联网下载:  setup_offline.bat download
::   离线安装:  setup_offline.bat install
:: ============================================================
setlocal enabledelayedexpansion
set "PACKAGES_DIR=%~dp0packages"

if /I "%~1"=="download" (
    echo [1/2] 创建 packages 目录...
    if not exist "%PACKAGES_DIR%" mkdir "%PACKAGES_DIR%"

    echo [2/2] 下载全部依赖到 packages/ ...
    echo         含核心依赖 + web + report + dev
    pip download .[web,report,dev] -d "%PACKAGES_DIR%"

    echo.
    echo ========================================
    echo  下载完成！文件列表:
    echo ========================================
    dir /b "%PACKAGES_DIR%\*.whl" 2>nul
    dir /b "%PACKAGES_DIR%\*.tar.gz" 2>nul
    echo.
    echo 请将 packages/ 文件夹复制到离线机器的项目根目录,
    echo 然后在离线机器上运行: setup_offline.bat install
    goto :eof
)

if /I "%~1"=="install" (
    if not exist "%PACKAGES_DIR%" (
        echo [错误] packages/ 文件夹不存在，请先在有网机器上运行:
        echo        setup_offline.bat download
        exit /b 1
    )

    echo [1/2] 从本地 packages/ 安装全部依赖...
    pip install --no-index --find-links="%PACKAGES_DIR%" smartsuite[web,report,dev]

    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查 packages/ 中的文件是否完整
        exit /b 1
    )

    echo [2/2] 安装 smartsuite 本身（开发模式）...
    pip install --no-deps -e "%~dp0."

    echo.
    echo ========================================
    echo  安装完成！
    echo ========================================
    echo  验证: python -c "import smartsuite; print('OK')"
    goto :eof
)

:: 默认：显示帮助
echo SmartSuite 离线安装脚本
echo ========================================
echo 用法:
echo   setup_offline.bat download   - 在有网机器上下载所有依赖到 packages/
echo   setup_offline.bat install     - 从本地 packages/ 离线安装
echo ========================================
endlocal
