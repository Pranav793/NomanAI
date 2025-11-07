"""
Tool implementations for agent use
"""

import re
import shlex
from typing import List

from . import config
from .docker_utils import docker_exec
from .file_ops import read_file, set_config_line, write_file_atomic
from .remote_exec import get_executor

# Export all tools for easy access
__all__ = [
    "tool_read_file",
    "tool_write_file",
    "tool_run_safe",
    "tool_restart_service",
    "tool_install_package",
    "tool_remove_package",
    "tool_update_system",
    "tool_list_packages",
    "tool_search_packages",
    "tool_check_service_status",
    "tool_list_services",
    "tool_verify_regex",
    "tool_set_config_kv",
    "tool_create_directory",
    "tool_change_permissions",
    "tool_change_ownership",
    "tool_run_command",
    "dispatch_tool",
    "TOOLS_FOR_CHAT",
    "TOOLS_FOR_RESPONSES",
]


# Safety: allow-only specific run() commands (expanded for real-world operations)
ALLOWED_CMD_PATTERNS = [
    r"^systemctl\s+(reload|restart|stop|start|status|enable|disable|list-units|is-active|is-enabled|list-unit-files)\s+.*$",
    r"^service\s+[a-zA-Z0-9_.-]+\s+(reload|restart|stop|start|status)$",
    r"^update-rc\.d\s+[a-zA-Z0-9_.-]+\s+(enable|disable).*$",
    r"^chkconfig\s+[a-zA-Z0-9_.-]+\s+(on|off).*$",
    r"^nohup\s+.*$",
    r"^grep\s+-[a-zA-Z]*[nE]?\s+.+$",
    r"^sed\s+-[a-zA-Z]*[in]?\s+'.+'\s+[a-zA-Z0-9._/\-]+$",
    r"^cat\s+/[a-zA-Z0-9._/\-]+$",
    r"^ls\s+-[a-zA-Z]*\s*[a-zA-Z0-9._/\-]*$",
    r"^test\s+-[a-zA-Z]+\s+[a-zA-Z0-9._/\-]+$",
    r"^apt-get\s+(update|install|remove|purge|upgrade|autoremove)\s+.*$",
    r"^apt\s+(update|install|remove|purge|upgrade|autoremove|search|list|cache)\s+.*$",
    r"^apt-cache\s+(search|show|policy)\s+.*$",
    r"^dpkg\s+-[a-zA-Z]+\s+.*$",
    r"^dpkg\s+-l\s*.*$",
    r"^ps\s+aux?$",
    r"^pgrep\s+-f\s+.*$",
    r"^netstat\s+-[a-zA-Z]*[tulpn]*$",
    r"^ss\s+-[a-zA-Z]*[tulpn]*$",
    r"^which\s+[a-zA-Z0-9_.-]+$",
    r"^command\s+-v\s+[a-zA-Z0-9_.-]+$",
    r"^mkdir\s+-[a-zA-Z]*[p]?\s+.*$",
    r"^chmod\s+[0-9a-zA-Z+=-]+\s+/[a-zA-Z0-9._/\-]+$",
    r"^chown\s+[a-zA-Z0-9_.-]+(:[a-zA-Z0-9_.-]+)?\s+/[a-zA-Z0-9._/\-]+$",
    r"^find\s+/[a-zA-Z0-9._/\-]+\s+.*$",
    r"^sleep\s+[0-9]+$",
    r"^openssl\s+.*$",
    r"^ssh-keygen\s+.*$",
    r"^cd\s+[a-zA-Z0-9._/\-]+$",
    r"^pwd$",
    r"^touch\s+[a-zA-Z0-9._/\-]+$",
]


def cmd_allowed(cmd: str) -> bool:
    """Check if a command is allowed by the security policy."""
    cmd_clean = re.sub(r'\s+', ' ', cmd.strip())
    return any(re.match(p, cmd_clean) for p in ALLOWED_CMD_PATTERNS)


def has_systemd() -> bool:
    """Check if systemd is available on the remote target."""
    executor = get_executor()
    rc, out, _ = executor.execute("command -v systemctl >/dev/null 2>&1 && systemctl --version >/dev/null 2>&1 && echo yes || echo no")
    return out.strip() == "yes"


