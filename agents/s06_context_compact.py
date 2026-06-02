#!/usr/bin/env python3
# Harness: compression + planning -- todo state survives context compression.
"""
s06_context_compact.py - Compact + TodoWrite

Combines s06 (context compression) with s03 (todo tracking).

The key insight: TodoManager lives in Python memory, NOT in messages[].
When auto_compact wipes messages[], the todo list survives untouched.

    messages (compressed away)     TodoManager.items (always alive)
    ─────────────────────────      ──────────────────────────────────
    [摘要一條]              vs     [x] #1: 讀 s01
                                   [x] #2: 讀 s02
                                   [x] #3: 讀 s03
                                   [ ] #4: 讀 s04   <-- model wakes up,
                                   [ ] #5: 讀 s05       checks todo,
                                   [ ] #6: 讀 s06       continues here
                                   [ ] #7: 寫總整理

    After compact, model calls todo (no args) to read current state,
    then picks up from the first pending item.

Key insight: "Out-of-band state survives compression."
"""

import json
import os
import subprocess
import time
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

WORKDIR = Path.cwd()
client = OpenAI(
    base_url=os.environ["BASE_URL"],
    api_key=os.getenv("API_KEY", "none"),
)
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use the todo tool to plan and track multi-step tasks. Mark in_progress before starting, completed when done.
After any context compression, call todo (no args) first to check remaining work.

When creating todos, break tasks into the smallest concrete steps possible.
For example, if asked to read 8 files, create 8 separate todo items, one per file.
Never group multiple files or actions into a single todo item."""

THRESHOLD = 3000  # 調低方便 demo，正式用途改回 50000
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
KEEP_RECENT = 3
PRESERVE_RESULT_TOOLS = {"read_file"}


def estimate_tokens(messages: list) -> int:
    return len(str(messages)) // 4


# -- TodoManager: lives in Python memory, survives compact --
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


TODO = TodoManager()


# -- Layer 1: micro_compact --
def micro_compact(messages: list) -> list:
    tool_results = [(i, msg) for i, msg in enumerate(messages) if msg.get("role") == "tool"]
    if len(tool_results) <= KEEP_RECENT:
        return messages
    tool_name_map = {}
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tool_name_map[tc["id"]] = tc["function"]["name"]
    to_clear = tool_results[:-KEEP_RECENT]
    for idx, msg in to_clear:
        content = msg.get("content", "")
        if not isinstance(content, str) or len(content) <= 100:
            continue
        tool_name = tool_name_map.get(msg.get("tool_call_id", ""), "unknown")
        if tool_name in PRESERVE_RESULT_TOOLS:
            continue
        messages[idx]["content"] = f"[Previous: used {tool_name}]"
    return messages


# -- Layer 2: auto_compact --
def auto_compact(messages: list, focus: str = "") -> list:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    print(f"[transcript saved: {transcript_path}]")

    # Always include current todo state in focus so the summary captures it
    todo_state = TODO.render()
    combined_focus = f"current todo list: {todo_state}"
    if focus:
        combined_focus += f". Also: {focus}"

    conversation_text = json.dumps(messages, default=str)[-80000:]
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            "Summarize this conversation for continuity. Include: "
            "1) What was accomplished, 2) Current state, 3) Key decisions made. "
            f"Pay special attention to preserving: {combined_focus}.\n\n"
            + conversation_text}],
        max_tokens=2000,
    )
    summary = response.choices[0].message.content or "No summary generated."
    return [
        {"role": "user", "content":
            f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}\n\n"
            f"[Current todo state]\n{todo_state}"},
    ]


# -- Tool implementations --
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]) if kw.get("items") else TODO.render(),
    "compact":    lambda **kw: "Compressing...",
}

TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description": "Run a shell command.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read file contents.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Write content to file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file", "description": "Replace exact text in file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}}},
    {"type": "function", "function": {
        "name": "todo",
        "description": "Update task list, or call with no args to read current state.",
        "parameters": {"type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "text": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
            },
            "required": ["id", "text", "status"],
        }}}}}},
    {"type": "function", "function": {
        "name": "compact", "description": "Trigger manual conversation compression.",
        "parameters": {"type": "object", "properties": {"focus": {"type": "string"}}}}},
]


def agent_loop(messages: list):
    rounds_since_todo = 0
    while True:
        micro_compact(messages)
        tokens = estimate_tokens(messages)
        print(f"\033[90m[context: ~{tokens} tokens | todo: {sum(1 for t in TODO.items if t['status']=='completed')}/{len(TODO.items)}]\033[0m")
        if tokens > THRESHOLD:
            print("[auto_compact triggered]")
            messages[:] = auto_compact(messages)
            print(f"\033[90m[context after compact: ~{estimate_tokens(messages)} tokens]\033[0m")

        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        asst_msg = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            asst_msg["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        messages.append(asst_msg)

        if finish_reason != "tool_calls":
            return

        manual_compact = False
        compact_focus = ""
        used_todo = False
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            if tc.function.name == "compact":
                manual_compact = True
                compact_focus = args.get("focus", "")
                output = "Compressing..."
            else:
                handler = TOOL_HANDLERS.get(tc.function.name)
                try:
                    output = handler(**args) if handler else f"Unknown tool: {tc.function.name}"
                except Exception as e:
                    output = f"Error: {e}"
            if tc.function.name == "todo":
                used_todo = True
            print(f"> {tc.function.name}:")
            print(str(output)[:200])
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(output),
            })

        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            messages.append({"role": "user", "content": "<reminder>Update your todos.</reminder>"})

        if manual_compact:
            print("[manual compact]")
            messages[:] = auto_compact(messages, focus=compact_focus)
            return


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms06 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        last = history[-1]
        if last.get("content") and last.get("role") == "assistant":
            print(last["content"])
        print()
