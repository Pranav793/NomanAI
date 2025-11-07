"""
Multi-agent system: Planner, Executor, and Verifier agents
"""

import json
import re
import sys
from typing import List

from . import config
from .config import OPENAI_BASE_URL, OPENAI_MODEL
from .docker_utils import ensure_up
from .tools import TOOLS_FOR_CHAT, dispatch_tool, tool_read_file, tool_list_services, tool_list_packages

PLANNER_SYSTEM_PROMPT = """You are the Planner Agent for NomanAI, a security remediation system.
Your role is to analyze a natural language goal and create a detailed, step-by-step plan.
The plan should be specific, actionable, and consider the current system state.

IMPORTANT POLICY RULES:
- If the goal contains [policy:deny_insecure], you MUST NOT plan any insecure security configurations.
- Insecure configurations include: enabling PasswordAuthentication, enabling PermitRootLogin, or any other security-weakening changes.
- If the goal requires an insecure change but [policy:deny_insecure] is present, you MUST either:
  1. Refuse to create the plan and explain why, OR
  2. Create a plan that checks the current state but does NOT attempt the insecure change, and explains that the policy blocks it.
- If the goal contains [policy:allow_insecure], you may plan insecure changes when explicitly requested.

Output a JSON list of steps, where each step has:
- step_number: integer
- action: string describing what to do
- tool: string (tool name to use: read_file, write_file, set_config_kv, restart_service, install_package, remove_package, update_system, list_packages, search_packages, check_service_status, list_services, create_directory, change_permissions, change_ownership, run_safe, verify_regex)
- parameters: object with tool-specific parameters
- expected_result: string describing what success looks like

When managing services, use restart_service with action='enable' to ensure services start at boot and are running. Use action='restart' for a full restart, or action='start' to just start.

Be thorough: include steps to check current state, make changes, restart services if needed, and verify results.
For security configurations, always include verification steps."""

EXECUTOR_SYSTEM_PROMPT = """You are the Executor Agent for NomanAI.
Your role is to execute the planned steps EXACTLY as specified in the plan.

CRITICAL RULES:
1. Execute steps IN ORDER from the plan
2. Use the EXACT tool name specified in each step
3. Use the EXACT parameters specified in each step's "parameters" field
4. DO NOT skip steps - execute every step in the plan
5. DO NOT execute tools that are not in the plan
6. DO NOT deviate from the plan unless explicitly necessary

For each step:
- Read the step_number, action, tool, and parameters
- Call the specified tool with the specified parameters (even if parameter names seem slightly different, the system will handle normalization)
- Continue to the next step after executing the current one
- If a step fails, analyze the error, but continue with remaining steps unless the failure makes them impossible

Parameter handling:
- Use the parameter names from the plan as-is (the system will normalize them)
- If the plan says "package_names": ["openssh-server"], use it exactly as specified
- If the plan says "service_name": "ssh", use it exactly as specified
- The system handles parameter name variations automatically

Error handling:
- If a tool fails, note the error but continue
- Some steps may be independent and can succeed even if earlier steps failed
- Report errors clearly but don't stop execution

Your goal is to execute ALL steps in the plan, in order, using the exact tools and parameters specified."""

VERIFIER_SYSTEM_PROMPT = """You are the Verification Agent for NomanAI.
Your role is to verify that the goal has been achieved.

CRITICAL RULES:
1. Check the EXACT file paths and locations from the execution transcript
2. If files were created in /tmp/, check /tmp/, not ~/.ssh/ or other default locations
3. If the execution transcript shows files were read successfully, verify those same paths
4. Use the execution transcript to understand what was actually done
5. Don't assume default locations - use the actual paths from execution

Verification steps:
- Check the current state of the system using the paths from execution
- Verify that files exist at the locations shown in the execution transcript
- Verify file contents match expectations (check actual file contents)
- Test that services are running correctly if applicable
- Confirm security configurations are in place
- Report success or failure with specific evidence
- If files were successfully read in execution, verify those same files still exist and have content"""