def get_service_command(service_name: str) -> str:
    """Get the appropriate service command path."""
    executor = get_executor()
    systemd_available = has_systemd()
    
    # Check for systemd service first (if systemd is available)
    if systemd_available:
        rc1, _, _ = executor.execute(f"systemctl list-unit-files {shlex.quote(service_name)}.service >/dev/null 2>&1")
        if rc1 == 0:
            return "systemd"
    
    # Check for init.d script
    rc2, _, _ = executor.execute(f"test -f /etc/init.d/{shlex.quote(service_name)}")
    if rc2 == 0:
        return f"/etc/init.d/{service_name}"
    
    # Check for service command availability
    rc3, _, _ = executor.execute("command -v service >/dev/null 2>&1")
    if rc3 == 0:
        return "service"
    
    return None


# Tool implementations
def tool_read_file(path: str) -> dict:
    """Read a file from the container. Supports both absolute and relative paths."""
    try:
        original_path = path
        # Expand ~ to /root (container home directory)
        if path.startswith('~/'):
            path = path.replace('~/', '/root/', 1)
        elif path == '~':
            path = '/root'
        # If path is relative, try multiple locations
        elif not path.startswith('/'):
            # Try reading from common locations: /root/, /, and current working directory
            # Try /root/ first (most common)
            content = read_file(f"/root/{path}")
            if content:
                return {"ok": True, "content": content}
            # Try / (root filesystem)
            content = read_file(f"/{path}")
            if content:
                return {"ok": True, "content": content}
            # Try current working directory (relative path)
            content = read_file(path)
            if content:
                return {"ok": True, "content": content}
            # If all failed, default to /root/ for error message
            path = f"/root/{path}"
            return {"ok": False, "stderr": f"File not found in /root/, /, or current directory: {original_path}"}
        
        # Absolute path - read directly
        content = read_file(path)
        return {"ok": True, "content": content}
    except Exception as e:
        return {"ok": False, "stderr": f"Error reading file {path}: {str(e)}"}


def tool_write_file(path: str, content: str) -> dict:
    """Write a file to the container atomically. Supports both absolute and relative paths."""
    try:
        # Expand ~ to /root (container home directory)
        if path.startswith('~/'):
            path = path.replace('~/', '/root/', 1)
        elif path == '~':
            path = '/root'
        # If path is relative, make it absolute from /root
        elif not path.startswith('/'):
            path = f"/root/{path}"
        write_file_atomic(path, content)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "stderr": f"Error writing file {path}: {str(e)}"}


def tool_run_safe(cmd: str) -> dict:
    """Run a whitelisted shell command on the remote target."""
    # Handle multiple commands separated by && or ;
    cmd_parts = cmd.split('&&')
    if len(cmd_parts) == 1:
        cmd_parts = cmd.split(';')
    
    # Check each command part
    for part in cmd_parts:
        part = part.strip()
        if part and not cmd_allowed(part):
            return {"ok": False, "stderr": f"command not allowed by policy: {part}"}
    
    # Execute the full command using the current executor
    executor = get_executor()
    rc, out, err = executor.execute(cmd)
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}


