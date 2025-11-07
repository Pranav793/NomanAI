#!/usr/bin/env python3
"""
NomanAI — containerized fixer + OpenAI tool-using agent

Quickstart:
  pip install --upgrade openai
  export OPENAI_API_KEY=sk-...
  python3 nomanai.py up
  python3 nomanai.py apply --fix all
  python3 nomanai.py exec -- grep -nE '^(PermitRootLogin|PasswordAuthentication)' /etc/ssh/sshd_config || true
  python3 nomanai.py agent --goal "Disable SSH password auth and disallow root login"
  # test insecure flips (ONLY for testing):
  python3 nomanai.py agent --goal "Enable SSH password auth and allow root login" --allow-insecure
"""

from nomanai.cli import main

if __name__ == "__main__":
    main()

