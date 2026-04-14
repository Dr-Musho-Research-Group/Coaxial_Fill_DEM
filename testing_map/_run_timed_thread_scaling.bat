@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%timed_thread_scaling.py"

if not exist "%SCRIPT%" (
    echo Error: timed scaling script not found: "%SCRIPT%"
    exit /b 1
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

if exist "C:\Program Files\Inkscape\bin\python.exe" (
    "C:\Program Files\Inkscape\bin\python.exe" "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

echo Error: no usable Python interpreter was found.
echo Tried: python, py, and C:\Program Files\Inkscape\bin\python.exe
exit /b 1
