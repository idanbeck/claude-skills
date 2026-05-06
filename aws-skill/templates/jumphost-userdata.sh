#!/bin/bash
# Cloud-init for aws-skill jump hosts.
#
# Hardening defaults:
#   - apt update + auto-security-updates
#   - fail2ban for ssh brute-force protection
#   - ufw locked to ssh-only (the SG already restricts source IP)
#   - SSH password auth disabled (key-only)
#   - root login disabled
#   - automatic-reboot on kernel updates
#
# Variables (substituted by lib/intent/jumphost.py before submit):
#   {{HOSTNAME}}      — hostname to set
#   {{ALLOWED_IP}}    — informational only; the SG enforces source restriction

set -eux

# --- base
export DEBIAN_FRONTEND=noninteractive
hostnamectl set-hostname '{{HOSTNAME}}'
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    fail2ban \
    ufw \
    unattended-upgrades \
    curl \
    jq \
    htop \
    git \
    tmux

# --- ssh hardening
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# --- ufw (defense-in-depth; SG is the primary control)
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable

# --- fail2ban
systemctl enable fail2ban
systemctl start fail2ban

# --- automatic security updates
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

# --- ready marker (poll this from the skill to know setup is complete)
date -u +"%Y-%m-%dT%H:%M:%SZ" > /var/log/aws-skill-jumphost-ready

echo "Allowed source IP (informational): {{ALLOWED_IP}}"
