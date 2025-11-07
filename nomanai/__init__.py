"""
NomanAI - AI-powered security remediation system
"""

__version__ = "0.1.0"
__author__ = "NomanAI Team"

from .config import APP_NAME, CONTAINER, IMAGE, TARGET_FILE
from .docker_utils import ensure_up, down, docker_exec
from .file_ops import read_file, write_file_atomic, set_config_line, verify_config_line
from .fixes import FIXES, resolve_fixes, plan_fixes, apply_fixes, verify_fixes
from .tools import (
    tool_read_file, tool_write_file, tool_run_safe, tool_restart_service,
    tool_install_package, tool_check_service_status, tool_verify_regex,
    tool_set_config_kv, TOOLS_FOR_CHAT, TOOLS_FOR_RESPONSES
)
from .agents import agent
from .multi_agent import multi_agent_system

__all__ = [
    "APP_NAME",
    "CONTAINER",
    "IMAGE",
    "TARGET_FILE",
    "ensure_up",
    "down",
    "docker_exec",
    "read_file",
    "write_file_atomic",
    "set_config_line",
    "verify_config_line",
    "FIXES",
    "resolve_fixes",
    "plan_fixes",
    "apply_fixes",
    "verify_fixes",
    "tool_read_file",
    "tool_write_file",
    "tool_run_safe",
    "tool_restart_service",
    "tool_install_package",
    "tool_check_service_status",
    "tool_verify_regex",
    "tool_set_config_kv",
    "TOOLS_FOR_CHAT",
    "TOOLS_FOR_RESPONSES",
    "agent",
    "multi_agent_system",
]

