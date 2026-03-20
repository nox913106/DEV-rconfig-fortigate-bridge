#!/bin/bash
# ==========================================
# UFW 批次設定 - 允許 Fortigate IP 存取 SFTP (Port 2222)
# ==========================================

set -e

echo "🔥 開始設定 UFW 規則..."

# 定義 Fortigate IP 清單
FORTIGATE_IPS=(
    "172.16.11.2"
    "172.16.11.3"
    "172.16.11.4"
    "172.16.11.5"
    "172.23.13.9"
    "172.23.174.9"
    "172.23.127.9"
    "172.23.199.251"
    "172.23.94.9"
    "172.23.110.30"
    "10.240.29.254"
    "10.240.13.4"
)

# 計數器
count=0

# 批次新增規則
for ip in "${FORTIGATE_IPS[@]}"; do
    count=$((count + 1))
    echo "[$count/${#FORTIGATE_IPS[@]}] 新增規則: $ip → Port 2222"
    sudo ufw allow from $ip to any port 2222 proto tcp comment "Fortigate $ip"
done

echo ""
echo "✅ 已新增 ${#FORTIGATE_IPS[@]} 條 UFW 規則"
echo ""
echo "📋 檢查規則："
sudo ufw status numbered | grep 2222

echo ""
echo "🎯 完成！所有 Fortigate IP 已允許存取 Port 2222"
