#!/bin/bash
# setup-server.sh
# Run this once on a fresh Ubuntu 22.04/24.04 Hetzner server as root
# Usage: bash setup-server.sh

set -e

echo "==> Updating system packages..."
apt-get update && apt-get upgrade -y

echo "==> Installing Docker..."
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

echo "==> Enabling Docker on boot..."
systemctl enable docker
systemctl start docker

echo "==> Creating deploy user..."
useradd -m -s /bin/bash deploy || echo "User 'deploy' already exists"
usermod -aG docker deploy

echo "==> Setting up SSH for deploy user..."
mkdir -p /home/deploy/.ssh
# Copy root's authorized_keys so your existing SSH key works for deploy user too
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys 2>/dev/null || true
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

echo "==> Configuring firewall (ufw)..."
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo ""
echo "✅ Server setup complete!"
echo "   - Docker installed and running"
echo "   - Deploy user created (with docker access)"
echo "   - Firewall: SSH, 80, 443 open"
echo ""
echo "Next step: SSH in as deploy and clone your repo:"
echo "  ssh deploy@<your-server-ip>"