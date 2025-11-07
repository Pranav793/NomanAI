"""
SSH client for remote machine connections.
Supports connection pooling, multiple authentication methods, and scalable operations.
"""

import asyncio
import logging
import os
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import paramiko
    from paramiko import SSHClient, AutoAddPolicy, RSAKey, Ed25519Key
    from paramiko.ssh_exception import (
        SSHException,
        AuthenticationException,
        BadHostKeyException,
        NoValidConnectionsError,
    )
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False
    # Create dummy classes for type hints
    SSHClient = None
    AutoAddPolicy = None
    RSAKey = None
    Ed25519Key = None
    SSHException = Exception
    AuthenticationException = Exception

logger = logging.getLogger(__name__)


@dataclass
class SSHConfig:
    """SSH connection configuration."""
    host: str
    port: int = 22
    username: str = "root"
    password: Optional[str] = None
    key_file: Optional[str] = None
    key_data: Optional[str] = None
    passphrase: Optional[str] = None
    timeout: int = 30
    allow_agent: bool = True
    look_for_keys: bool = True
    compress: bool = False
    # Connection pool settings
    max_connections: int = 10
    connection_timeout: int = 30
    keepalive_interval: int = 30


if not PARAMIKO_AVAILABLE:
    raise ImportError(
        "paramiko is required for SSH functionality. Install it with: pip install paramiko"
    )


class SSHConnectionPool:
    """
    Connection pool for SSH connections to improve performance and scalability.
    Reuses connections to avoid overhead of establishing new connections.
    """
    
    def __init__(self, max_connections_per_host: int = 5):
        self.max_connections_per_host = max_connections_per_host
        self._pools: Dict[str, List[SSHClient]] = defaultdict(list)
        self._locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._active_connections: Dict[str, int] = defaultdict(int)
        self._configs: Dict[str, SSHConfig] = {}
    
    def _get_pool_key(self, config: SSHConfig) -> str:
        """Generate a unique key for connection pool."""
        return f"{config.username}@{config.host}:{config.port}"
    
    def get_connection(self, config: SSHConfig) -> SSHClient:
        """Get a connection from the pool or create a new one."""
        pool_key = self._get_pool_key(config)
        lock = self._locks[pool_key]
        
        with lock:
            # Store config for this pool
            if pool_key not in self._configs:
                self._configs[pool_key] = config
            
            # Try to reuse existing connection
            while self._pools[pool_key]:
                conn = self._pools[pool_key].pop()
                if self._is_connection_alive(conn):
                    self._active_connections[pool_key] += 1
                    return conn
                else:
                    try:
                        conn.close()
                    except:
                        pass
            
            # Create new connection if pool is empty and under limit
            if self._active_connections[pool_key] < self.max_connections_per_host:
                conn = self._create_connection(config)
                self._active_connections[pool_key] += 1
                return conn
            
            # Wait for a connection to become available
            # In a production system, you might want to use a semaphore here
            raise Exception(f"Connection pool exhausted for {pool_key}. Max connections: {self.max_connections_per_host}")
    
    def return_connection(self, config: SSHConfig, conn: SSHClient):
        """Return a connection to the pool."""
        pool_key = self._get_pool_key(config)
        lock = self._locks[pool_key]
        
        with lock:
            if self._is_connection_alive(conn):
                self._pools[pool_key].append(conn)
            else:
                try:
                    conn.close()
                except:
                    pass
            self._active_connections[pool_key] = max(0, self._active_connections[pool_key] - 1)
    
    def _is_connection_alive(self, conn: SSHClient) -> bool:
        """Check if SSH connection is still alive."""
        try:
            transport = conn.get_transport()
            if transport is None:
                return False
            return transport.is_active()
        except:
            return False
    
    def _create_connection(self, config: SSHConfig) -> SSHClient:
        """Create a new SSH connection."""
        client = SSHClient()
        client.set_missing_host_key_policy(AutoAddPolicy())
        
        # Prepare authentication
        auth_kwargs = {
            'username': config.username,
            'timeout': config.timeout,
            'allow_agent': config.allow_agent,
            'look_for_keys': config.look_for_keys,
            'compress': config.compress,
        }
        
        # Add key-based authentication
        pkey = None
        if config.key_file:
            pkey = self._load_key_file(config.key_file, config.passphrase)
        elif config.key_data:
            pkey = self._load_key_data(config.key_data, config.passphrase)
        
        if pkey:
            auth_kwargs['pkey'] = pkey
        
        # Connect
        try:
            client.connect(config.host, port=config.port, **auth_kwargs)
            
            # Set keepalive
            transport = client.get_transport()
            if transport:
                transport.set_keepalive(config.keepalive_interval)
            
            return client
        except AuthenticationException:
            # Try password authentication if key failed
            if config.password:
                auth_kwargs.pop('pkey', None)
                auth_kwargs['password'] = config.password
                client.connect(config.host, port=config.port, **auth_kwargs)
                
                transport = client.get_transport()
                if transport:
                    transport.set_keepalive(config.keepalive_interval)
                
                return client
            raise
        except Exception as e:
            client.close()
            raise SSHException(f"Failed to connect to {config.host}:{config.port}: {str(e)}")
    
    def _load_key_file(self, key_path: str, passphrase: Optional[str] = None):
        """Load SSH key from file."""
        key_path = Path(key_path).expanduser()
        if not key_path.exists():
            raise FileNotFoundError(f"SSH key file not found: {key_path}")
        
        # Try different key types
        for key_class in [Ed25519Key, RSAKey]:
            try:
                return key_class.from_private_key_file(str(key_path), password=passphrase)
            except:
                continue
        
        raise ValueError(f"Unable to load SSH key from {key_path}")
    
    def _load_key_data(self, key_data: str, passphrase: Optional[str] = None):
        """Load SSH key from string data."""
        from io import StringIO
        
        # Try different key types
        for key_class in [Ed25519Key, RSAKey]:
            try:
                key_file = StringIO(key_data)
                return key_class.from_private_key(key_file, password=passphrase)
            except:
                continue
        
        raise ValueError("Unable to load SSH key from provided data")
    
    def close_all(self):
        """Close all connections in the pool."""
        for pool_key, connections in self._pools.items():
            for conn in connections:
                try:
                    conn.close()
                except:
                    pass
            self._pools[pool_key] = []
            self._active_connections[pool_key] = 0
    
    def get_stats(self) -> Dict[str, Dict]:
        """Get connection pool statistics."""
        stats = {}
        for pool_key in self._pools:
            stats[pool_key] = {
                'pooled': len(self._pools[pool_key]),
                'active': self._active_connections[pool_key],
                'total': len(self._pools[pool_key]) + self._active_connections[pool_key]
            }
        return stats


