@echo off
REM Build Agent Hub as a standalone Windows .exe
REM Requires: Python 3.11+ with project dependencies installed
REM Usage: build_exe.bat

echo Building Agent Hub .exe...
pip install pyinstaller
pyinstaller agent_hub.spec

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Build successful!
    echo Output: dist\agent-hub.exe
    echo.
    for %%A in (dist\agent-hub.exe) do (
        for %%B in (%%~zA) do (
            set /a size=%%B/1024/1024
            echo File size: %%B bytes (~!size! MB)
        )
    )
) else (
    echo.
    echo Build failed with error code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)