def tool_restart_service(name: str, action: str = "restart") -> dict:
    """
    Manage a service. Works with systemd, init.d, or service command.
    action can be 'reload', 'restart', 'stop', 'start', 'enable', 'disable'.
    """
    if action not in ["reload", "restart", "stop", "start", "enable", "disable"]:
        return {"ok": False, "stderr": f"Invalid action: {action}. Use reload, restart, stop, start, enable, or disable."}
    
    systemd_available = has_systemd()
    service_cmd = get_service_command(name)
    
    executor = get_executor()
    
    # For systemd environments
    if systemd_available and service_cmd == "systemd":
        if action == "enable":
            rc1, out1, err1 = executor.execute(f"systemctl enable {shlex.quote(name)}.service 2>&1 || true")
            rc2, out2, err2 = executor.execute(f"systemctl start {shlex.quote(name)}.service 2>&1 || true")
            return {"ok": rc2 == 0, "rc": rc2, "stdout": out1 + out2, "stderr": err1 + err2}
        elif action == "disable":
            rc1, out1, err1 = executor.execute(f"systemctl stop {shlex.quote(name)}.service 2>&1 || true")
            rc2, out2, err2 = executor.execute(f"systemctl disable {shlex.quote(name)}.service 2>&1 || true")
            return {"ok": True, "rc": 0, "stdout": out1 + out2, "stderr": err1 + err2}
        else:
            rc, out, err = executor.execute(f"systemctl {action} {shlex.quote(name)}.service 2>&1")
            if rc != 0 and action == "restart":
                executor.execute(f"systemctl stop {shlex.quote(name)}.service 2>&1 || true")
                rc, out, err = executor.execute(f"systemctl start {shlex.quote(name)}.service 2>&1")
            return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}
    
    # Fallback for non-systemd environments (init.d or service command)
    elif service_cmd:
        if action == "enable":
            # Use update-rc.d or chkconfig to enable service at boot
            rc1, out1, err1 = executor.execute(f"update-rc.d {shlex.quote(name)} enable 2>&1 || chkconfig {shlex.quote(name)} on 2>&1 || true")
            # Try to start the service
            if service_cmd == "service":
                rc2, out2, err2 = executor.execute(f"service {shlex.quote(name)} start 2>&1 || /etc/init.d/{shlex.quote(name)} start 2>&1 || true")
            else:
                rc2, out2, err2 = executor.execute(f"{service_cmd} start 2>&1 || true")
            return {"ok": rc2 == 0, "rc": rc2, "stdout": out1 + out2, "stderr": err1 + err2, "note": "Service enabled (non-systemd)"}
        elif action == "disable":
            rc1, out1, err1 = executor.execute(f"service {shlex.quote(name)} stop 2>&1 || /etc/init.d/{shlex.quote(name)} stop 2>&1 || true")
            rc2, out2, err2 = executor.execute(f"update-rc.d {shlex.quote(name)} disable 2>&1 || chkconfig {shlex.quote(name)} off 2>&1 || true")
            return {"ok": True, "rc": 0, "stdout": out1 + out2, "stderr": err1 + err2, "note": "Service disabled (non-systemd)"}
        else:
            # Use service command or init.d script
            if service_cmd == "service":
                cmd = f"service {shlex.quote(name)} {action} 2>&1 || /etc/init.d/{shlex.quote(name)} {action} 2>&1"
            else:
                cmd = f"{service_cmd} {action} 2>&1"
            rc, out, err = executor.execute(cmd)
            if rc != 0 and action == "restart":
                # Try stop then start
                executor.execute(f"service {shlex.quote(name)} stop 2>&1 || /etc/init.d/{shlex.quote(name)} stop 2>&1 || true")
                rc, out, err = executor.execute(f"service {shlex.quote(name)} start 2>&1 || /etc/init.d/{shlex.quote(name)} start 2>&1")
            return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err, "note": f"Used {service_cmd} (non-systemd)"}
    else:
        # Last resort: try to start service directly (for SSH, etc.)
        # In Docker containers without systemd, we start services as background processes
        if name in ["ssh", "sshd"]:
            if action in ["start", "restart", "enable"]:
                # For SSH, we need to ensure it's configured and can start
                # Check if sshd_config exists and is valid
                rc_check, _, _ = executor.execute(f"test -f /etc/ssh/sshd_config && /usr/sbin/sshd -t 2>&1")
                if rc_check != 0:
                    return {"ok": False, "rc": 1, "stdout": "", "stderr": "SSH configuration invalid. Please configure SSH first."}
                # Start SSH daemon in background (non-blocking)
                rc, out, err = executor.execute(f"nohup /usr/sbin/sshd -D >/tmp/sshd.log 2>&1 & echo $!")
                if rc == 0:
                    # Wait a moment and check if it's running
                    executor.execute("sleep 1")
                    rc_check, out_check, _ = executor.execute("ps aux | grep -E '[s]shd' | grep -v grep || echo 'not_running'")
                    if "sshd" in out_check:
                        return {"ok": True, "rc": 0, "stdout": "SSH daemon started in background", "stderr": err, "note": "Started SSH directly (Docker container without systemd)"}
                return {"ok": False, "rc": rc, "stdout": out, "stderr": err, "note": "Failed to start SSH daemon"}
        
        # For other services, try to find and start them
        # This is a basic fallback - for production use, consider using a systemd-enabled container
        return {
            "ok": False,
            "rc": 1,
            "stdout": "",
            "stderr": f"Could not find service management method for {name}. Tried systemd, init.d, and service command.",
            "note": "For full service management, consider using a systemd-enabled Docker container or running on a real Linux system."
        }


