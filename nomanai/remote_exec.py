"""
Unified remote execution interface supporting both Docker containers and SSH connections.
"""

import shlex
from typing import Optional, Tuple

from . import config
from .docker_utils import docker_exec as _docker_exec
from .ssh_client import SSHClientManager, SSHConfig, get_ssh_manager


class RemoteExecutor:
    """
    Unified interface for executing commands on remote targets.
    Supports both Docker containers and SSH connections.
    """
    
    def __init__(self, target_type: str = "docker", ssh_config: Optional[SSHConfig] = None):
        """
        Initialize remote executor.
        
        Args:
            target_type: "docker" or "ssh"
            ssh_config: SSH configuration if target_type is "ssh"
        """
        self.target_type = target_type
        self.ssh_config = ssh_config
        self.ssh_manager = None
        
        if target_type == "ssh":
            if not ssh_config:
                raise ValueError("SSH config required for SSH target type")
            self.ssh_manager = get_ssh_manager(config.SSH_MAX_CONNECTIONS_PER_HOST)
            self.ssh_manager.set_default_config(ssh_config)
    
    def execute(self, cmd: str) -> Tuple[int, str, str]:
        """
        Execute a command on the remote target.
        Returns: (returncode, stdout, stderr)
        """
        if self.target_type == "docker":
            return _docker_exec(cmd)
        elif self.target_type == "ssh":
            if not self.ssh_manager:
                raise ValueError("SSH manager not initialized")
            return self.ssh_manager.execute(cmd, config=self.ssh_config, 
                                           timeout=config.SSH_DEFAULT_TIMEOUT)
        else:
            raise ValueError(f"Unknown target type: {self.target_type}")
    
    def read_file(self, path: str) -> str:
        """Read a file from the remote target."""
        if self.target_type == "docker":
            from .file_ops import read_file as _read_file
            return _read_file(path)
        elif self.target_type == "ssh":
            if not self.ssh_manager:
                raise ValueError("SSH manager not initialized")
            return self.ssh_manager.read_file(path, config=self.ssh_config)
        else:
            raise ValueError(f"Unknown target type: {self.target_type}")
    
    def write_file(self, path: str, content: str):
        """Write a file to the remote target."""
        if self.target_type == "docker":
            from .file_ops import write_file_atomic
            write_file_atomic(path, content)
        elif self.target_type == "ssh":
            if not self.ssh_manager:
                raise ValueError("SSH manager not initialized")
            self.ssh_manager.write_file(path, content, config=self.ssh_config)
        else:
            raise ValueError(f"Unknown target type: {self.target_type}")
    
    def test_connection(self) -> bool:
        """Test if connection to remote target works."""
        if self.target_type == "docker":
            from .docker_utils import docker_running
            return docker_running()
        elif self.target_type == "ssh":
            if not self.ssh_manager:
                return False
            return self.ssh_manager.test_connection(config=self.ssh_config)
        else:
            return False


# Global executor instance
_current_executor: Optional[RemoteExecutor] = None


def set_executor(executor: RemoteExecutor):
    """Set the global remote executor."""
    global _current_executor
    _current_executor = executor


def get_executor() -> RemoteExecutor:
    """Get the current remote executor."""
    global _current_executor
    if _current_executor is None:
        # Default to Docker
        _current_executor = RemoteExecutor(target_type="docker")
    return _current_executor


def execute_remote(cmd: str) -> Tuple[int, str, str]:
    """Execute a command using the current remote executor."""
    return get_executor().execute(cmd)

