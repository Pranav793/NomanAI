"""
Command-line interface for NomanAI
"""

import argparse
import sys

from . import config
from .agents import agent
from .docker_utils import docker_exec, down, ensure_up
from .fixes import FIXES, apply_fixes, plan_fixes, resolve_fixes, verify_fixes
from .multi_agent import multi_agent_system
from .remote_exec import RemoteExecutor, set_executor
from .ssh_client import SSHConfig, get_ssh_manager


def main():
    """Main CLI entry point."""
    ap = argparse.ArgumentParser(description=f"{config.APP_NAME} — safe containerized fixer + OpenAI agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("up", help="create/start container")
    sub.add_parser("down", help="delete container")

    # Robust exec: accept all remaining args after "--" to avoid shell quoting issues
    p_exec = sub.add_parser("exec", help="run a command in container (use '--' before command or --cmd)")
    p_exec.add_argument("--cmd", dest="exec_cmd", help="(optional) command string")
    p_exec.add_argument("cmd_list", nargs="*", help="command parts after '--' (preferred)")

    def add_fix_arg(p):
        p.add_argument("--fix", action="append", default=None,
                       help=f"Fix id (repeatable). Known: {', '.join(list(FIXES.keys()) + ['all'])}. Default=ssh_disable_root")

    p_plan = sub.add_parser("plan", help="show plan")
    add_fix_arg(p_plan)
    p_apply = sub.add_parser("apply", help="apply fix(es)")
    add_fix_arg(p_apply)
    p_verify = sub.add_parser("verify", help="verify fix(es)")
    add_fix_arg(p_verify)

    p_agent = sub.add_parser("agent", help="Use the OpenAI-powered agent with tool calling")
    p_agent.add_argument("--goal", required=True, help="Natural language goal (e.g., 'Disable SSH password auth')")
    p_agent.add_argument("--iters", type=int, default=10, help="Max tool steps (default 10)")
    p_agent.add_argument("--allow-insecure", action="store_true",
                         help="Permit the agent to weaken security (e.g., enable root login/password auth) for testing")

    p_multi = sub.add_parser("multi-agent", help="Use multi-agent system (Planner + Executor + Verifier)")
    p_multi.add_argument("--goal", required=True, help="Natural language goal (e.g., 'Disable SSH password auth and restart SSH service')")
    p_multi.add_argument("--allow-insecure", action="store_true",
                         help="Permit insecure configurations for testing")
    p_multi.add_argument("--max-retries", type=int, default=3,
                         help="Maximum number of retry attempts if verification fails (default: 3)")
    p_multi.add_argument("--ssh-host", help="SSH host to connect to (e.g., user@host or user@host:port)")
    p_multi.add_argument("--ssh-key", "--key", dest="ssh_key", help="Path to SSH private key file")
    p_multi.add_argument("--ssh-password", help="SSH password (not recommended, use key-based auth)")
    p_multi.add_argument("--ssh-port", type=int, default=22, help="SSH port (default: 22)")
    
    p_ssh = sub.add_parser("ssh", help="SSH connection management")
    p_ssh_sub = p_ssh.add_subparsers(dest="ssh_cmd", required=True)
    
    p_ssh_test = p_ssh_sub.add_parser("test", help="Test SSH connection")
    p_ssh_test.add_argument("--host", required=True, help="SSH host (e.g., user@host or user@host:port)")
    p_ssh_test.add_argument("--key", help="Path to SSH private key file")
    p_ssh_test.add_argument("--password", help="SSH password")
    p_ssh_test.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    
    p_ssh_exec = p_ssh_sub.add_parser("exec", help="Execute command via SSH")
    p_ssh_exec.add_argument("--host", required=True, help="SSH host (e.g., user@host or user@host:port)")
    p_ssh_exec.add_argument("--key", help="Path to SSH private key file")
    p_ssh_exec.add_argument("--password", help="SSH password")
    p_ssh_exec.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    p_ssh_exec.add_argument("--cmd", required=True, help="Command to execute")
    
    p_ssh_stats = p_ssh_sub.add_parser("stats", help="Show SSH connection pool statistics")

    args = ap.parse_args()

    if args.cmd == "up":
        ensure_up()
        # Show which image is being used
        from .docker_utils import docker
        rc, current_img, _ = docker(f"inspect {config.CONTAINER} --format='{{{{.Config.Image}}}}' 2>/dev/null || echo 'unknown'")
        if rc == 0:
            img = current_img.strip()
            systemd_status = "systemd-enabled" if config.USE_SYSTEMD_CONTAINER else "standard"
            print(f"{config.APP_NAME} container '{config.CONTAINER}' ready (image: {img}, type: {systemd_status}).")
        else:
            print(f"{config.APP_NAME} container '{config.CONTAINER}' ready.")

    elif args.cmd == "down":
        down()
        print("Container removed.")

    elif args.cmd == "exec":
        ensure_up()
        command = None
        # Handle cmd_list (from positional args after --) - preferred method
        if hasattr(args, 'cmd_list') and args.cmd_list:
            command = " ".join(args.cmd_list).strip()
        # Handle --cmd flag as fallback
        if not command and hasattr(args, 'exec_cmd') and args.exec_cmd:
            command = args.exec_cmd
        if not command:
            print("Usage: nomanai.py exec -- <your shell command>", file=sys.stderr)
            print("   or: nomanai.py exec --cmd '<your shell command>'", file=sys.stderr)
            sys.exit(2)
        rc, out, err = docker_exec(command)
        print(out, end="")
        if rc != 0 and err:
            print(err, file=sys.stderr, end="")
        sys.exit(rc)

    elif args.cmd == "plan":
        ensure_up()
        [print(s) for s in plan_fixes(resolve_fixes(args.fix))]

    elif args.cmd == "apply":
        ensure_up()
        changed, diff = apply_fixes(resolve_fixes(args.fix))
        print("No changes needed." if not changed else "Applied inside container. Unified diff:\n" + diff)

    elif args.cmd == "verify":
        ensure_up()
        ok, failed = verify_fixes(resolve_fixes(args.fix))
        print("PASS: all selected fixes verified" if ok else "FAIL: " + ", ".join(failed))

    elif args.cmd == "agent":
        ensure_up()
        config.ALLOW_INSECURE = bool(args.allow_insecure)
        goal = args.goal + (" [policy:allow_insecure]" if config.ALLOW_INSECURE else " [policy:deny_insecure]")
        tr = agent(goal, max_iters=args.iters)
        # compact transcript
        i = 0
        for step in tr:
            if "final" in step:
                print(f"\nFinal: {step['final']}")
            else:
                i += 1
                a, r = step["action"], step["result"]
                print(f"{i:02d}. {a['tool']} {a['args']} -> ok={r.get('ok')} rc={r.get('rc', '')}")
                if r.get("stderr"):
                    print("    err:", r["stderr"].strip())

    elif args.cmd == "multi-agent":
        # Determine target type (Docker or SSH)
        if args.ssh_host:
            # SSH mode
            host_parts = args.ssh_host.split('@')
            if len(host_parts) == 2:
                username, host_port = host_parts
            else:
                username = "root"
                host_port = host_parts[0]
            
            host_port_parts = host_port.split(':')
            host = host_port_parts[0]
            port = int(host_port_parts[1]) if len(host_port_parts) > 1 else args.ssh_port
            
            # Expand key file path if needed
            key_file = args.ssh_key
            if key_file:
                from pathlib import Path
                key_file = str(Path(key_file).expanduser())
            
            ssh_config = SSHConfig(
                host=host,
                port=port,
                username=username,
                key_file=key_file,
                password=args.ssh_password,
                timeout=config.SSH_DEFAULT_TIMEOUT,
            )
            executor = RemoteExecutor(target_type="ssh", ssh_config=ssh_config)
            set_executor(executor)
            
            # Test connection
            if not executor.test_connection():
                print(f"Error: Cannot connect to SSH host {args.ssh_host}", file=sys.stderr)
                sys.exit(1)
            print(f"Connected to SSH host: {args.ssh_host}")
        else:
            # Docker mode (default)
            ensure_up()
            executor = RemoteExecutor(target_type="docker")
            set_executor(executor)
        
        config.ALLOW_INSECURE = bool(args.allow_insecure)
        goal = args.goal + (" [policy:allow_insecure]" if config.ALLOW_INSECURE else " [policy:deny_insecure]")
        result = multi_agent_system(goal, allow_insecure=config.ALLOW_INSECURE, max_retries=args.max_retries)

        # Print results
        print("\n" + "="*70)
        print("MULTI-AGENT SYSTEM RESULTS")
        print("="*70)
        print(f"\nGoal: {result['goal']}")
        print(f"Success: {result.get('success', False)}")
        if result.get('attempts') and len(result['attempts']) > 1:
            print(f"Total Attempts: {len(result['attempts'])} (succeeded on attempt {result.get('final_attempt', '?')})")
        elif result.get('final_attempt'):
            print(f"Attempts: {result.get('final_attempt', 1)}")

        # Show final plan (from last attempt)
        print(f"\n[FINAL PLAN] {len(result['plan'])} steps:")
        for step in result['plan']:
            print(f"  {step.get('step_number', '?')}. {step.get('action', 'N/A')}")
            if step.get('tool'):
                print(f"      Tool: {step['tool']}, Params: {step.get('parameters', {})}")

        # Check if goal asks for file contents, keys, or similar
        goal_lower = result['goal'].lower()
        wants_content = any(keyword in goal_lower for keyword in [
            'give me', 'show me', 'display', 'content', 'contents', 'key pair', 
            'private key', 'public key', 'rsa key', 'ssh key', 'file content',
            'read file', 'cat', 'output', 'print'
        ])
        
        # Collect all file contents that were read
        file_contents = {}
        
        print(f"\n[FINAL EXECUTION] {len([s for s in result['execution'] if 'step' in s])} actions:")
        for i, exec_step in enumerate([s for s in result['execution'] if 'step' in s], 1):
            step_name = exec_step['step']
            args = exec_step.get('args', {})
            result_obj = exec_step.get('result', {})
            ok = result_obj.get('ok', False)
            print(f"  {i:02d}. {step_name} {args} -> ok={ok}")
            
            # Display file contents for read_file operations
            if step_name == "read_file" and ok:
                file_path = args.get("path", "unknown")
                content = result_obj.get("content", "")
                
                # Store content for summary
                file_contents[file_path] = content
                
                # Always display content if it exists
                if content:
                    lines = content.split('\n')
                    if len(lines) > 30:
                        print(f"      File {file_path} contents (first 10 and last 10 lines):")
                        for line in lines[:10]:
                            print(f"        {line}")
                        print("        ... (truncated) ...")
                        for line in lines[-10:]:
                            print(f"        {line}")
                    else:
                        print(f"      File {file_path} contents:")
                        for line in lines:
                            print(f"        {line}")
                else:
                    print(f"      File {file_path} is empty or could not be read")
            
            # Show stderr if there's an error
            if result_obj.get("stderr"):
                print(f"      Error: {result_obj['stderr'].strip()}")

        # Check verification results for additional file reads
        verif = result['verification']
        if verif.get('checks'):
            for check in verif['checks']:
                check_name = check.get('check', '')
                check_result = check.get('result', {})
                if check_name == "read_file" and check_result.get('ok') and "content" in check_result:
                    file_path = check.get('args', {}).get('path', 'unknown')
                    content = check_result["content"]
                    if file_path not in file_contents:  # Don't duplicate
                        file_contents[file_path] = content

        print(f"\n[FINAL VERIFICATION]")
        print(f"  Success: {verif.get('success', False)}")
        print(f"  Conclusion: {verif.get('conclusion', 'N/A')}")
        if verif.get('checks'):
            print(f"  Checks performed: {len(verif['checks'])}")
        
        # Show attempt history if there were multiple attempts
        if result.get('attempts') and len(result['attempts']) > 1:
            print(f"\n[ATTEMPT HISTORY]")
            for attempt in result['attempts']:
                attempt_num = attempt.get('attempt_number', '?')
                verif_attempt = attempt.get('verification', {})
                success = verif_attempt.get('success', False)
                print(f"  Attempt {attempt_num}: {'SUCCESS' if success else 'FAILED'}")
                if not success and verif_attempt.get('failure_analysis'):
                    failure = verif_attempt['failure_analysis']
                    if failure.get('failed_steps'):
                        print(f"    Failed steps: {len(failure['failed_steps'])}")
                        for failed_step in failure['failed_steps'][:3]:  # Show first 3
                            step_name = failed_step.get('step', 'unknown')
                            error = failed_step.get('error', '')[:100]
                            print(f"      - {step_name}: {error}")

        # Show file contents summary if goal asks for content or if any files were read
        if wants_content and file_contents:
            print(f"\n[FILE CONTENTS SUMMARY]")
            for file_path, content in file_contents.items():
                if content:
                    print(f"\n  {file_path}:")
                    print("  " + "-" * 68)
                    # Show full content for key files or small files, truncated for large ones
                    lines = content.split('\n')
                    if len(lines) > 50:
                        print("  (Showing first 25 and last 25 lines)")
                        for line in lines[:25]:
                            print(f"  {line}")
                        print("  ... (truncated) ...")
                        for line in lines[-25:]:
                            print(f"  {line}")
                    else:
                        for line in lines:
                            print(f"  {line}")
                    print("  " + "-" * 68)
                else:
                    print(f"\n  {file_path}: (empty or could not be read)")

        print("\n" + "="*70)
    
    elif args.cmd == "ssh":
        if args.ssh_cmd == "test":
            # Parse host
            host_parts = args.host.split('@')
            if len(host_parts) == 2:
                username, host_port = host_parts
            else:
                username = "root"
                host_port = host_parts[0]
            
            host_port_parts = host_port.split(':')
            host = host_port_parts[0]
            port = int(host_port_parts[1]) if len(host_port_parts) > 1 else args.port
            
            ssh_config = SSHConfig(
                host=host,
                port=port,
                username=username,
                key_file=args.key,
                password=args.password,
                timeout=config.SSH_DEFAULT_TIMEOUT,
            )
            
            manager = get_ssh_manager()
            if manager.test_connection(config=ssh_config):
                print(f"✓ SSH connection successful: {username}@{host}:{port}")
            else:
                print(f"✗ SSH connection failed: {username}@{host}:{port}", file=sys.stderr)
                sys.exit(1)
        
        elif args.ssh_cmd == "exec":
            # Parse host
            host_parts = args.host.split('@')
            if len(host_parts) == 2:
                username, host_port = host_parts
            else:
                username = "root"
                host_port = host_parts[0]
            
            host_port_parts = host_port.split(':')
            host = host_port_parts[0]
            port = int(host_port_parts[1]) if len(host_port_parts) > 1 else args.port
            
            ssh_config = SSHConfig(
                host=host,
                port=port,
                username=username,
                key_file=args.key,
                password=args.password,
                timeout=config.SSH_DEFAULT_TIMEOUT,
            )
            
            manager = get_ssh_manager()
            rc, stdout, stderr = manager.execute(args.cmd, config=ssh_config)
            print(stdout, end='')
            if stderr:
                print(stderr, file=sys.stderr, end='')
            sys.exit(rc)
        
        elif args.ssh_cmd == "stats":
            manager = get_ssh_manager()
            stats = manager.get_stats()
            if stats:
                print("SSH Connection Pool Statistics:")
                print("=" * 60)
                for pool_key, stat in stats.items():
                    print(f"\n{pool_key}:")
                    print(f"  Pooled connections: {stat['pooled']}")
                    print(f"  Active connections: {stat['active']}")
                    print(f"  Total connections: {stat['total']}")
            else:
                print("No active SSH connections.")

    else:
        ap.print_help()