def tool_install_package(package: str) -> dict:
    """Install a package using apt. Can install multiple packages separated by spaces."""
    # Split package string in case multiple packages are provided
    packages = shlex.split(package)
    packages_quoted = " ".join(shlex.quote(p) for p in packages)
    # Update package lists first, then install (non-interactive)
    rc1, out1, err1 = docker_exec(f"DEBIAN_FRONTEND=noninteractive apt-get update -y 2>&1")
    if rc1 != 0 and "E:" in err1:
        # Real error during update
        return {"ok": False, "rc": rc1, "stdout": out1, "stderr": err1}
    # Install packages (non-interactive, auto-yes)
    rc2, out2, err2 = docker_exec(f"DEBIAN_FRONTEND=noninteractive apt-get install -y {packages_quoted} 2>&1")
    # Check if installation succeeded (warnings are OK)
    success = rc2 == 0 or ("W:" in err2 and "E:" not in err2)
    return {"ok": success, "rc": rc2, "stdout": out1 + out2, "stderr": err1 + err2}


def tool_remove_package(package: str) -> dict:
    """Remove a package using apt. Can remove multiple packages separated by spaces."""
    packages = shlex.split(package)
    packages_quoted = " ".join(shlex.quote(p) for p in packages)
    rc, out, err = docker_exec(f"apt-get remove -y {packages_quoted}")
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}


def tool_update_system() -> dict:
    """Update the package list and upgrade all installed packages."""
    # Update package lists (non-interactive, auto-yes)
    rc1, out1, err1 = docker_exec("DEBIAN_FRONTEND=noninteractive apt-get update -y 2>&1")
    if rc1 != 0:
        # Still continue even if update has warnings
        if "W:" in err1 or "warning" in err1.lower():
            # Warnings are OK, continue
            pass
        else:
            return {"ok": False, "rc": rc1, "stdout": out1, "stderr": err1}
    # Upgrade packages (non-interactive)
    rc2, out2, err2 = docker_exec("DEBIAN_FRONTEND=noninteractive apt-get upgrade -y 2>&1")
    # Return success if upgrade completed (even with warnings)
    success = rc2 == 0 or ("W:" in err2 and "E:" not in err2)
    return {"ok": success, "rc": rc2, "stdout": out1 + out2, "stderr": err1 + err2}


def tool_list_packages(pattern: str = "") -> dict:
    """List installed packages. Optionally filter by pattern."""
    if pattern:
        cmd = f"dpkg -l | grep -i {shlex.quote(pattern)} || true"
    else:
        cmd = "dpkg -l"
    rc, out, err = docker_exec(cmd)
    return {"ok": True, "rc": rc, "stdout": out, "stderr": err}


def tool_search_packages(query: str) -> dict:
    """Search for available packages matching the query."""
    # Update package cache first to ensure we have latest package info
    docker_exec("apt-get update >/dev/null 2>&1 || true")
    rc, out, err = docker_exec(f"apt-cache search {shlex.quote(query)} 2>&1")
    # Even if search returns no results (rc != 0), return what we found
    if rc != 0 and "E:" not in err and "error" not in err.lower():
        # Might just be no results found, which is OK
        return {"ok": True, "rc": 0, "stdout": out, "stderr": err}
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}


