@echo off
setlocal

cd /d "%~dp0"

echo ===============================================================
echo Cleaning generated testing_map outputs...

del verification_* >nul 2>&1
del *.log >nul 2>&1

if exist "__pycache__" rmdir /s /q "__pycache__"
if exist "success_xyz" rmdir /s /q "success_xyz"
if exist "cases" rmdir /s /q "cases"

echo Done.
echo Kept source files and taguchi_map.csv intact.
echo ===============================================================
