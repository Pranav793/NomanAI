"""
Fix catalog and fix-related operations
"""

import sys
from typing import List, Tuple

from .config import TARGET_FILE
from .docker_utils import docker_exec, ensure_up
from .file_ops import read_file, set_config_line, unified_diff_str, verify_config_line, write_file_atomic


# Fix catalog
FIXES = {
    "ssh_disable_root": {
        "title": "Disable root SSH login",
        "key": "PermitRootLogin",
        "value": "no"
    },
    "ssh_disable_password_auth": {
        "title": "Disable SSH password authentication",
        "key": "PasswordAuthentication",
        "value": "no"
    },
}


def resolve_fixes(selected: List[str]) -> List[str]:
    """Resolve fix IDs from user selection."""
    if not selected:
        return ["ssh_disable_root"]
    if "all" in selected:
        return list(FIXES.keys())
    bad = [f for f in selected if f not in FIXES]
    if bad:
        print(f"Unknown fix id(s): {', '.join(bad)}. Known: {', '.join(FIXES.keys())}", file=sys.stderr)
        sys.exit(1)
    return selected


def plan_fixes(fix_ids: List[str]) -> List[str]:
    """Generate a plan for applying fixes."""
    steps = []
    for fid in fix_ids:
        key, value = FIXES[fid]["key"], FIXES[fid]["value"]
        steps += [
            f"[{fid}] {FIXES[fid]['title']}",
            f"  • Read {TARGET_FILE}",
            f"  • Ensure '{key} {value}' exists (replace if present)",
            f"  • Write back to {TARGET_FILE} with backup"
        ]
    steps.append("  • Reload sshd (best-effort)")
    return steps


def apply_fixes(fix_ids: List[str]) -> Tuple[bool, str]:
    """Apply the specified fixes."""
    original = read_file(TARGET_FILE)
    content = original
    changed_any = False
    for fid in fix_ids:
        key, value = FIXES[fid]["key"], FIXES[fid]["value"]
        content, changed = set_config_line(content, key, value)
        changed_any = changed_any or changed
    if not changed_any:
        return False, ""
    diff = unified_diff_str(original, content, TARGET_FILE)
    write_file_atomic(TARGET_FILE, content)
    docker_exec("systemctl reload ssh || service ssh reload || true || /bin/true")
    return True, diff


def verify_fixes(fix_ids: List[str]) -> Tuple[bool, List[str]]:
    """Verify that the specified fixes are applied."""
    content = read_file(TARGET_FILE)
    failed = []
    for fid in fix_ids:
        k, v = FIXES[fid]["key"], FIXES[fid]["value"]
        if not verify_config_line(content, k, v):
            failed.append(fid)
    return (len(failed) == 0), failed

