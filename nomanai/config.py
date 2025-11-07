"""
Configuration and constants for NomanAI
"""

import os

APP_NAME = "NomanAI"
CONTAINER = "nomanai-sbx"
IMAGE = "ubuntu:24.04"
TARGET_FILE = "/etc/ssh/sshd_config"

# Option to use systemd-enabled container (requires systemd in Docker)
# Set to True to use jrei/systemd-ubuntu or similar
USE_SYSTEMD_CONTAINER = os.environ.get("NOMANAI_USE_SYSTEMD", "false").lower() == "true"
SYSTEMD_IMAGE = os.environ.get("NOMANAI_SYSTEMD_IMAGE", "jrei/systemd-ubuntu:24.04")

# Policy: allow insecure flips (only when --allow-insecure is passed)
ALLOW_INSECURE = False

# OpenAI configuration
OPENAI_MODEL = os.environ.get("NOMANAI_MODEL", "gpt-4o")
OPENAI_API_MODE = os.environ.get("NOMANAI_API_MODE", "chat")  # default to "chat" for reliability
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")  # optional (Azure/proxy)

# SSH configuration
SSH_MAX_CONNECTIONS_PER_HOST = int(os.environ.get("NOMANAI_SSH_MAX_CONNECTIONS", "5"))
SSH_DEFAULT_TIMEOUT = int(os.environ.get("NOMANAI_SSH_TIMEOUT", "30"))
SSH_KEEPALIVE_INTERVAL = int(os.environ.get("NOMANAI_SSH_KEEPALIVE", "30"))

