: << 'CMDBLOCK'
@echo off
setlocal
set "EDGE_MODE=%~1"
if "%EDGE_MODE%"=="" set "EDGE_MODE=pre_tool"

if /i "%EDGE_HOOKS%"=="off" (
    if "%EDGE_MODE%"=="post_tool" echo {}
    if "%EDGE_MODE%"=="pre_invocation" echo {"injectSteps":[]}
    if not "%EDGE_MODE%"=="post_tool" if not "%EDGE_MODE%"=="pre_invocation" echo {"decision":"allow"}
    exit /b 0
)

set "EDGE_ROOT=%PLUGIN_ROOT%"
if "%EDGE_ROOT%"=="" set "EDGE_ROOT=%~dp0.."
set "EDGE_DISPATCH=%EDGE_ROOT%\hooks\dispatch.py"
if not exist "%EDGE_DISPATCH%" (
    if "%EDGE_MODE%"=="post_tool" echo {}
    if "%EDGE_MODE%"=="pre_invocation" echo {"injectSteps":[]}
    if not "%EDGE_MODE%"=="post_tool" if not "%EDGE_MODE%"=="pre_invocation" echo {"decision":"allow"}
    exit /b 0
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
    "%EDGE_PY%" %EDGE_PY_ARG% "%EDGE_DISPATCH%" "%EDGE_MODE%"
    if not errorlevel 1 exit /b 0
)

if not defined EDGE_PY where uv <nul >nul 2>nul && uv run --no-project --offline python "%EDGE_DISPATCH%" "%EDGE_MODE%"
if not errorlevel 1 if not defined EDGE_PY exit /b 0

if "%EDGE_MODE%"=="post_tool" echo {}
if "%EDGE_MODE%"=="pre_invocation" echo {"injectSteps":[]}
if not "%EDGE_MODE%"=="post_tool" if not "%EDGE_MODE%"=="pre_invocation" echo {"decision":"allow"}
exit /b 0
CMDBLOCK

_fail_open() {
    case "${1:-pre_tool}" in
        post_tool) printf '%s\n' '{}' ;;
        pre_invocation) printf '%s\n' '{"injectSteps":[]}' ;;
        *) printf '%s\n' '{"decision":"allow"}' ;;
    esac
}

EDGE_MODE="${1:-pre_tool}"
if [ "${EDGE_HOOKS:-}" = "off" ] || [ "${EDGE_HOOKS:-}" = "OFF" ]; then
    _fail_open "$EDGE_MODE"
    exit 0
fi

if [ -n "${PLUGIN_ROOT:-}" ]; then
    EDGE_ROOT="$PLUGIN_ROOT"
else
    case "$0" in
        */*) _self_dir="${0%/*}" ;;
        *) _self_dir="." ;;
    esac
    EDGE_ROOT="$(CDPATH= cd -- "$_self_dir/.." && pwd)"
fi
EDGE_DISPATCH="$EDGE_ROOT/hooks/dispatch.py"
if [ ! -f "$EDGE_DISPATCH" ]; then
    _fail_open "$EDGE_MODE"
    exit 0
fi

_EDGE_HOME_DIR="${EDGE_HOME:-$HOME/.edge}"
_EDGE_PY=""
for _cache_file in "${PLUGIN_DATA:+$PLUGIN_DATA/python_exe.txt}" "$_EDGE_HOME_DIR/python_exe.txt"; do
    if [ -n "$_cache_file" ] && [ -f "$_cache_file" ]; then
        _cand="$(head -n 1 "$_cache_file" | tr -d '\r\n')"
        if [ -n "$_cand" ] && [ -x "$_cand" ] && "$_cand" -c "import sys" </dev/null >/dev/null 2>&1; then
            _EDGE_PY="$_cand"
            break
        fi
    fi
done

if [ -n "$_EDGE_PY" ]; then
    "$_EDGE_PY" "$EDGE_DISPATCH" "$EDGE_MODE" && exit 0
fi

for _cand in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python; do
    if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c "import sys" </dev/null >/dev/null 2>&1; then
        "$_cand" "$EDGE_DISPATCH" "$EDGE_MODE" && exit 0
    fi
done

for _uv_cand in uv /opt/homebrew/bin/uv /usr/local/bin/uv "$HOME/.local/bin/uv"; do
    if command -v "$_uv_cand" >/dev/null 2>&1; then
        "$_uv_cand" run --no-project --offline python "$EDGE_DISPATCH" "$EDGE_MODE" && exit 0
    fi
done

_fail_open "$EDGE_MODE"
exit 0
