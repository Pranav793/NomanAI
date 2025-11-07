# NomanAI

AI-powered security configuration remediation system. Remediate security misconfigurations on Linux machines through natural language commands. Supports both Docker containers and remote SSH connections.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [SSH/Remote Connections](#sshremote-connections)
- [Multi-Machine Support](#multi-machine-support)
- [Testing](#testing)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Cleanup](#cleanup)

## Overview

NomanAI uses AI agents to interact with Linux systems through natural language. It can:
- Install and configure software
- Manage system services
- Update system packages
- Modify configuration files
- Perform security remediations
- Execute operations on single or multiple remote machines

## Features

### Core Capabilities
- **Natural Language Interface**: Describe what you want in plain English
- **Multi-Agent System**: Planner, Executor, and Verifier agents work together
- **Full Linux Control**: Package management, service management, file operations
- **Remote Execution**: Works with Docker containers or SSH connections
- **Multi-Machine Support**: Execute operations on multiple hosts in parallel
- **Connection Pooling**: Efficient connection reuse for better performance
- **Security First**: Command whitelisting and policy enforcement

### Available Tools

#### Package Management
- `install_package`: Install one or more packages
- `remove_package`: Remove packages
- `update_system`: Update and upgrade all packages
- `list_packages`: List installed packages
- `search_packages`: Search for available packages

#### Service Management
- `restart_service`: Start, stop, restart, enable, disable services
- `check_service_status`: Get detailed service status
- `list_services`: List all system services

#### File Operations
- `read_file`: Read files
- `write_file`: Write files atomically
- `create_directory`: Create directories
- `change_permissions`: Change file permissions
- `change_ownership`: Change file ownership

#### Configuration Management
- `set_config_kv`: Set configuration key-value pairs
- `verify_regex`: Verify file content matches patterns

## Quick Start

### Docker Mode (Default)

```bash
# Start container
python3 nomanai.py up

# Run a command
python3 nomanai.py multi-agent --goal "Install curl and verify it works"
```

### SSH Mode

```bash
# Test SSH connection
python3 nomanai.py ssh test --host user@server.com --key ~/.ssh/id_rsa

# Use multi-agent with SSH
python3 nomanai.py multi-agent \
  --goal "Install nginx and start it" \
  --ssh-host user@server.com \
  --key ~/.ssh/id_rsa
```

## Installation

### Requirements

- Python 3.8+
- Docker (for container mode)
- OpenAI API key

### Install Dependencies

```bash
# Activate virtual environment (if using)
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### Environment Variables

```bash
# OpenAI API
export OPENAI_API_KEY="your-api-key"

# Optional: Model and API settings
export NOMANAI_MODEL="gpt-4o"
export NOMANAI_API_MODE="chat"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # Optional for Azure/proxy

# SSH Configuration (optional)
export NOMANAI_SSH_MAX_CONNECTIONS=5
export NOMANAI_SSH_TIMEOUT=30
export NOMANAI_SSH_KEEPALIVE=30

# Docker Configuration (optional)
export NOMANAI_USE_SYSTEMD=false
export NOMANAI_SYSTEMD_IMAGE="jrei/systemd-ubuntu:24.04"
```

## Usage

### Basic Commands

```bash
# Container management
python3 nomanai.py up          # Start container
python3 nomanai.py down        # Stop container
python3 nomanai.py exec -- cmd # Execute command

# Multi-agent system
python3 nomanai.py multi-agent --goal "Your goal here"

# SSH commands
python3 nomanai.py ssh test --host user@host --key ~/.ssh/id_rsa
python3 nomanai.py ssh exec --host user@host --key ~/.ssh/id_rsa --cmd "ls -la"
python3 nomanai.py ssh stats   # View connection pool statistics
```

### Example Goals

```bash
# Install software
python3 nomanai.py multi-agent --goal "Install nginx and start it"

# Configure services
python3 nomanai.py multi-agent --goal "Enable SSH service to start at boot"

# Security remediation
python3 nomanai.py multi-agent --goal "Disable SSH password authentication"

# System updates
python3 nomanai.py multi-agent --goal "Update all system packages"

# With SSH
python3 nomanai.py multi-agent \
  --goal "Install curl and verify it works" \
  --ssh-host root@server.com \
  --key ~/.ssh/id_rsa
```

## SSH/Remote Connections

### Features

- **Connection Pooling**: Reuses SSH connections for better performance
- **Multiple Authentication Methods**: Key-based and password authentication
- **Scalable**: Supports concurrent operations on multiple machines
- **Thread-Safe**: Safe for multi-threaded environments
- **Automatic Reconnection**: Handles connection failures gracefully

### Authentication

#### Key-Based (Recommended)

```bash
# Test connection
python3 nomanai.py ssh test --host user@server.com --key ~/.ssh/id_rsa

# Use with multi-agent
python3 nomanai.py multi-agent \
  --goal "Your goal" \
  --ssh-host user@server.com \
  --key ~/.ssh/id_rsa
```

#### Password (Not Recommended)

```bash
python3 nomanai.py ssh test --host user@server.com --password mypassword
```

### Supported Key Formats

- RSA keys (2048-bit and above)
- Ed25519 keys
- Keys with or without passphrases

### Connection Options

```bash
# Custom port
python3 nomanai.py multi-agent \
  --goal "Your goal" \
  --ssh-host user@server.com:2222 \
  --key ~/.ssh/id_rsa

# Or specify port separately
python3 nomanai.py multi-agent \
  --goal "Your goal" \
  --ssh-host user@server.com \
  --ssh-port 2222 \
  --key ~/.ssh/id_rsa
```

### Connection Pool Statistics

```bash
# View connection pool stats
python3 nomanai.py ssh stats
```

## Multi-Machine Support

### Overview

Execute operations on multiple remote hosts simultaneously for faster fleet management.

### How It Works

1. **Connection Pooling**: Each host has its own connection pool (default: 5 connections)
2. **Parallel Execution**: Commands execute simultaneously across all hosts
3. **Result Collection**: Results are collected as they complete
4. **Independent Execution**: One host failure doesn't stop others

### Architecture

```
SSHClientManager (Orchestrator)
    ↓
    ├─→ Connection Pool (Host 1) → SSH Connection (Reused)
    ├─→ Connection Pool (Host 2) → SSH Connection (Reused)
    └─→ Connection Pool (Host 3) → SSH Connection (Reused)
         ↓
    ThreadPoolExecutor (Parallel Execution)
```

### Usage Example

```python
from nomanai.ssh_client import SSHClientManager, SSHConfig

manager = SSHClientManager()

# Define multiple hosts
configs = [
    SSHConfig(host="server1.example.com", username="admin", key_file="~/.ssh/id_rsa"),
    SSHConfig(host="server2.example.com", username="admin", key_file="~/.ssh/id_rsa"),
    SSHConfig(host="server3.example.com", username="admin", key_file="~/.ssh/id_rsa"),
]

# Execute command on all hosts in parallel
results = manager.execute_multi_host("systemctl status ssh", configs)

# Process results
for host, (rc, stdout, stderr) in results.items():
    if rc == 0:
        print(f"✓ {host}: {stdout.strip()}")
    else:
        print(f"✗ {host}: {stderr.strip()}")
```

### Performance

- **Sequential**: 3 servers × 2s = 6 seconds
- **Parallel**: 3 servers simultaneously = 2 seconds
- **Speedup**: 3x faster (or more with more servers)

### Real-World Example

```python
# Remediate security on production servers
production_servers = [
    SSHConfig(host="prod1.example.com", username="admin", key_file="~/.ssh/prod_key"),
    SSHConfig(host="prod2.example.com", username="admin", key_file="~/.ssh/prod_key"),
    SSHConfig(host="prod3.example.com", username="admin", key_file="~/.ssh/prod_key"),
]

# Disable password auth on all servers in parallel
results = manager.execute_multi_host(
    "sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config && systemctl reload sshd",
    production_servers
)

# Check results
for host, (rc, stdout, stderr) in results.items():
    if rc == 0:
        print(f"✓ {host}: Password auth disabled")
    else:
        print(f"✗ {host}: Failed - {stderr}")
```

## Testing

### Setup Test Environment

```bash
# Run setup script to create test SSH containers
./test_ssh_setup.sh

# Start test containers
docker-compose -f docker-compose.test-ssh.yml up -d
```

This creates 3 SSH-enabled test containers:
- `nomanai-ssh-test-1` on port 2222
- `nomanai-ssh-test-2` on port 2223
- `nomanai-ssh-test-3` on port 2224

### Test SSH Connection

```bash
# Test connection to container 1
python3 nomanai.py ssh test \
  --host root@localhost:2222 \
  --key ./test_ssh_keys/id_ed25519
```

### Test Multi-Agent with SSH

```bash
# Test on container 1
python3 nomanai.py multi-agent \
  --goal "Install curl and verify it works" \
  --ssh-host root@localhost:2222 \
  --key ./test_ssh_keys/id_ed25519
```

### Test Multi-Machine

```bash
# Run automated test
python3 test_multi_machine.py
```

This tests:
- Connections to all 3 containers
- Parallel command execution
- File read/write operations
- Connection pool statistics

### Manual Testing

```bash
# Execute command via SSH
python3 nomanai.py ssh exec \
  --host root@localhost:2222 \
  --key ./test_ssh_keys/id_ed25519 \
  --cmd "hostname"

# Check service status
python3 nomanai.py ssh exec \
  --host root@localhost:2222 \
  --key ./test_ssh_keys/id_ed25519 \
  --cmd "systemctl status ssh"
```

## Configuration

### Docker Configuration

#### Standard Container (Default)

```bash
# Uses standard Ubuntu container
python3 nomanai.py up
```

#### Systemd-Enabled Container

```bash
# Use systemd-enabled container for full service management
export NOMANAI_USE_SYSTEMD=true
python3 nomanai.py down  # Remove old container
python3 nomanai.py up    # Create new systemd-enabled container
```

### SSH Configuration

```bash
# Maximum connections per host (default: 5)
export NOMANAI_SSH_MAX_CONNECTIONS=10

# Connection timeout in seconds (default: 30)
export NOMANAI_SSH_TIMEOUT=60

# Keepalive interval in seconds (default: 30)
export NOMANAI_SSH_KEEPALIVE=30
```

### Security Policy

```bash
# Allow insecure configurations (for testing)
python3 nomanai.py multi-agent \
  --goal "Your goal" \
  --allow-insecure
```

## Architecture

### Multi-Agent System

1. **Planner Agent**: Creates detailed, step-by-step plans from natural language goals
2. **Executor Agent**: Executes the planned steps using available tools
3. **Verifier Agent**: Verifies that goals were achieved correctly

### Remote Execution

- **Docker Mode**: Executes commands in Docker containers
- **SSH Mode**: Executes commands on remote machines via SSH
- **Unified Interface**: Same tools work with both modes

### Connection Management

- **Connection Pooling**: Reuses SSH connections for efficiency
- **Health Checks**: Automatically detects and replaces dead connections
- **Thread-Safe**: Safe for concurrent operations

## Troubleshooting

### Container Issues

```bash
# Check container status
docker ps | grep nomanai

# Check container logs
docker logs nomanai-sbx

# Restart container
python3 nomanai.py down
python3 nomanai.py up
```

### SSH Connection Issues

```bash
# Test connection manually
ssh -i ~/.ssh/id_rsa -p 22 user@host

# Check SSH key permissions
chmod 600 ~/.ssh/id_rsa

# Verify key format
ssh-keygen -l -f ~/.ssh/id_rsa.pub
```

### Connection Pool Exhausted

```bash
# Increase pool size
export NOMANAI_SSH_MAX_CONNECTIONS=10

# Check pool statistics
python3 nomanai.py ssh stats
```

### Service Management Issues

```bash
# Check if systemd is available
python3 nomanai.py exec -- systemctl --version

# Use systemd-enabled container
export NOMANAI_USE_SYSTEMD=true
python3 nomanai.py down && python3 nomanai.py up
```

## Cleanup

### Test Environment Cleanup

After testing, clean up test files and containers using the cleanup script:

```bash
# Run the cleanup script (recommended)
./cleanup_test_env.sh
```

Or manually:

```bash
# Stop and remove test containers
docker-compose -f docker-compose.test-ssh.yml down -v

# Remove test SSH keys
rm -rf ./test_ssh_keys

# Remove Docker test files
rm -f Dockerfile.ssh-test docker-compose.test-ssh.yml

# Remove test scripts (optional)
# rm -f test_ssh_setup.sh test_multi_machine.py
```

### Production Container Cleanup

```bash
# Remove production container
python3 nomanai.py down

# Remove Docker images (optional)
docker rmi ubuntu:24.04
docker rmi jrei/systemd-ubuntu:24.04  # If used
```

### SSH Connection Cleanup

```bash
# Close all SSH connections
python3 -c "from nomanai.ssh_client import get_ssh_manager; get_ssh_manager().close_all()"

# Or check connections first
python3 nomanai.py ssh stats
```

### What Gets Cleaned Up

The cleanup script (`cleanup_test_env.sh`) removes:
- Test Docker containers (nomanai-ssh-test-*)
- Test SSH keys directory (`./test_ssh_keys/`)
- Docker test files (`Dockerfile.ssh-test`, `docker-compose.test-ssh.yml`)

**Note**: The cleanup script does NOT remove:
- Test setup scripts (`test_ssh_setup.sh`, `test_multi_machine.py`) - uncomment in script if desired
- Production containers or SSH connections

## Examples

### Example 1: Security Remediation

```bash
# Disable SSH password authentication
python3 nomanai.py multi-agent \
  --goal "Disable SSH password authentication and restart SSH service" \
  --ssh-host admin@production-server.com \
  --key ~/.ssh/id_rsa
```

### Example 2: Software Installation

```bash
# Install and configure nginx
python3 nomanai.py multi-agent \
  --goal "Install nginx, configure it to listen on port 8080, and start it" \
  --ssh-host root@web-server.com \
  --key ~/.ssh/id_rsa
```

### Example 3: System Updates

```bash
# Update all packages
python3 nomanai.py multi-agent \
  --goal "Update all system packages and restart services that need restarting" \
  --ssh-host admin@server.com \
  --key ~/.ssh/id_rsa
```

### Example 4: Service Management

```bash
# Enable and start service
python3 nomanai.py multi-agent \
  --goal "Enable SSH service to start at boot and verify it's running" \
  --ssh-host root@server.com \
  --key ~/.ssh/id_rsa
```

### Example 5: RSA Key Generation

```bash
# Generate RSA key pair
python3 nomanai.py multi-agent \
  --goal "Make an RSA key pair and give me the public and private keys" \
  --ssh-host root@server.com \
  --key ~/.ssh/id_rsa
```

## Security Best Practices

1. **Use Key-Based Authentication**: Avoid password authentication
2. **Protect Private Keys**: Use appropriate file permissions (600)
3. **Use Passphrases**: Protect keys with passphrases
4. **Limit Access**: Use SSH keys with limited permissions
5. **Monitor Connections**: Regularly check connection pool statistics
6. **Command Whitelisting**: Only whitelisted commands can be executed
7. **Policy Enforcement**: Insecure configurations are blocked by default

## Command Reference

### Container Commands

```bash
python3 nomanai.py up              # Start container
python3 nomanai.py down            # Stop container
python3 nomanai.py exec -- cmd     # Execute command
```

### Multi-Agent Commands

```bash
python3 nomanai.py multi-agent --goal "Your goal"
python3 nomanai.py multi-agent --goal "Your goal" --allow-insecure
python3 nomanai.py multi-agent --goal "Your goal" --ssh-host user@host --key ~/.ssh/id_rsa
```

### SSH Commands

```bash
python3 nomanai.py ssh test --host user@host --key ~/.ssh/id_rsa
python3 nomanai.py ssh exec --host user@host --key ~/.ssh/id_rsa --cmd "command"
python3 nomanai.py ssh stats
```

## Future Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features and enhancements.

## License

[Your License Here]

## Contributing

[Contributing Guidelines]

## Support

[Support Information]