class SSHClientManager:
    """
    High-level SSH client manager with connection pooling and multi-machine support.
    Thread-safe and scalable for enterprise use.
    """
    
    def __init__(self, max_connections_per_host: int = 5):
        self.pool = SSHConnectionPool(max_connections_per_host)
        self._default_config: Optional[SSHConfig] = None
    
    def set_default_config(self, config: SSHConfig):
        """Set default SSH configuration."""
        self._default_config = config
    
    def parse_ssh_url(self, url: str) -> SSHConfig:
        """
        Parse SSH URL format: ssh://user@host:port or user@host:port
        Also supports: ssh://user:password@host:port (not recommended for security)
        """
        # Handle user@host:port format
        if not url.startswith('ssh://'):
            url = f'ssh://{url}'
        
        parsed = urlparse(url)
        
        config = SSHConfig(
            host=parsed.hostname or '',
            port=parsed.port or 22,
            username=parsed.username or 'root',
        )
        
        # Extract password from URL if present (not recommended)
        if parsed.password:
            config.password = parsed.password
        
        return config
    
    @contextmanager
    def get_client(self, config: Optional[SSHConfig] = None, url: Optional[str] = None):
        """
        Get an SSH client from the pool. Use as context manager for automatic cleanup.
        
        Usage:
            with ssh_manager.get_client(config=my_config) as client:
                stdin, stdout, stderr = client.exec_command('ls')
        """
        if url:
            config = self.parse_ssh_url(url)
        elif not config:
            config = self._default_config
        
        if not config:
            raise ValueError("No SSH configuration provided")
        
        client = None
        try:
            client = self.pool.get_connection(config)
            yield client
        finally:
            if client:
                self.pool.return_connection(config, client)
    
    def execute(self, command: str, config: Optional[SSHConfig] = None, 
                url: Optional[str] = None, timeout: int = 30) -> Tuple[int, str, str]:
        """
        Execute a command on a remote machine.
        Returns: (returncode, stdout, stderr)
        """
        with self.get_client(config=config, url=url) as client:
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            returncode = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode('utf-8', errors='replace')
            stderr_text = stderr.read().decode('utf-8', errors='replace')
            return returncode, stdout_text, stderr_text
    
    def execute_async(self, command: str, config: Optional[SSHConfig] = None,
                     url: Optional[str] = None, timeout: int = 30):
        """
        Execute a command asynchronously (for concurrent operations).
        Returns a coroutine.
        """
        async def _execute():
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self.execute, command, config, url, timeout
            )
        return _execute()
    
    def execute_batch(self, commands: List[str], config: Optional[SSHConfig] = None,
                     url: Optional[str] = None, timeout: int = 30) -> List[Tuple[int, str, str]]:
        """
        Execute multiple commands sequentially on the same connection.
        More efficient than multiple execute() calls.
        """
        results = []
        with self.get_client(config=config, url=url) as client:
            for command in commands:
                stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
                returncode = stdout.channel.recv_exit_status()
                stdout_text = stdout.read().decode('utf-8', errors='replace')
                stderr_text = stderr.read().decode('utf-8', errors='replace')
                results.append((returncode, stdout_text, stderr_text))
        return results
    
    async def execute_batch_async(self, commands: List[str], 
                                  config: Optional[SSHConfig] = None,
                                  url: Optional[str] = None, 
                                  timeout: int = 30) -> List[Tuple[int, str, str]]:
        """
        Execute multiple commands asynchronously (concurrent execution).
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.execute_batch, commands, config, url, timeout
        )
    
    def execute_multi_host(self, command: str, configs: List[SSHConfig],
                          timeout: int = 30) -> Dict[str, Tuple[int, str, str]]:
        """
        Execute a command on multiple hosts in parallel.
        Returns a dict mapping host to (returncode, stdout, stderr).
        """
        results = {}
        
        def _execute_for_host(config: SSHConfig):
            try:
                result = self.execute(command, config=config, timeout=timeout)
                return config.host, result
            except Exception as e:
                return config.host, (1, "", str(e))
        
        # Use ThreadPoolExecutor for parallel execution
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        with ThreadPoolExecutor(max_workers=min(len(configs), 20)) as executor:
            future_to_host = {
                executor.submit(_execute_for_host, config): config.host 
                for config in configs
            }
            
            for future in as_completed(future_to_host):
                host, result = future.result()
                results[host] = result
        
        return results
    
    def read_file(self, remote_path: str, config: Optional[SSHConfig] = None,
                  url: Optional[str] = None) -> str:
        """Read a file from the remote machine."""
        with self.get_client(config=config, url=url) as client:
            sftp = client.open_sftp()
            try:
                with sftp.open(remote_path, 'r') as f:
                    return f.read().decode('utf-8', errors='replace')
            finally:
                sftp.close()
    
    def write_file(self, remote_path: str, content: str, 
                   config: Optional[SSHConfig] = None, url: Optional[str] = None,
                   mode: int = 0o644):
        """Write a file to the remote machine."""
        with self.get_client(config=config, url=url) as client:
            sftp = client.open_sftp()
            try:
                # Create directory if needed
                dir_path = os.path.dirname(remote_path)
                if dir_path:
                    try:
                        sftp.mkdir(dir_path)
                    except IOError:
                        pass  # Directory might already exist
                
                with sftp.open(remote_path, 'w') as f:
                    f.write(content.encode('utf-8'))
                
                # Set file permissions
                sftp.chmod(remote_path, mode)
            finally:
                sftp.close()
    
    def test_connection(self, config: Optional[SSHConfig] = None, 
                       url: Optional[str] = None) -> bool:
        """Test if SSH connection works."""
        try:
            with self.get_client(config=config, url=url) as client:
                return client.get_transport() is not None and client.get_transport().is_active()
        except:
            return False
    
    def close_all(self):
        """Close all connections."""
        self.pool.close_all()
    
    def get_stats(self) -> Dict[str, Dict]:
        """Get connection pool statistics."""
        return self.pool.get_stats()


# Global SSH client manager instance
_ssh_manager: Optional[SSHClientManager] = None


def get_ssh_manager(max_connections_per_host: int = 5) -> SSHClientManager:
    """Get or create the global SSH client manager."""
    global _ssh_manager
    if _ssh_manager is None:
        _ssh_manager = SSHClientManager(max_connections_per_host)
    return _ssh_manager


def set_default_ssh_config(config: SSHConfig):
    """Set default SSH configuration globally."""
    manager = get_ssh_manager()
    manager.set_default_config(config)

