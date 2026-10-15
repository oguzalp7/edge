import json
import subprocess
from pathlib import Path

payload_tool = {
    "toolCall": {"name": "replace_file_content", "args": {}},
    "transcriptPath": "C:\\Users\\oguz_\\.gemini\\antigravity\\brain\\5aa2a2a7-254a-4db3-b406-64afa103dd0c\\.system_generated\\logs\\transcript.jsonl"
}

res = subprocess.check_output(
    ["python3", "/mnt/c/Users/oguz_/.gemini/config/plugins/edge/tools/brigade/orchestrator_guard.py", "pre_tool"],
    input=json.dumps(payload_tool).encode("utf-8")
).decode("utf-8")
print("PreToolUse output:", res.strip())

res_inv = subprocess.check_output(
    ["python3", "/mnt/c/Users/oguz_/.gemini/config/plugins/edge/tools/brigade/orchestrator_guard.py", "pre_invocation"],
    input=json.dumps(payload_tool).encode("utf-8")
).decode("utf-8")
print("PreInvocation output:", res_inv.strip())

# Non orchestrator test
payload_non_orch = {
    "toolCall": {"name": "replace_file_content", "args": {}},
    "transcriptPath": "C:\\Users\\oguz_\\.gemini\\antigravity\\brain\\b28d971a-e45c-4b3e-9f87-3f5e2c5483ac\\.system_generated\\logs\\transcript.jsonl"
}
res_allow = subprocess.check_output(
    ["python3", "/mnt/c/Users/oguz_/.gemini/config/plugins/edge/tools/brigade/orchestrator_guard.py", "pre_tool"],
    input=json.dumps(payload_non_orch).encode("utf-8")
).decode("utf-8")
print("Non-orch PreToolUse output:", res_allow.strip())
