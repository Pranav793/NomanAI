#!/bin/bash
# Cleanup script for test environment
# Removes test containers, SSH keys, and Docker configuration files

set -e

echo "🧹 Cleaning up test environment..."

# Stop and remove test containers
if [ -f docker-compose.test-ssh.yml ]; then
    echo "📦 Stopping and removing test containers..."
    docker-compose -f docker-compose.test-ssh.yml down -v 2>/dev/null || true
    echo "   ✓ Test containers removed"
else
    echo "   ℹ No docker-compose.test-ssh.yml found"
fi

# Remove test SSH keys
if [ -d "./test_ssh_keys" ]; then
    echo "🔑 Removing test SSH keys..."
    rm -rf ./test_ssh_keys
    echo "   ✓ Test SSH keys removed"
else
    echo "   ℹ No test_ssh_keys directory found"
fi

# Remove Docker test files
if [ -f "Dockerfile.ssh-test" ]; then
    echo "🐳 Removing Docker test files..."
    rm -f Dockerfile.ssh-test
    echo "   ✓ Dockerfile.ssh-test removed"
fi

if [ -f "docker-compose.test-ssh.yml" ]; then
    rm -f docker-compose.test-ssh.yml
    echo "   ✓ docker-compose.test-ssh.yml removed"
fi

# Remove test scripts (optional - uncomment if you want to remove them)
# if [ -f "test_ssh_setup.sh" ]; then
#     echo "📝 Removing test setup script..."
#     rm -f test_ssh_setup.sh
#     echo "   ✓ test_ssh_setup.sh removed"
# fi
#
# if [ -f "test_multi_machine.py" ]; then
#     echo "📝 Removing test script..."
#     rm -f test_multi_machine.py
#     echo "   ✓ test_multi_machine.py removed"
# fi

# Check for any remaining test containers
echo "🔍 Checking for remaining test containers..."
REMAINING=$(docker ps -a --filter "name=nomanai-ssh-test" --format "{{.Names}}" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    echo "   ⚠ Found remaining containers: $REMAINING"
    echo "   Run 'docker rm -f $REMAINING' to remove them"
else
    echo "   ✓ No remaining test containers"
fi

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "To recreate test environment, run: ./test_ssh_setup.sh"

