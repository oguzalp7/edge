"""WSL command safety and --cd auto-anchoring guard (stdlib-only)."""

import re
from typing import Any, Dict, Optional

WSL_INVOCATION_PATTERN = re.compile(r"^\s*(?:wsl(?:\.exe)?)(?:\s+|$)", re.IGNORECASE)
DOUBLE_QUOTE_SEGMENT_PATTERN = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
UNESCAPED_PS_VAR_PATTERN = re.compile(r"(?<![`\\])\$([a-zA-Z_][a-zA-Z0-9_]*|\{[a-zA-Z_][a-zA-Z0-9_]*\})")
BASH_C_PATTERN = re.compile(r"\bbash\s+-(?:l)?c\b", re.IGNORECASE)
SHELL_METACHAR_PATTERN = re.compile(r"[();|&]")
WSL_CD_CMD_PATTERN = re.compile(r"""(?:^|[\s;&|'"])cd\s+([\"']?)(~?/[^\"'\s;&|]+)\1""", re.IGNORECASE)
WSL_MANAGEMENT_FLAGS = ("--list", "-l", "--status", "--shutdown", "--terminate", "-t", "--help", "-h", "--version", "-v")
WSL_PREFIX_PATTERN = re.compile(r"^(\s*wsl(?:\.exe)?(?:\s+(?:-d|--distribution|-u|--user)\s+[^\s]+)*)", re.IGNORECASE)


def _is_wsl_invocation(command_line: str) -> bool:
    return bool(command_line and isinstance(command_line, str) and WSL_INVOCATION_PATTERN.search(command_line))


def _check_powershell_var_swallowing(command_line: str) -> Optional[Dict[str, Any]]:
    for match in DOUBLE_QUOTE_SEGMENT_PATTERN.finditer(command_line):
        var_match = UNESCAPED_PS_VAR_PATTERN.search(match.group(1))
        if not var_match:
            continue
        var_name = var_match.group(0)
        return {
            "decision": "deny",
            "reason": (
                f"❌ [POWERSHELL VARIABLE SWALLOWING GUARD]: Unescaped PowerShell variable '{var_name}' "
                "detected inside double quotes in WSL command. PowerShell will evaluate and swallow this variable "
                "locally before WSL launches. Wrap the bash command in single quotes ('...') or escape the variable "
                f"using backtick (e.g. `{var_name}) or backslash."
            ),
        }
    return None


def _check_nested_quoting_collision(command_line: str) -> Optional[Dict[str, Any]]:
    if not BASH_C_PATTERN.search(command_line):
        return None
    has_nested = (
        ("'" in command_line and '"' in command_line)
        or (r'\"' in command_line or r"\'" in command_line)
        or command_line.count('"') > 2
        or command_line.count("'") > 2
    )
    if has_nested and bool(SHELL_METACHAR_PATTERN.search(command_line)):
        return {
            "decision": "deny",
            "reason": (
                "❌ [NESTED QUOTING & METACHARACTER COLLISION GUARD]: Nested quotes (' and \") combined with shell "
                "metacharacters ('(', ')', ';', '|', '&') detected in 'wsl bash -c'. Win32 argument wrapping will corrupt "
                "inner quotes and break bash command parsing. Avoid nested 'bash -c' wrappers; invoke the target executable "
                "directly using 'wsl --cd <linux_path> <executable> <args>', or write commands to a shell script file."
            ),
        }
    return None


def _normalize_cwd_to_linux(cwd: str) -> Optional[str]:
    norm = cwd.strip().replace("\\", "/")
    if not norm:
        return None
    unc_match = re.match(r"^//wsl(?:\.localhost|\$)/[^/]+(/.*)$", norm, re.IGNORECASE)
    if unc_match:
        return unc_match.group(1)
    if norm.startswith("/") or norm.startswith("~"):
        return norm
    if re.match(r"^[a-zA-Z]:/home/", norm, re.IGNORECASE):
        return norm[2:]
    drive_match = re.match(r"^([a-zA-Z]):/(.*)$", norm)
    return f"/mnt/{drive_match.group(1).lower()}/{drive_match.group(2)}" if drive_match else None


def _resolve_wsl_anchor_path(command_line: str, cwd: str = "") -> Optional[str]:
    cd_match = WSL_CD_CMD_PATTERN.search(command_line)
    if cd_match:
        return cd_match.group(2)
    return _normalize_cwd_to_linux(cwd) if cwd else None


def _transform_wsl_command_anchor(command_line: str, linux_path: str) -> str:
    strip_pattern = re.compile(r"(cd\s+[\"']?" + re.escape(linux_path) + r"[\"']?\s*(?:&&|;)\s*)", re.IGNORECASE)
    cleaned_cmd = strip_pattern.sub("", command_line)
    prefix_match = WSL_PREFIX_PATTERN.match(cleaned_cmd)
    if not prefix_match:
        return f"wsl --cd {linux_path} {cleaned_cmd.strip()}"
    wsl_head = prefix_match.group(1).rstrip()
    wsl_tail = cleaned_cmd[prefix_match.end():].lstrip()
    return f"{wsl_head} --cd {linux_path} {wsl_tail}" if wsl_tail else f"{wsl_head} --cd {linux_path}"


def evaluate_wsl_command_guard(command_line: str, cwd: str = "") -> Optional[Dict[str, Any]]:
    """Evaluate and auto-anchor WSL commands with --cd <linux_path>."""
    if not _is_wsl_invocation(command_line):
        return None
    deny = _check_powershell_var_swallowing(command_line) or _check_nested_quoting_collision(command_line)
    if deny:
        return deny
    tokens = command_line.split()
    if any(tok.lower() in WSL_MANAGEMENT_FLAGS for tok in tokens) or "--cd" in tokens:
        return None
    linux_path = _resolve_wsl_anchor_path(command_line, cwd=cwd)
    return {"decision": "allow", "overwrite": {"CommandLine": _transform_wsl_command_anchor(command_line, linux_path)}} if linux_path else None


def _handle_run_command_wsl_guard(tool_name: str, args: dict) -> Optional[dict]:
    cmd_key = "CommandLine" if "CommandLine" in args else ("command" if "command" in args else None)
    if not ((tool_name == "run_command" or cmd_key is not None) and cmd_key):
        return None
    cwd = args.get("cwd", "") or args.get("working_directory", "")
    res = evaluate_wsl_command_guard(args.get(cmd_key, ""), cwd=cwd)
    if res is not None and res.get("decision") == "allow" and "overwrite" in res:
        new_cmd = res["overwrite"].get("CommandLine") or res["overwrite"].get("command")
        res["overwrite"] = {cmd_key: new_cmd}
    return res
