#!/usr/bin/env python3
# nomanai.py — run config fixes safely inside a Docker container (no host changes)
import argparse, base64, difflib, os, subprocess, sys, time, shlex, re
from typing import Tuple, List

APP_NAME    = "NomanAI"
CONTAINER   = "nomanai-sbx"
IMAGE       = "ubuntu:24.04"
TARGET_FILE = "/etc/ssh/sshd_config"

# ---------------- host shell helpers ----------------
def sh(cmd: str) -> Tuple[int,str,str]:
    p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    return p.returncode, p.stdout, p.stderr

def die(msg: str, rc: int=1):
    print(msg, file=sys.stderr); sys.exit(rc)

# ---------------- docker helpers (no recursion) ----------------
def docker(args: str) -> Tuple[int,str,str]:
    return sh(f"docker {args}")

def docker_exists() -> bool:
    rc, out, _ = docker(f"ps -a --filter name={CONTAINER} --format '{{{{.ID}}}}'")
    return rc == 0 and out.strip() != ""

def docker_running() -> bool:
    rc, out, _ = docker(f"ps --filter name={CONTAINER} --format '{{{{.ID}}}}'")
    return rc == 0 and out.strip() != ""

def ensure_up():
    rc, _, _ = sh("docker version --format '{{.Server.Version}}'")
    if rc != 0:
        die("Docker isn't available. Install & start Docker Desktop.")
    docker(f"pull {IMAGE}")
    if not docker_exists():
        rc, out, err = docker(f"run -d --name {CONTAINER} --hostname {CONTAINER} {IMAGE} sleep infinity")
        if rc != 0: die(f"Failed to start container: {err or out}")
    elif not docker_running():
        rc, out, err = docker(f"start {CONTAINER}")
        if rc != 0: die(f"Failed to start container: {err or out}")

def docker_exec(cmd: str) -> Tuple[int,str,str]:
    return docker(f"exec {CONTAINER} bash -lc {shlex.quote(cmd)}")

def down():
    docker(f"rm -f {CONTAINER}")

# ---------------- file ops inside container ----------------
def read_file(path: str) -> str:
    rc, out, _ = docker_exec(f"test -f {shlex.quote(path)} && cat {shlex.quote(path)} || true")
    return out if rc in (0,1) else ""

def write_file_atomic(path: str, content: str):
    b64 = base64.b64encode(content.encode()).decode()
    dirn = os.path.dirname(path) or "/"
    ts = int(time.time())
    docker_exec(f"mkdir -p {shlex.quote(dirn)}")
    docker_exec(f"test -f {shlex.quote(path)} && cp {shlex.quote(path)} {shlex.quote(path)}.bak.{ts} || true")
    docker_exec(f"echo {shlex.quote(b64)} | base64 -d > /tmp/.nomanai.tmp && mv /tmp/.nomanai.tmp {shlex.quote(path)}")

def unified_diff_str(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"{path} (old)", tofile=f"{path} (new)", lineterm=""
    ))

# ---------------- generic line-set helper ----------------
def set_config_line(current: str, key: str, value: str) -> Tuple[str,bool]:
    """Ensure a single 'key value' line exists; replace any existing setting or commented variant."""
    lines, found, out = current.splitlines(), False, []
    pat = re.compile(rf"^\s*#?\s*{re.escape(key)}\b", re.I)
    for line in lines:
        if pat.match(line):
            out.append(f"{key} {value}"); found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key} {value}")
    new = "\n".join(out) + ("\n" if not (out and out[-1].endswith("\n")) else "")
    changed = (new != (current if current.endswith("\n") else (current + ("\n" if current else ""))))
    return new, changed

def verify_config_line(content: str, key: str, value: str) -> bool:
    return bool(re.search(rf"^\s*{re.escape(key)}\s+{re.escape(value)}\b", content, re.M))

# ---------------- fixes registry ----------------
FIXES = {
    "ssh_disable_root": {
        "title": "Disable root SSH login",
        "key": "PermitRootLogin",
        "value": "no",
    },
    "ssh_disable_password_auth": {
        "title": "Disable SSH password authentication",
        "key": "PasswordAuthentication",
        "value": "no",
    },
}

