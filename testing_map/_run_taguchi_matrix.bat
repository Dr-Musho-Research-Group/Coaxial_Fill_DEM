@echo off
setlocal EnableExtensions

rem Robust wrapper for run_taguchi_matrix.py
rem Put this file in the same folder as run_taguchi_matrix.py and taguchi_map.csv

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "PY_SCRIPT=%SCRIPT_DIR%\run_taguchi_matrix.py"
set "CSV_PATH=%SCRIPT_DIR%\taguchi_map.csv"
set "CASE_ROOT=%SCRIPT_DIR%\cases"
set "EXE_PATH=%SCRIPT_DIR%\..\src\coax_pack_cpu.exe"

if not exist "%PY_SCRIPT%" (
    echo ERROR: Python script not found:
    echo   %PY_SCRIPT%
    exit /b 1
)

if not exist "%CSV_PATH%" (
    echo ERROR: CSV file not found:
    echo   %CSV_PATH%
    exit /b 1
)

set "PY_CMD="
where python >nul 2>nul
if not errorlevel 1 set "PY_CMD=python"
if not defined PY_CMD (
    if exist "C:\Program Files\Inkscape\bin\python.exe" set "PY_CMD=C:\Program Files\Inkscape\bin\python.exe"
)
if not defined PY_CMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py"
)

if not defined PY_CMD (
    echo ERROR: Could not find a usable Python launcher.
    echo Tried: python, C:\Program Files\Inkscape\bin\python.exe, and py
    exit /b 1
)

echo Using Python launcher: %PY_CMD%
echo Script: %PY_SCRIPT%
echo CSV:    %CSV_PATH%
echo Cases:  %CASE_ROOT%
echo EXE:    %EXE_PATH%
echo.

pushd "%SCRIPT_DIR%"
%PY_CMD% "%PY_SCRIPT%" --csv "%CSV_PATH%" --base-dir . --case-root "%CASE_ROOT%" --exe "%EXE_PATH%" %*
set "ERR=%ERRORLEVEL%"
popd

if not "%ERR%"=="0" (
    echo.
    echo Taguchi case generation failed with exit code %ERR%.
    exit /b %ERR%
)

echo.
echo Taguchi case generation completed successfully.
exit /b 0