def tool_check_service_status(name: str) -> dict:
    """Check if a service is running and enabled. Returns detailed status information."""
    systemd_available = has_systemd()
    
    if systemd_available:
        rc_active, out_active, _ = docker_exec(f"systemctl is-active {shlex.quote(name)}.service 2>/dev/null || echo inactive")
        rc_enabled, out_enabled, _ = docker_exec(f"systemctl is-enabled {shlex.quote(name)}.service 2>/dev/null || echo disabled")
        rc_status, out_status, err_status = docker_exec(f"systemctl status {shlex.quote(name)}.service --no-pager -l 2>&1 || true")
        
        is_active = out_active.strip() == "active"
        is_enabled = out_enabled.strip() in ["enabled", "enabled-runtime"]
        
        return {
            "ok": True,
            "active": is_active,
            "enabled": is_enabled,
            "status": out_active.strip(),
            "enabled_status": out_enabled.strip(),
            "detailed_status": out_status.strip(),
            "systemd": True
        }
    else:
        # Non-systemd: check if process is running and if service script exists
        # Check if process is running
        if name in ["ssh", "sshd"]:
            rc_proc, out_proc, _ = docker_exec(f"ps aux | grep -E '[s]shd' || echo 'not_running'")
            is_active = "sshd" in out_proc or "ssh" in out_proc
        else:
            # Generic process check
            rc_proc, out_proc, _ = docker_exec(f"pgrep -f {shlex.quote(name)} || echo 'not_running'")
            is_active = out_proc.strip() != "not_running" and out_proc.strip() != ""
        
        # Check if service script exists (for enable/disable status)
        rc_init, _, _ = docker_exec(f"test -f /etc/init.d/{shlex.quote(name)}")
        rc_enabled, out_enabled, _ = docker_exec(f"ls -la /etc/rc*.d/*{shlex.quote(name)} 2>/dev/null | grep -E 'S[0-9]' || echo 'disabled'")
        is_enabled = "disabled" not in out_enabled and rc_enabled == 0
        
        # Try to get service status using service command
        rc_status, out_status, err_status = docker_exec(f"service {shlex.quote(name)} status 2>&1 || /etc/init.d/{shlex.quote(name)} status 2>&1 || echo 'status_unknown'")
        
        return {
            "ok": True,
            "active": is_active,
            "enabled": is_enabled,
            "status": "active" if is_active else "inactive",
            "enabled_status": "enabled" if is_enabled else "disabled",
            "detailed_status": out_status.strip(),
            "systemd": False,
            "note": "Checked using process and init.d scripts (non-systemd environment)"
        }


def tool_list_services(pattern: str = "") -> dict:
    """List system services. Optionally filter by pattern."""
    systemd_available = has_systemd()
    
    if systemd_available:
        if pattern:
            cmd = f"systemctl list-units --type=service --all --no-pager | grep -i {shlex.quote(pattern)} || true"
        else:
            cmd = "systemctl list-units --type=service --all --no-pager"
        rc, out, err = docker_exec(cmd)
        return {"ok": True, "rc": rc, "stdout": out, "stderr": err, "systemd": True}
    else:
        # Fallback: list init.d scripts
        if pattern:
            cmd = f"ls /etc/init.d/ | grep -i {shlex.quote(pattern)} || echo ''"
        else:
            cmd = "ls /etc/init.d/ || echo ''"
        rc, out, err = docker_exec(cmd)
        return {"ok": True, "rc": rc, "stdout": out, "stderr": err, "systemd": False, "note": "Listed init.d services (non-systemd)"}


def tool_verify_regex(path: str, regex: str) -> dict:
    """Verify that file content matches a regex pattern."""
    content = read_file(path)
    ok = bool(re.search(regex, content, re.M))
    return {"ok": ok}


def tool_set_config_kv(path: str, key: str, value: str) -> dict:
    """Set/replace a single 'key value' line in a config file (idempotent)."""
    # Block dangerous flips unless user opted in
    if not config.ALLOW_INSECURE and path == "/etc/ssh/sshd_config":
        if key in ("PermitRootLogin", "PasswordAuthentication") and value.lower() == "yes":
            return {"ok": False, "stderr": "blocked by policy: insecure sshd setting; rerun with --allow-insecure"}
    current = read_file(path)
    new, _ = set_config_line(current, key, value)
    write_file_atomic(path, new)
    return {"ok": True}


def tool_create_directory(path: str, mode: str = "755") -> dict:
    """Create a directory (and parent directories if needed)."""
    rc, out, err = docker_exec(f"mkdir -p -m {shlex.quote(mode)} {shlex.quote(path)}")
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}


