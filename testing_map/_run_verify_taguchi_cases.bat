@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VERIFY_SCRIPT=%SCRIPT_DIR%verify_taguchi_cases.py"

if not exist "%VERIFY_SCRIPT%" (
    echo Error: verifier script not found: "%VERIFY_SCRIPT%"
    exit /b 1
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python "%VERIFY_SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py "%VERIFY_SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

if exist "C:\Program Files\Inkscape\bin\python.exe" (
    "C:\Program Files\Inkscape\bin\python.exe" "%VERIFY_SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

echo Error: no usable Python interpreter was found.
echo Tried: python, py, and C:\Program Files\Inkscape\bin\python.exe
exit /b 1
