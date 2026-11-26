@echo off
setlocal

set "EDGE_ROOT=%PLUGIN_ROOT%"
if "%EDGE_ROOT%"=="" set "EDGE_ROOT=%~dp0.."
if defined PYTHONPATH (
    set "PYTHONPATH=%EDGE_ROOT%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%EDGE_ROOT%"
)

set "EDGE_PY="
set "EDGE_PY_ARG="
if defined PLUGIN_DATA if exist "%PLUGIN_DATA%\python_exe.txt" set /p EDGE_PY=<"%PLUGIN_DATA%\python_exe.txt"
if defined EDGE_PY if not exist "%EDGE_PY%" set "EDGE_PY="
if not defined EDGE_PY if exist "%USERPROFILE%\.edge\python_exe.txt" set /p EDGE_PY=<"%USERPROFILE%\.edge\python_exe.txt"
if defined EDGE_PY if not exist "%EDGE_PY%" set "EDGE_PY="

if not defined EDGE_PY for /d %%D in ("%APPDATA%\uv\python\cpython-3.1*") do if not defined EDGE_PY if exist "%%D\python.exe" set "EDGE_PY=%%D\python.exe"

if not defined EDGE_PY python3 -c "import sys" <nul >nul 2>nul && set "EDGE_PY=python3"
if not defined EDGE_PY python -c "import sys" <nul >nul 2>nul && set "EDGE_PY=python"
if not defined EDGE_PY py -3 -c "import sys" <nul >nul 2>nul && (set "EDGE_PY=py" & set "EDGE_PY_ARG=-3")

if defined EDGE_PY (
    "%EDGE_PY%" %EDGE_PY_ARG% -m tools.doctor.cli %*
    exit /b %ERRORLEVEL%
)

where uv <nul >nul 2>nul && (
    uv run --no-project --offline python -m tools.doctor.cli %*
    exit /b %ERRORLEVEL%
)

echo Error: Python 3.10+ or uv not found. 1>&2
exit /b 1
