@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%tune_case1.py"

if not exist "%SCRIPT%" (
    echo Error: tuning script not found: "%SCRIPT%"
    exit /b 1
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python "%SCRIPT%" --base-dir "%SCRIPT_DIR%" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py "%SCRIPT%" --base-dir "%SCRIPT_DIR%" %*
    exit /b %ERRORLEVEL%
)

if exist "C:\Program Files\Inkscape\bin\python.exe" (
    "C:\Program Files\Inkscape\bin\python.exe" "%SCRIPT%" --base-dir "%SCRIPT_DIR%" %*
    exit /b %ERRORLEVEL%
)

echo Error: no usable Python interpreter was found.
echo Tried: python, py, and C:\Program Files\Inkscape\bin\python.exe
exit /b 1
