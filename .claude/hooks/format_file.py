"""PostToolUse hook: auto-format the file an agent just edited.

Never fails the turn: formatter errors are ignored.
"""
import json
import os
import subprocess
import sys

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "") or ""
root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
web = os.path.join(root, "apps", "web")
shell = os.name == "nt"


def run(cmd, cwd):
    try:
        subprocess.run(cmd, cwd=cwd, shell=shell, timeout=50,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


if path.endswith(".py"):
    run(["uv", "run", "ruff", "format", path], root)
    run(["uv", "run", "ruff", "check", "--fix", path], root)
elif path.endswith((".ts", ".tsx", ".js", ".jsx", ".css", ".json")) and os.path.isdir(web):
    if os.path.abspath(path).startswith(os.path.abspath(web)):
        run(["pnpm", "exec", "prettier", "--write", path], web)
sys.exit(0)