def _client():
    """Create an OpenAI client."""
    from openai import OpenAI
    kwargs = {}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def planner_agent(goal: str, max_iters: int = 5, previous_attempt: dict = None) -> List[dict]:
    """Planner agent: creates a detailed plan from a natural language goal.
    
    Args:
        goal: The goal to achieve
        max_iters: Maximum iterations for planning
        previous_attempt: Optional dict with 'plan', 'execution', and 'verification' from previous attempt
    """
    ensure_up()
    client = _client()
    
    # Build initial prompt
    prompt = f"Create a detailed plan to achieve this goal: {goal}\n\nAvailable tools:\n"
    prompt += "- read_file: Read files\n"
    prompt += "- write_file: Write files\n"
    prompt += "- set_config_kv: Set config key-value pairs\n"
    prompt += "- restart_service: Manage services (start, stop, restart, enable, disable)\n"
    prompt += "- install_package: Install packages (can install multiple)\n"
    prompt += "- remove_package: Remove packages\n"
    prompt += "- update_system: Update and upgrade system packages\n"
    prompt += "- list_packages: List installed packages\n"
    prompt += "- search_packages: Search for available packages\n"
    prompt += "- check_service_status: Check service status\n"
    prompt += "- list_services: List system services\n"
    prompt += "- create_directory: Create directories\n"
    prompt += "- change_permissions: Change file permissions\n"
    prompt += "- change_ownership: Change file ownership\n"
    prompt += "- run_safe: Run system commands (grep, systemctl, apt, etc.)\n"
    prompt += "- verify_regex: Verify file content with regex\n\n"
    
    # Add feedback from previous attempt if provided
    if previous_attempt:
        prompt += "\n=== PREVIOUS ATTEMPT FAILED - LEARN FROM THIS ===\n"
        prompt += "A previous attempt to achieve this goal failed. Analyze what went wrong and create a new plan that addresses these issues.\n\n"
        
        if previous_attempt.get('verification', {}).get('failure_analysis'):
            failure = previous_attempt['verification']['failure_analysis']
            prompt += f"Verification Conclusion: {failure.get('conclusion', 'N/A')}\n\n"
            
            if failure.get('failed_steps'):
                prompt += "Failed Steps:\n"
                for failed_step in failure['failed_steps']:
                    step_name = failed_step.get('step', 'unknown')
                    args = failed_step.get('args', {})
                    error = failed_step.get('error', 'Unknown error')
                    prompt += f"  - {step_name}({args}): {error[:300]}\n"
                prompt += "\n"
            
            if previous_attempt.get('plan'):
                prompt += "Previous Plan (for reference):\n"
                for step in previous_attempt['plan']:
                    prompt += f"  {step.get('step_number', '?')}. {step.get('action', 'N/A')}\n"
                prompt += "\n"
        
        prompt += "IMPORTANT: Create a NEW plan that:\n"
        prompt += "1. Addresses the root causes of the failures\n"
        prompt += "2. Includes steps to check prerequisites (e.g., install missing packages)\n"
        prompt += "3. Verifies each step before proceeding\n"
        prompt += "4. Uses alternative approaches if the previous method failed\n\n"
    
    prompt += "Output a JSON array of steps."
    
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    # Use read_file tool to help planner understand current state
    tools_for_planning = [
        {"type": "function", "function": {
            "name": "read_file", "description": "Read a file to understand current configuration."}},
    ]

    plan_steps = []
    for _ in range(max_iters):
        res = client.chat.completions.create(
            model=OPENAI_MODEL, messages=messages, tools=tools_for_planning, tool_choice="auto"
        )
        msg = res.choices[0].message

        if msg.tool_calls:
            # Execute read_file if planner wants to check current state
            for tc in msg.tool_calls:
                if tc.function.name == "read_file":
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                        result = tool_read_file(**args)
                        messages.append({"role": "assistant", "content": None, "tool_calls": [{
                            "id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                        }]})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
                    except Exception as e:
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"ok": False, "error": str(e)})})
        else:
            # Extract plan from response
            content = msg.content or ""
            # Try to parse JSON plan from response
            try:
                # Look for JSON array in the response
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    plan_steps = json.loads(json_match.group())
                else:
                    # If no JSON, parse as text steps
                    lines = content.split('\n')
                    step_num = 1
                    for line in lines:
                        if line.strip() and (line.strip().startswith('-') or line.strip().startswith('*') or re.match(r'^\d+\.', line.strip())):
                            plan_steps.append({
                                "step_number": step_num,
                                "action": line.strip().lstrip('-*').lstrip('0123456789. '),
                                "tool": "run_safe",  # default
                                "parameters": {},
                                "expected_result": "Step completed"
                            })
                            step_num += 1
            except Exception:
                # If parsing fails, create a simple plan from the text
                plan_steps = [{"step_number": 1, "action": content, "tool": "run_safe", "parameters": {}, "expected_result": "Goal achieved"}]
            break

    return plan_steps if plan_steps else [{"step_number": 1, "action": goal, "tool": "run_safe", "parameters": {}, "expected_result": "Goal achieved"}]


