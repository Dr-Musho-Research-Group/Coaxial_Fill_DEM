@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "BENCH_SCRIPT=%SCRIPT_DIR%benchmark_threads.py"

if not exist "%BENCH_SCRIPT%" (
    echo Error: benchmark script not found: "%BENCH_SCRIPT%"
    exit /b 1
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python "%BENCH_SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py "%BENCH_SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

if exist "C:\Program Files\Inkscape\bin\python.exe" (
    "C:\Program Files\Inkscape\bin\python.exe" "%BENCH_SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

echo Error: no usable Python interpreter was found.
echo Tried: python, py, and C:\Program Files\Inkscape\bin\python.exe
exit /b 1