def resolve_fixes(selected: List[str]) -> List[str]:
    if not selected or selected == ["ssh_disable_root"]:
        return ["ssh_disable_root"]
    if "all" in selected:
        return list(FIXES.keys())
    # validate
    bad = [f for f in selected if f not in FIXES]
    if bad:
        die(f"Unknown fix id(s): {', '.join(bad)}. Known: {', '.join(FIXES.keys())}")
    return selected

# ---------------- high-level ops ----------------
def plan_fixes(fix_ids: List[str]) -> List[str]:
    steps = []
    for fid in fix_ids:
        title = FIXES[fid]["title"]
        key, value = FIXES[fid]["key"], FIXES[fid]["value"]
        steps.extend([
            f"[{fid}] {title}",
            f"  • Read {TARGET_FILE}",
            f"  • Ensure '{key} {value}' exists (replace if present)",
            f"  • Write back to {TARGET_FILE} with backup",
        ])
    steps.append("  • Reload sshd (best-effort)")
    return steps

def apply_fixes(fix_ids: List[str]) -> Tuple[bool,str]:
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

def verify_fixes(fix_ids: List[str]) -> Tuple[bool,List[str]]:
    content = read_file(TARGET_FILE)
    failed = []
    for fid in fix_ids:
        key, value = FIXES[fid]["key"], FIXES[fid]["value"]
        if not verify_config_line(content, key, value):
            failed.append(fid)
    return (len(failed) == 0), failed

# ---------------- CLI commands ----------------
def cmd_up(_):
    ensure_up()
    print(f"{APP_NAME} container '{CONTAINER}' ready (image {IMAGE}).")

def cmd_down(_):
    down()
    print("Container removed.")

def cmd_exec(a):
    ensure_up()
    rc, out, err = docker_exec(a.cmd)
    print(out, end="")
    if rc != 0:
        print(err, file=sys.stderr)
    sys.exit(rc)

def cmd_plan(a):
    ensure_up()
    fix_ids = resolve_fixes(a.fix)
    print("Plan inside container:")
    for s in plan_fixes(fix_ids):
        print(s)

def cmd_apply(a):
    ensure_up()
    fix_ids = resolve_fixes(a.fix)
    changed, diff = apply_fixes(fix_ids)
    if not changed:
        print("No changes needed.")
        return
    print("Applied inside container. Unified diff:\n" + diff)

def cmd_verify(a):
    ensure_up()
    fix_ids = resolve_fixes(a.fix)
    ok, failed = verify_fixes(fix_ids)
    if ok:
        print("PASS: all selected fixes verified")
    else:
        titles = [FIXES[f]["title"] for f in failed]
        print("FAIL: these fixes did not verify → " + ", ".join(titles))

def main():
    ap = argparse.ArgumentParser(description=f"{APP_NAME} — safe containerized fixer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("up", help="create/start container").set_defaults(func=cmd_up)
    sub.add_parser("down", help="delete container").set_defaults(func=cmd_down)

    p_exec = sub.add_parser("exec", help="run a command in container")
    p_exec.add_argument("--cmd", required=True)
    p_exec.set_defaults(func=cmd_exec)

    def add_fix_arg(p):
        p.add_argument("--fix", action="append", default=None,
                       help=f"Fix id (repeatable). Known: {', '.join(list(FIXES.keys()) + ['all'])}. "
                            f"Default=ssh_disable_root")

    p_plan = sub.add_parser("plan", help="show plan")
    add_fix_arg(p_plan); p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="apply fix(es)")
    add_fix_arg(p_apply); p_apply.set_defaults(func=cmd_apply)

    p_verify = sub.add_parser("verify", help="verify fix(es)")
    add_fix_arg(p_verify); p_verify.set_defaults(func=cmd_verify)

    args = ap.parse_args(); args.func(args)

if __name__ == "__main__":
    main()