def executor_agent(plan: List[dict], max_iters: int = 20) -> List[dict]:
    """Executor agent: executes the planned steps."""
    ensure_up()
    transcript = []
    client = _client()

    # Convert plan to execution context with clear instructions
    plan_steps = []
    for i, s in enumerate(plan):
        step_num = s.get('step_number', i+1)
        action = s.get('action', '')
        tool = s.get('tool', 'run_safe')
        params = s.get('parameters', {})
        plan_steps.append(f"STEP {step_num}: {action}\n  Tool: {tool}\n  Parameters: {params}")
    
    plan_context = "\n\n".join(plan_steps)

    messages = [
        {"role": "system", "content": EXECUTOR_SYSTEM_PROMPT},
        {"role": "user", "content": f"""Execute this plan EXACTLY as specified. Execute each step in order using the exact tool and parameters shown.

PLAN TO EXECUTE:
{plan_context}

INSTRUCTIONS:
1. Start with STEP 1 and execute it using the specified tool and parameters
2. After completing STEP 1, move to STEP 2, then STEP 3, and so on
3. Execute ALL steps in the plan, in order
4. Use the exact tool names and parameters from each step
5. Continue even if some steps fail - complete all steps

Begin executing STEP 1 now."""}
    ]

    for iteration in range(max_iters):
        res = client.chat.completions.create(
            model=OPENAI_MODEL, messages=messages, tools=TOOLS_FOR_CHAT, tool_choice="auto"
        )
        msg = res.choices[0].message

        if msg.tool_calls:
            assistant_tool_calls = []
            for tc in msg.tool_calls:
                assistant_tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}
                })
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls})

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args_str = tc.function.arguments or "{}"
                    args = json.loads(args_str)
                except json.JSONDecodeError as e:
                    args = {}
                    print(f"[Executor] Warning: Failed to parse JSON arguments for {name}: {args_str}", file=sys.stderr)
                except Exception as e:
                    args = {}
                    print(f"[Executor] Warning: Error parsing arguments for {name}: {e}", file=sys.stderr)
                out = dispatch_tool(name, args)
                transcript.append({"step": name, "args": args, "result": out})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)})
        else:
            # Check if we've completed all steps
            content = msg.content or ""
            # If the agent says it's done but we haven't completed all steps, remind it
            if "done" in content.lower() or "complete" in content.lower() or "finished" in content.lower():
                # Count how many steps we've executed
                executed_steps = len([t for t in transcript if "step" in t])
                if executed_steps < len(plan):
                    # Remind the executor to continue
                    messages.append({
                        "role": "user",
                        "content": f"You have executed {executed_steps} steps, but the plan has {len(plan)} steps. Please continue executing the remaining steps from the plan. Start with STEP {executed_steps + 1}."
                    })
                    continue
            transcript.append({"final": content})
            break

    return transcript


