"""
Docker container management utilities
"""

import shlex
import subprocess
import sys
from typing import Tuple

from .config import CONTAINER, IMAGE, USE_SYSTEMD_CONTAINER, SYSTEMD_IMAGE


def sh(cmd: str) -> Tuple[int, str, str]:
    """Run a shell command and return returncode, stdout, stderr."""
    p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    return p.returncode, p.stdout, p.stderr


def docker(args: str) -> Tuple[int, str, str]:
    """Run a docker command."""
    return sh(f"docker {args}")


def docker_exists() -> bool:
    """Check if the container exists."""
    rc, out, _ = docker(f"ps -a --filter name={CONTAINER} --format '{{{{.ID}}}}'")
    return rc == 0 and out.strip() != ""


def docker_running() -> bool:
    """Check if the container is running."""
    rc, out, _ = docker(f"ps --filter name={CONTAINER} --format '{{{{.ID}}}}'")
    if rc == 0 and out.strip() != "":
        # Double-check the container is actually running (not just exists)
        rc_status, status, _ = docker(f"inspect {CONTAINER} --format='{{{{.State.Status}}}}'")
        if rc_status == 0:
            return status.strip() == "running"
    return False


def ensure_up():
    """Ensure the Docker container is up and running."""
    rc, _, _ = sh("docker version --format '{{.Server.Version}}'")
    if rc != 0:
        print("Docker isn't available. Install & start Docker Desktop.", file=sys.stderr)
        sys.exit(1)
    
    # Choose image based on systemd preference
    container_image = SYSTEMD_IMAGE if USE_SYSTEMD_CONTAINER else IMAGE
    
    # Check if container exists and if we need to recreate it
    if docker_exists():
        # Check what image the existing container is using
        rc_img, current_img, _ = docker(f"inspect {CONTAINER} --format='{{{{.Config.Image}}}}'")
        if rc_img == 0:
            current_img = current_img.strip()
            # If image doesn't match what we want, remove and recreate
            if current_img != container_image:
                print(f"Container exists with different image ({current_img}), recreating with {container_image}...", file=sys.stderr)
                down()
        # Also check if container is in a bad state (exited, etc.)
        if docker_exists() and not docker_running():
            rc_status, status, _ = docker(f"inspect {CONTAINER} --format='{{{{.State.Status}}}}'")
            if rc_status == 0:
                status = status.strip()
                if status in ["exited", "dead", "removing"]:
                    print(f"Container exists but is in '{status}' state. Removing and recreating...", file=sys.stderr)
                    down()
    
    docker(f"pull {container_image}")
    
    if not docker_exists():
        if USE_SYSTEMD_CONTAINER:
            # Systemd-enabled container needs privileged mode and volume mounts
            # Some systemd images need /tmp to be a tmpfs mount
            print(f"Creating systemd-enabled container with image {container_image}...", file=sys.stderr)
            run_cmd = (
                f"run -d --name {CONTAINER} --hostname {CONTAINER} "
                f"--privileged --tmpfs /tmp --tmpfs /run "
                f"-v /sys/fs/cgroup:/sys/fs/cgroup:ro "
                f"{container_image}"
            )
        else:
            print(f"Creating standard container with image {container_image}...", file=sys.stderr)
            run_cmd = f"run -d --name {CONTAINER} --hostname {CONTAINER} {container_image} sleep infinity"
        
        rc, out, err = docker(run_cmd)
        if rc != 0:
            print(f"Failed to create container: {err or out}", file=sys.stderr)
            sys.exit(1)
        
        # Wait and verify container is actually running
        import time
        time.sleep(2)
        
        # Check if container is running
        if not docker_running():
            # Container might have exited - check why
            rc_exit, exit_code, _ = docker(f"inspect {CONTAINER} --format='{{{{.State.ExitCode}}}}'")
            rc_status, status, _ = docker(f"inspect {CONTAINER} --format='{{{{.State.Status}}}}'")
            
            if rc_status == 0 and status.strip() != "running":
                print(f"Warning: Container is not running (status: {status.strip()})", file=sys.stderr)
                if USE_SYSTEMD_CONTAINER:
                    print("Systemd containers may need special configuration. Trying to start...", file=sys.stderr)
                    # Try to start it
                    rc_start, out_start, err_start = docker(f"start {CONTAINER}")
                    if rc_start == 0:
                        time.sleep(2)
                        if docker_running():
                            print("Container started successfully.", file=sys.stderr)
                        else:
                            print(f"Container failed to start. Exit code: {exit_code.strip() if rc_exit == 0 else 'unknown'}", file=sys.stderr)
                            print("You may need to check Docker Desktop settings or use a standard container.", file=sys.stderr)
                            sys.exit(1)
                    else:
                        print(f"Failed to start container: {err_start or out_start}", file=sys.stderr)
                        sys.exit(1)
                else:
                    # For standard containers, just try to start
                    rc_start, out_start, err_start = docker(f"start {CONTAINER}")
                    if rc_start != 0 or not docker_running():
                        print(f"Container failed to start: {err_start or out_start}", file=sys.stderr)
                        sys.exit(1)
        
        if USE_SYSTEMD_CONTAINER:
            print("Container created. Waiting for systemd to initialize...", file=sys.stderr)
            time.sleep(2)
            # Verify systemd is actually working (only if container is running)
            if docker_running():
                rc_systemd, out_systemd, _ = docker_exec("systemctl --version >/dev/null 2>&1 && echo 'systemd_ok' || echo 'systemd_failed'")
                if "systemd_ok" not in out_systemd:
                    print("Warning: Systemd may not be working properly in the container.", file=sys.stderr)
            else:
                print("Warning: Container is not running, cannot verify systemd.", file=sys.stderr)
    
    elif not docker_running():
        # Container exists but is not running - start it
        print(f"Starting existing container {CONTAINER}...", file=sys.stderr)
        rc, out, err = docker(f"start {CONTAINER}")
        if rc != 0:
            print(f"Failed to start container: {err or out}", file=sys.stderr)
            sys.exit(1)
        
        # Wait and verify it's running
        import time
        time.sleep(1)
        if not docker_running():
            print(f"Container started but is not running. Check Docker Desktop for details.", file=sys.stderr)
            sys.exit(1)
        
        if USE_SYSTEMD_CONTAINER:
            # Verify systemd is working (only if container is running)
            if docker_running():
                time.sleep(1)
                rc_systemd, out_systemd, _ = docker_exec("systemctl --version >/dev/null 2>&1 && echo 'systemd_ok' || echo 'systemd_failed'")
                if "systemd_ok" not in out_systemd:
                    print("Warning: Systemd may not be working properly in the container.", file=sys.stderr)
            else:
                print("Warning: Container is not running, cannot verify systemd.", file=sys.stderr)


def docker_exec(cmd: str) -> Tuple[int, str, str]:
    """
    Execute a command in the Docker container as root.
    NOTE: callers should ensure container is up first.
    Use bash -c instead of bash -lc to avoid login shell issues.
    """
    # Verify container is running before executing
    if not docker_running():
        return (1, "", f"Container {CONTAINER} is not running. Use 'nomanai.py up' to start it.")
    
    # Run as root to ensure full system control
    return docker(f"exec -u root {CONTAINER} bash -c {shlex.quote(cmd)}")


def down():
    """Remove the Docker container."""
    docker(f"rm -f {CONTAINER}")

