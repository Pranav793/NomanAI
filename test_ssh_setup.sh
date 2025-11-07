#!/bin/bash
# Setup script for testing SSH functionality with Docker containers

set -e

echo "Setting up SSH test environment..."

# Create SSH keys for testing if they don't exist
SSH_KEY_DIR="./test_ssh_keys"
if [ ! -d "$SSH_KEY_DIR" ]; then
    mkdir -p "$SSH_KEY_DIR"
    chmod 700 "$SSH_KEY_DIR"
    
    echo "Generating SSH test keys..."
    ssh-keygen -t ed25519 -f "$SSH_KEY_DIR/id_ed25519" -N "" -C "nomanai-test"
    ssh-keygen -t rsa -b 2048 -f "$SSH_KEY_DIR/id_rsa" -N "" -C "nomanai-test"
    
    echo "SSH keys created in $SSH_KEY_DIR"
fi

# Get the public key
PUBLIC_KEY=$(cat "$SSH_KEY_DIR/id_ed25519.pub")

# Create Dockerfile for SSH-enabled containers
cat > Dockerfile.ssh-test << 'EOF'
FROM ubuntu:24.04

# Install SSH server and basic tools
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    openssh-server \
    sudo \
    curl \
    wget \
    vim \
    systemd \
    && rm -rf /var/lib/apt/lists/*

# Configure SSH
RUN mkdir /var/run/sshd && \
    echo 'root:testpass' | chpasswd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    echo "Port 22" >> /etc/ssh/sshd_config

# Create .ssh directory and add public key
RUN mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh

# Copy public key (will be replaced by docker-compose)
RUN echo "PUBLIC_KEY_PLACEHOLDER" > /root/.ssh/authorized_keys && \
    chmod 600 /root/.ssh/authorized_keys

# Expose SSH port
EXPOSE 22

# Start SSH service
CMD ["/usr/sbin/sshd", "-D"]
EOF

# Create docker-compose file for multiple test containers
# Escape the public key for use in docker-compose
PUBLIC_KEY_ESCAPED=$(echo "$PUBLIC_KEY" | sed 's/\\/\\\\/g' | sed 's/\$/\\$/g')

cat > docker-compose.test-ssh.yml << EOF
version: '3.8'

services:
  ssh-test-1:
    build:
      context: .
      dockerfile: Dockerfile.ssh-test
    container_name: nomanai-ssh-test-1
    hostname: ssh-test-1
    ports:
      - "2222:22"
    command: >
      bash -c "
        mkdir -p /root/.ssh &&
        echo '${PUBLIC_KEY_ESCAPED}' > /root/.ssh/authorized_keys &&
        chmod 700 /root/.ssh &&
        chmod 600 /root/.ssh/authorized_keys &&
        /usr/sbin/sshd -D
      "
    networks:
      - nomanai-test

  ssh-test-2:
    build:
      context: .
      dockerfile: Dockerfile.ssh-test
    container_name: nomanai-ssh-test-2
    hostname: ssh-test-2
    ports:
      - "2223:22"
    command: >
      bash -c "
        mkdir -p /root/.ssh &&
        echo '${PUBLIC_KEY_ESCAPED}' > /root/.ssh/authorized_keys &&
        chmod 700 /root/.ssh &&
        chmod 600 /root/.ssh/authorized_keys &&
        /usr/sbin/sshd -D
      "
    networks:
      - nomanai-test

  ssh-test-3:
    build:
      context: .
      dockerfile: Dockerfile.ssh-test
    container_name: nomanai-ssh-test-3
    hostname: ssh-test-3
    ports:
      - "2224:22"
    command: >
      bash -c "
        mkdir -p /root/.ssh &&
        echo '${PUBLIC_KEY_ESCAPED}' > /root/.ssh/authorized_keys &&
        chmod 700 /root/.ssh &&
        chmod 600 /root/.ssh/authorized_keys &&
        /usr/sbin/sshd -D
      "
    networks:
      - nomanai-test

networks:
  nomanai-test:
    driver: bridge
EOF

# Update Dockerfile to accept public key as build arg
cat > Dockerfile.ssh-test << 'EOF'
FROM ubuntu:24.04

# Install SSH server and basic tools
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    openssh-server \
    sudo \
    curl \
    wget \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Configure SSH
RUN mkdir /var/run/sshd && \
    echo 'root:testpass' | chpasswd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    echo "Port 22" >> /etc/ssh/sshd_config

# Create .ssh directory
RUN mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh

# Expose SSH port
EXPOSE 22

# Start SSH service
CMD ["/usr/sbin/sshd", "-D"]
EOF

echo ""
echo "✓ Setup complete!"
echo ""
echo "To start test SSH containers:"
echo "  docker-compose -f docker-compose.test-ssh.yml up -d"
echo ""
echo "To stop test SSH containers:"
echo "  docker-compose -f docker-compose.test-ssh.yml down"
echo ""
echo "SSH connection details:"
echo "  Container 1: root@localhost:2222 (key: $SSH_KEY_DIR/id_ed25519)"
echo "  Container 2: root@localhost:2223 (key: $SSH_KEY_DIR/id_ed25519)"
echo "  Container 3: root@localhost:2224 (key: $SSH_KEY_DIR/id_ed25519)"
echo ""
echo "Test connection:"
echo "  ssh -i $SSH_KEY_DIR/id_ed25519 -p 2222 root@localhost"
echo ""
echo "Or use with NomanAI:"
echo "  python3 nomanai.py ssh test --host root@localhost:2222 --key $SSH_KEY_DIR/id_ed25519"

