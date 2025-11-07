#!/usr/bin/env python3
"""
Test script for multi-machine SSH functionality.
Tests SSH connections to multiple Docker containers.
"""

import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from nomanai.ssh_client import SSHClientManager, SSHConfig

def test_multi_machine():
    """Test multi-machine SSH execution."""
    print("=" * 70)
    print("Multi-Machine SSH Test")
    print("=" * 70)
    
    # Initialize SSH manager
    manager = SSHClientManager(max_connections_per_host=3)
    
    # Test with localhost containers (from docker-compose)
    ssh_key = "./test_ssh_keys/id_ed25519"
    
    if not Path(ssh_key).exists():
        print(f"Error: SSH key not found: {ssh_key}")
        print("Please run ./test_ssh_setup.sh first to generate test keys")
        return 1
    
    configs = [
        SSHConfig(
            host="localhost",
            port=2222,
            username="root",
            key_file=ssh_key,
            timeout=10
        ),
        SSHConfig(
            host="localhost",
            port=2223,
            username="root",
            key_file=ssh_key,
            timeout=10
        ),
        SSHConfig(
            host="localhost",
            port=2224,
            username="root",
            key_file=ssh_key,
            timeout=10
        ),
    ]
    
    print("\n1. Testing connections...")
    for i, config in enumerate(configs, 1):
        if manager.test_connection(config=config):
            print(f"   ✓ Container {i} (port {config.port}): Connected")
        else:
            print(f"   ✗ Container {i} (port {config.port}): Failed")
            print("   Make sure containers are running: docker-compose -f docker-compose.test-ssh.yml up -d")
            return 1
    
    print("\n2. Testing parallel execution...")
    print("   Executing 'hostname' on all containers in parallel...")
    results = manager.execute_multi_host("hostname", configs)
    
    print("\n   Results:")
    for host, (rc, stdout, stderr) in results.items():
        if rc == 0:
            print(f"   ✓ {host}: {stdout.strip()}")
        else:
            print(f"   ✗ {host}: Error (rc={rc}) - {stderr.strip()}")
    
    print("\n3. Testing file operations...")
    test_content = "Hello from NomanAI multi-machine test!\n"
    for i, config in enumerate(configs, 1):
        test_file = f"/tmp/nomanai_test_{i}.txt"
        try:
            manager.write_file(test_file, test_content, config=config)
            content = manager.read_file(test_file, config=config)
            if content == test_content:
                print(f"   ✓ Container {i}: File write/read successful")
            else:
                print(f"   ✗ Container {i}: File content mismatch")
        except Exception as e:
            print(f"   ✗ Container {i}: Error - {e}")
    
    print("\n4. Testing connection pool statistics...")
    stats = manager.get_stats()
    if stats:
        print("   Connection Pool Stats:")
        for pool_key, stat in stats.items():
            print(f"     {pool_key}:")
            print(f"       Pooled: {stat['pooled']}")
            print(f"       Active: {stat['active']}")
            print(f"       Total: {stat['total']}")
    else:
        print("   No active connections")
    
    print("\n5. Cleanup...")
    manager.close_all()
    print("   ✓ All connections closed")
    
    print("\n" + "=" * 70)
    print("Multi-machine test complete!")
    print("=" * 70)
    return 0

if __name__ == "__main__":
    sys.exit(test_multi_machine())