def tool_change_permissions(path: str, mode: str) -> dict:
    """Change file or directory permissions using chmod."""
    rc, out, err = docker_exec(f"chmod {shlex.quote(mode)} {shlex.quote(path)}")
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}


def tool_change_ownership(path: str, user: str, group: str = "") -> dict:
    """Change file or directory ownership using chown."""
    owner = f"{shlex.quote(user)}:{shlex.quote(group)}" if group else shlex.quote(user)
    rc, out, err = docker_exec(f"chown {owner} {shlex.quote(path)}")
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}


def tool_run_command(cmd: str) -> dict:
    """Run a system command. This is a more flexible version of run_safe with expanded allowed commands."""
    # This tool uses the same security checks as run_safe
    return tool_run_safe(cmd)


# Tool schemas for OpenAI API
TOOLS_FOR_RESPONSES = [
    {"type": "function", "name": "read_file", "description": "Read a text file inside the container.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"type": "function", "name": "write_file", "description": "Atomically replace a text file inside the container.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
      "required": ["path", "content"]}},
    {"type": "function", "name": "run_safe", "description": "Run a whitelisted shell command inside the container.",
     "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}},
    {"type": "function", "name": "restart_service", "description": "Reload a service (idempotent).",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"type": "function", "name": "verify_regex", "description": "Assert that file content matches a regex.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "regex": {"type": "string"}},
      "required": ["path", "regex"]}},
    {"type": "function", "name": "set_config_kv",
     "description": "Set/replace a single 'key value' line in a config file (idempotent).",
     "parameters": {"type": "object",
      "properties": {"path": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"}},
      "required": ["path", "key", "value"]}},
]

