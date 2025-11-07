"""
Single agent implementation
"""

import json
import sys
from typing import List

from .config import OPENAI_API_MODE, OPENAI_BASE_URL, OPENAI_MODEL
from .docker_utils import ensure_up
from .tools import TOOLS_FOR_CHAT, TOOLS_FOR_RESPONSES, dispatch_tool

SYSTEM_RULES = """You are NomanAI, a security remediation agent working inside an Ubuntu container.

Available tools:
- read_file, write_file: File operations
- set_config_kv: Set configuration key-value pairs
- restart_service: Manage services (start, stop, restart, enable, disable)
- install_package, remove_package: Package management
- update_system: Update and upgrade system packages
- list_packages, search_packages: Package discovery
- check_service_status, list_services: Service management
- create_directory, change_permissions, change_ownership: File system operations
- run_safe: Execute system commands
- verify_regex: Verify file content

Rules:
- You MUST use tools; do not output shell or config content directly as final answer.
- Prefer set_config_kv(path, key, value) for changes in configuration files.
- Make minimal, reversible edits; always verify after changes.
- When enabling services, use restart_service with action='enable' to ensure they start at boot.
- For system updates, use update_system tool.
- If the policy says [policy:deny_insecure], do NOT set insecure values (e.g., PermitRootLogin yes, PasswordAuthentication yes). Stop and report.
- If the policy says [policy:allow_insecure], you may set insecure values when explicitly asked.
"""


def _client():
    """Create an OpenAI client."""
    from openai import OpenAI
    kwargs = {}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def agent(goal: str, max_iters: int = 10) -> List[dict]:
    """
    Tool-using agent loop. Defaults to Chat Completions; optionally uses Responses API.
    Returns a transcript of actions/results.
    """
    ensure_up()
    transcript: List[dict] = []
    client = _client()

    # Helper: dispatch a single tool call
    def _dispatch(name: str, args: dict) -> dict:
        return dispatch_tool(name, args)

    # -------- Prefer Responses API if explicitly requested --------
    if OPENAI_API_MODE == "responses":
        try:
            response = client.responses.create(
                model=OPENAI_MODEL,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_RULES}]},
                    {"role": "user", "content": [{"type": "input_text", "text": f"Goal: {goal}\nUse tools; then verify."}]},
                ],
                tools=TOOLS_FOR_RESPONSES,
                tool_choice="auto",
            )

            def _extract_tool_calls(resp) -> List[dict]:
                items = getattr(resp, "output", None) or []
                calls = []
                for it in items:
                    if getattr(it, "type", None) == "tool_call":
                        args = getattr(it, "arguments", None)
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        calls.append({"id": getattr(it, "id", None), "name": getattr(it, "name", None), "args": args})
                return calls

            def _final_text(resp) -> str | None:
                try:
                    return resp.output_text
                except Exception:
                    return None

            steps = 0
            while steps < max_iters:
                calls = _extract_tool_calls(response)
                if not calls:
                    text = _final_text(response)
                    if text:
                        transcript.append({"final": text})
                    break

                tool_outputs = []
                for call in calls:
                    name, args = call["name"], call["args"] or {}
                    out = _dispatch(name, args)
                    transcript.append({"action": {"tool": name, "args": args}, "result": out})
                    tool_outputs.append({"tool_call_id": call["id"], "output": json.dumps(out)})

                response = client.responses.create(
                    model=OPENAI_MODEL,
                    response_id=response.id,
                    tool_outputs=tool_outputs,
                )
                steps += 1

            return transcript
        except Exception as e:
            print(f"[NomanAI] Responses API failed, falling back to chat: {e}", file=sys.stderr)

    # -------- Chat Completions (stable fallback / default) --------
    messages = [
        {"role": "system", "content": SYSTEM_RULES},
        {"role": "user", "content": f"Goal: {goal}\nYou MUST use tools to make changes and then verify."}
    ]
    for _ in range(max_iters):
        res = client.chat.completions.create(
            model=OPENAI_MODEL, messages=messages, tools=TOOLS_FOR_CHAT, tool_choice="auto"
        )
        msg = res.choices[0].message

        if msg.tool_calls:
            # IMPORTANT: append the assistant message with tool_calls BEFORE tool outputs
            assistant_tool_calls_payload = []
            for tc in msg.tool_calls:
                assistant_tool_calls_payload.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}
                })
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls_payload})

            # Now execute each tool and append tool results
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args_str = tc.function.arguments or "{}"
                    args = json.loads(args_str)
                except json.JSONDecodeError as e:
                    args = {}
                    print(f"[Agent] Warning: Failed to parse JSON arguments for {name}: {args_str}", file=sys.stderr)
                except Exception as e:
                    args = {}
                    print(f"[Agent] Warning: Error parsing arguments for {name}: {e}", file=sys.stderr)
                out = _dispatch(name, args)
                transcript.append({"action": {"tool": name, "args": args}, "result": out})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)})

        else:
            # Final assistant text (no more tool calls)
            transcript.append({"final": msg.content})
            break

    return transcript

