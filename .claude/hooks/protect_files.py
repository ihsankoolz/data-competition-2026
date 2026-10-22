"""PreToolUse hook: block agent edits to secrets, lockfiles and git internals.

Exit code 2 blocks the edit; stderr is shown to Claude.
"""
import json
import sys

BLOCKED = [".env", "pnpm-lock.yaml", "uv.lock", ".git/", ".git\\"]
ALLOWED = [".env.example"]

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "") or ""
norm = path.replace("\\", "/")

if any(norm.endswith(a) for a in ALLOWED):
    sys.exit(0)
for pattern in BLOCKED:
    p = pattern.replace("\\", "/")
    if norm.endswith(p) or f"/{p}" in norm or (p.endswith("/") and p in norm):
        print(f"Blocked: {path} is protected ({pattern}). Ask the human to change it.", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