TOOLS_FOR_CHAT = [
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a text file inside the container.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Atomically replace a text file inside the container.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_safe", "description": "Run a whitelisted shell command inside the container (grep, systemctl, apt, etc.).",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "restart_service",
        "description": "Manage a systemd service. Actions: 'start', 'stop', 'restart', 'reload', 'enable' (enable and start), 'disable' (stop and disable).",
        "parameters": {"type": "object",
         "properties": {"name": {"type": "string"},
          "action": {"type": "string", "enum": ["reload", "restart", "stop", "start", "enable", "disable"], "default": "restart"}},
         "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "verify_regex", "description": "Assert that file content matches a regex pattern.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "regex": {"type": "string"}},
         "required": ["path", "regex"]}}},
    {"type": "function", "function": {
        "name": "set_config_kv",
        "description": "Set/replace a single 'key value' line in a config file (idempotent).",
        "parameters": {"type": "object",
         "properties": {"path": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"}},
         "required": ["path", "key", "value"]}}},
    {"type": "function", "function": {
        "name": "install_package", "description": "Install one or more packages using apt. Can specify multiple packages separated by spaces.",
        "parameters": {"type": "object", "properties": {"package": {"type": "string"}}, "required": ["package"]}}},
    {"type": "function", "function": {
        "name": "remove_package", "description": "Remove one or more packages using apt. Can specify multiple packages separated by spaces.",
        "parameters": {"type": "object", "properties": {"package": {"type": "string"}}, "required": ["package"]}}},
    {"type": "function", "function": {
        "name": "update_system", "description": "Update package lists and upgrade all installed packages to latest versions.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "list_packages", "description": "List installed packages. Optionally filter by pattern.",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {
        "name": "search_packages", "description": "Search for available packages matching a query.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "check_service_status", "description": "Check if a service is running and enabled. Returns detailed status information.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "list_services", "description": "List system services. Optionally filter by pattern.",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {
        "name": "create_directory", "description": "Create a directory (and parent directories if needed).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "mode": {"type": "string", "default": "755"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "change_permissions", "description": "Change file or directory permissions using chmod (e.g., '755', '644', 'u+x').",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "mode": {"type": "string"}}, "required": ["path", "mode"]}}},
    {"type": "function", "function": {
        "name": "change_ownership", "description": "Change file or directory ownership using chown.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "user": {"type": "string"}, "group": {"type": "string", "default": ""}}, "required": ["path", "user"]}}},
]


def dispatch_tool(name: str, args: dict) -> dict:
    """Dispatch a tool call by name. Handles parameter name variations."""
    try:
        # Normalize parameter names (handle common variations)
        normalized_args = args.copy()
        
        # Handle parameter name variations (comprehensive normalization)
        if "service_name" in normalized_args and "name" not in normalized_args:
            normalized_args["name"] = normalized_args.pop("service_name")
        if "file_path" in normalized_args and "path" not in normalized_args:
            normalized_args["path"] = normalized_args.pop("file_path")
        
        # Package parameter variations
        if "package_names" in normalized_args and "package" not in normalized_args:
            pkg_list = normalized_args.pop("package_names")
            if isinstance(pkg_list, list):
                normalized_args["package"] = " ".join(pkg_list)
            else:
                normalized_args["package"] = pkg_list
        elif "packages" in normalized_args and "package" not in normalized_args:
            pkg_list = normalized_args.pop("packages")
            if isinstance(pkg_list, list):
                normalized_args["package"] = " ".join(pkg_list)
            else:
                normalized_args["package"] = pkg_list
        elif "package_name" in normalized_args:
            # For search_packages, package_name should be "query"
            # For install/remove, it should be "package"
            # We'll handle this based on the tool name later
            pass
        
        # Command parameter variations
        if "command" in normalized_args and "cmd" not in normalized_args:
            normalized_args["cmd"] = normalized_args.pop("command")
        
        # Permissions/mode variations
        if "permissions" in normalized_args and "mode" not in normalized_args:
            normalized_args["mode"] = normalized_args.pop("permissions")
        
        # Regex variations
        if "regex_pattern" in normalized_args and "regex" not in normalized_args:
            normalized_args["regex"] = normalized_args.pop("regex_pattern")
        
        # Special handling for search_packages - package_name becomes query
        if name == "search_packages" and "package_name" in normalized_args and "query" not in normalized_args:
            normalized_args["query"] = normalized_args.pop("package_name")
        elif "package_name" in normalized_args and "package" not in normalized_args:
            normalized_args["package"] = normalized_args.pop("package_name")
        
        if name == "read_file":
            if "path" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameter: path"}
            return tool_read_file(**normalized_args)
        if name == "write_file":
            if "path" not in normalized_args or "content" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameters: path, content"}
            return tool_write_file(**normalized_args)
        if name == "run_safe":
            if "cmd" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameter: cmd"}
            return tool_run_safe(**normalized_args)
        if name == "restart_service":
            if "name" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameter: name"}
            return tool_restart_service(**normalized_args)
        if name == "verify_regex":
            if "path" not in normalized_args or "regex" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameters: path, regex"}
            return tool_verify_regex(**normalized_args)
        if name == "set_config_kv":
            if "path" not in normalized_args or "key" not in normalized_args or "value" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameters: path, key, value"}
            return tool_set_config_kv(**normalized_args)
        if name == "install_package":
            if "package" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameter: package"}
            return tool_install_package(**normalized_args)
        if name == "remove_package":
            if "package" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameter: package"}
            return tool_remove_package(**normalized_args)
        if name == "update_system":
            return tool_update_system(**normalized_args)
        if name == "list_packages":
            return tool_list_packages(**normalized_args)
        if name == "search_packages":
            if "query" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameter: query"}
            return tool_search_packages(**normalized_args)
        if name == "check_service_status":
            if "name" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameter: name"}
            return tool_check_service_status(**normalized_args)
        if name == "list_services":
            return tool_list_services(**normalized_args)
        if name == "create_directory":
            if "path" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameter: path"}
            return tool_create_directory(**normalized_args)
        if name == "change_permissions":
            if "path" not in normalized_args or "mode" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameters: path, mode"}
            return tool_change_permissions(**normalized_args)
        if name == "change_ownership":
            if "path" not in normalized_args or "user" not in normalized_args:
                return {"ok": False, "stderr": "missing required parameters: path, user"}
            return tool_change_ownership(**normalized_args)
        return {"ok": False, "stderr": f"unknown tool {name}"}
    except Exception as e:
        return {"ok": False, "stderr": f"tool execution error: {str(e)}"}