def verifier_agent(goal: str, execution_transcript: List[dict], max_iters: int = 10) -> dict:
    """Verifier agent: verifies that the goal was achieved."""
    ensure_up()
    client = _client()

    # Tools for verification (read-only + verification)
    verify_tools = [
        {"type": "function", "function": {
            "name": "read_file", "description": "Read a file to verify its contents.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
        {"type": "function", "function": {
            "name": "run_safe", "description": "Run a command to check system state.",
            "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
        {"type": "function", "function": {
            "name": "verify_regex", "description": "Verify that file content matches a pattern.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "regex": {"type": "string"}},
             "required": ["path", "regex"]}}},
        {"type": "function", "function": {
            "name": "check_service_status", "description": "Check service status and get detailed information.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
        {"type": "function", "function": {
            "name": "list_services", "description": "List system services to verify service configuration.",
            "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "default": ""}}, "required": []}}},
        {"type": "function", "function": {
            "name": "list_packages", "description": "List installed packages to verify package installation.",
            "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "default": ""}}, "required": []}}},
    ]

    # Create detailed execution summary including file paths and results
    exec_details = []
    failed_steps = []
    for s in execution_transcript:
        if 'step' in s:
            step_name = s.get('step', 'unknown')
            args = s.get('args', {})
            result = s.get('result', {})
            ok = result.get('ok', False)
            
            detail = f"- {step_name}({args}): ok={ok}"
            
            # Include file paths for file operations
            if step_name in ["read_file", "write_file"] and "path" in args:
                detail += f", file={args['path']}"
                # If read_file succeeded, note that content was retrieved
                if step_name == "read_file" and ok and result.get("content"):
                    content_len = len(result.get("content", ""))
                    detail += f", content_length={content_len}"
                elif step_name == "read_file" and ok and not result.get("content"):
                    detail += f", file_empty=True"
            
            # Include command for run_safe
            if step_name == "run_safe" and "cmd" in args:
                detail += f", cmd={args['cmd']}"
                if not ok:
                    error_msg = result.get("stderr", "") or result.get("stdout", "")
                    if error_msg:
                        detail += f", error={error_msg[:200]}"
            
            # Track failed steps with detailed error info
            if not ok:
                error_info = {
                    "step": step_name,
                    "args": args,
                    "error": result.get("stderr", "") or result.get("stdout", "") or "Unknown error"
                }
                failed_steps.append(error_info)
            
            exec_details.append(detail)
    
    exec_summary = "\n".join(exec_details)

    messages = [
        {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": f"""Verify that this goal was achieved: {goal}

Execution transcript:
{exec_summary}

IMPORTANT: Use the file paths and locations from the execution transcript above. 
For example, if files were created in /tmp/, check /tmp/, not ~/.ssh/.
If keys were generated, check the exact paths where they were created.
Check the system state and confirm if the goal is met. Be thorough."""}
    ]

    verification_results = []
    for _ in range(max_iters):
        res = client.chat.completions.create(
            model=OPENAI_MODEL, messages=messages, tools=verify_tools, tool_choice="auto"
        )
        msg = res.choices[0].message

        if msg.tool_calls:
            assistant_tool_calls = []
            for tc in msg.tool_calls:
                assistant_tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}
                })
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls})

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args_str = tc.function.arguments or "{}"
                    args = json.loads(args_str)
                except json.JSONDecodeError as e:
                    args = {}
                    print(f"[Verifier] Warning: Failed to parse JSON arguments for {name}: {args_str}", file=sys.stderr)
                except Exception as e:
                    args = {}
                    print(f"[Verifier] Warning: Error parsing arguments for {name}: {e}", file=sys.stderr)
                out = dispatch_tool(name, args)
                verification_results.append({"check": name, "args": args, "result": out})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)})
        else:
            # Final verification conclusion
            conclusion = msg.content or "Verification incomplete"
            # Try to determine success from the conclusion
            success_keywords = ["success", "achieved", "verified", "complete", "correct", "pass"]
            failure_keywords = ["fail", "error", "missing", "incorrect", "not achieved", "not met", "not created", "not generated", "empty", "no content"]
            conclusion_lower = conclusion.lower()
            success = any(kw in conclusion_lower for kw in success_keywords) and not any(kw in conclusion_lower for kw in failure_keywords)
            
            # Build failure analysis for retry
            failure_analysis = None
            if not success:
                failure_analysis = {
                    "conclusion": conclusion,
                    "failed_steps": failed_steps,
                    "verification_checks": verification_results
                }
            
            return {
                "success": success,
                "conclusion": conclusion,
                "checks": verification_results,
                "failure_analysis": failure_analysis
            }

    return {
        "success": False, 
        "conclusion": "Verification incomplete - max iterations reached", 
        "checks": verification_results,
        "failure_analysis": {
            "conclusion": "Verification incomplete - max iterations reached",
            "failed_steps": failed_steps,
            "verification_checks": verification_results
        }
    }


def multi_agent_system(goal: str, allow_insecure: bool = False, max_retries: int = 3) -> dict:
    """Multi-agent system: coordinates Planner, Executor, and Verifier agents with retry loop.
    
    Args:
        goal: The goal to achieve
        allow_insecure: Whether to allow insecure configurations
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        dict with goal, attempts (list of all attempts), and final result
    """
    config.ALLOW_INSECURE = allow_insecure
    ensure_up()
    
    attempts = []
    previous_attempt = None
    
    for attempt_num in range(1, max_retries + 1):
        print(f"\n{'='*70}")
        print(f"ATTEMPT {attempt_num} of {max_retries}")
        print(f"{'='*70}")
        
        if attempt_num > 1:
            print(f"[Planner] Replanning based on previous failure...")
        else:
            print(f"[Planner] Creating plan for: {goal}")
        
        plan = planner_agent(goal, previous_attempt=previous_attempt)
        print(f"[Planner] Created plan with {len(plan)} steps")

        print(f"[Executor] Executing plan...")
        execution = executor_agent(plan)
        print(f"[Executor] Completed {len([s for s in execution if 'step' in s])} steps")

        print(f"[Verifier] Verifying goal achievement...")
        verification = verifier_agent(goal, execution)
        success = verification.get('success', False)
        print(f"[Verifier] Verification: {'SUCCESS' if success else 'FAILED'}")
        
        # Store this attempt
        attempt = {
            "attempt_number": attempt_num,
            "plan": plan,
            "execution": execution,
            "verification": verification
        }
        attempts.append(attempt)
        
        # If successful, return immediately
        if success:
            print(f"\n{'='*70}")
            print(f"SUCCESS achieved on attempt {attempt_num}")
            print(f"{'='*70}\n")
            return {
                "goal": goal,
                "success": True,
                "attempts": attempts,
                "final_attempt": attempt_num,
                "plan": plan,
                "execution": execution,
                "verification": verification
            }
        
        # If not successful and we have retries left, prepare for next attempt
        if attempt_num < max_retries:
            print(f"\n[System] Attempt {attempt_num} failed. Preparing retry...")
            previous_attempt = attempt
        else:
            print(f"\n[System] All {max_retries} attempts exhausted.")
    
    # All attempts failed
    print(f"\n{'='*70}")
    print(f"FAILED after {max_retries} attempts")
    print(f"{'='*70}\n")
    return {
        "goal": goal,
        "success": False,
        "attempts": attempts,
        "final_attempt": max_retries,
        "plan": attempts[-1]["plan"],
        "execution": attempts[-1]["execution"],
        "verification": attempts[-1]["verification"]
    }

