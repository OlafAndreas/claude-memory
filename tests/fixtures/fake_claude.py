#!/usr/bin/env python3
"""Stand-in for `claude -p` in tests. Mode via FAKE_CLAUDE_MODE: ok|fenced|garbage|fail|sleep|notworth."""
import json
import os
import sys
import time

prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd(),
                            "claudecode": os.environ.get("CLAUDECODE"),
                            "env": {k: os.environ.get(k) for k in ("CLAUDE_MEMORY_CHILD", "CLAUDE_CONFIG_DIR")}}) + "\n")

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
inner = os.environ.get("FAKE_CLAUDE_JSON") or json.dumps({
    "worth_keeping": mode != "notworth",
    "handoff": {"summary": "Measured the bucket: 250 wide, not 247",
                "surface_when": "bøtte, HÅLLBAR, bucket, measurement",
                "body": os.environ.get("FAKE_CLAUDE_BODY", "I assumed 247; the user measured 250.")},
    "notes": [{"kind": "lesson", "summary": "Measure before trusting assumed dimensions",
               "surface_when": "mål, måling, measure, assumed dimension", "body": "Ask for a caliper reading."}],
})
if mode == "fail":
    sys.stderr.write("not logged in\n")
    sys.exit(1)
if mode == "sleep":
    time.sleep(5)
if mode == "garbage":
    inner = "I could not do that, sorry."
if mode == "fenced":
    inner = f"```json\n{inner}\n```"
print(json.dumps({"type": "result", "result": inner}))
