"""
File operations and configuration helpers
"""

import base64
import difflib
import os
import re
import shlex
import time
from typing import Tuple

from .docker_utils import docker_exec


def read_file(path: str) -> str:
    """Read a file from inside the container."""
    rc, out, _ = docker_exec(f"test -f {shlex.quote(path)} && cat {shlex.quote(path)} || true")
    return out if rc in (0, 1) else ""


def write_file_atomic(path: str, content: str):
    """Atomically write a file to the container with backup."""
    b64 = base64.b64encode(content.encode()).decode()
    dirn = os.path.dirname(path) or "/"
    ts = int(time.time())
    docker_exec(f"mkdir -p {shlex.quote(dirn)}")
    docker_exec(f"test -f {shlex.quote(path)} && cp {shlex.quote(path)} {shlex.quote(path)}.bak.{ts} || true")
    docker_exec(f"echo {shlex.quote(b64)} | base64 -d > /tmp/.nomanai.tmp && mv /tmp/.nomanai.tmp {shlex.quote(path)}")


def unified_diff_str(old: str, new: str, path: str) -> str:
    """Generate a unified diff string."""
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"{path} (old)", tofile=f"{path} (new)", lineterm=""
    ))


def set_config_line(current: str, key: str, value: str) -> Tuple[str, bool]:
    """
    Ensure a single 'key value' line exists in a config file.
    Replace any existing setting or commented variant.
    Returns (new_content, changed).
    """
    lines, found, out = current.splitlines(), False, []
    pat = re.compile(rf"^\s*#?\s*{re.escape(key)}\b", re.I)
    for line in lines:
        if pat.match(line):
            out.append(f"{key} {value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key} {value}")
    new = "\n".join(out) + ("\n" if not (out and out[-1].endswith("\n")) else "")
    changed = (new != (current if current.endswith("\n") else (current + ("\n" if current else ""))))
    return new, changed


def verify_config_line(content: str, key: str, value: str) -> bool:
    """Verify that a config line exists with the expected key and value."""
    return bool(re.search(rf"^\s*{re.escape(key)}\s+{re.escape(value)}\b", content, re.M))

