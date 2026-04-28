# rconfig Fortigate Bridge — 部屬操作說明

> **適用對象**: 接手維運或在新主機重新部屬的工程師
> **最後更新**: 2026-04-08
> **部屬主機**: stwrconfig6 (172.16.5.124), Ubuntu 22.04

---

## 目錄

1. [系統概覽](#1-系統概覽)
2. [rconfig 主機部屬](#2-rconfig-主機部屬)
3. [Fortigate：路由設定（preferred-source）](#3-forgateroute--preferred-source)
4. [Fortigate：Automation Action 設定](#4-fortigate-automation-action-設定)
5. [部屬後驗證](#5-部屬後驗證)
6. [雷區預防與常見陷阱](#6-雷區預防與常見陷阱)
7. [日常維運指令](#7-日常維運指令)

---

## 1. 系統概覽

```
Fortigate (遠端，11 台)
  │
  │  execute backup config sftp
  │  檔名格式: upload/{hostname}-{IP用破折號}-%%date%%.conf
  │  Fortigate 會自動加序列號前綴，例如: FG201FT922913515_
  │
  ▼ Port 2222 (SFTP)
stwrconfig6 (172.16.5.124)
  └── Docker: rconfig-bridge-sftp    ← 接收備份檔
  └── Docker: rconfig-bridge-watcher ← 自動轉存到 rconfig 目錄
  └── Docker: rconfig-bridge-web     ← 備份瀏覽器 (Port 8882)

轉存位置:
  /var/www/html/rconfig/storage/app/rconfig/data/
    FortigateFirewalls/{hostname}/{YYYY}/{Mon}/{DD}/
      show_1930.txt          (rconfig 可讀格式)
      {原始序列號前綴}_{原始檔名}.conf  (完整備份含 metadata)

備份瀏覽器:
  http://172.16.5.124:8882
  - 設備列表、月曆視圖、備份下載
  - 支援繁中 / 簡中 / 英文 三語系
```

**為什麼需要這套系統**：rconfig 原本用 SSH `show full-configuration` 備份 Fortigate，輸出缺少 `#config-version`、`#buildno` 等 metadata，導致無法正確恢復配置。本系統透過 SFTP 接收 Fortigate 原生備份（含 metadata），再轉存到 rconfig 目錄，覆蓋 rconfig 的文字備份。

---

## 2. rconfig 主機部屬

### 2-1. 前置確認

```bash
# 確認 Docker 版本 (需 >= 20.10)
docker --version

# 確認 Docker Compose V2（注意：是 "docker compose"，沒有破折號）
docker compose version

# 確認 rconfig 目錄存在
ls /var/www/html/rconfig/storage/app/rconfig/data/
```

> **⚠️ 雷區**: 舊系統可能只有 `docker-compose`（V1），本專案使用 V2 語法，兩者不相容。

### 2-2. 克隆專案

```bash
cd /opt
sudo git clone https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
cd DEV-rconfig-fortigate-bridge
```

### 2-3. 建立 .env 環境變數

```bash
sudo nano .env
```

填入以下內容（密碼依實際環境填寫）：

```bash
RCONFIG_DB_HOST=192.168.254.1
RCONFIG_DB_PORT=3306
RCONFIG_DB_NAME=rconfig
RCONFIG_DB_USER=pcc_rconfig
RCONFIG_DB_PASSWORD=<rconfig 資料庫密碼>
RCONFIG_PATH=/var/www/html/rconfig
SFTP_PORT=2222
LOG_LEVEL=INFO
```

```bash
# 保護密碼，僅 root 可讀
sudo chmod 600 .env
```

> **⚠️ 雷區**: `RCONFIG_DB_HOST` **必須填 `192.168.254.1`**（Docker 橋接網路閘道），不能填 `localhost`。填 `localhost` 表示容器自身，DB 連線必然失敗。

### 2-4. MariaDB 授權 Docker 容器連線

Docker 容器的 IP 屬於 `192.168.254.0/24` 網段，預設 MariaDB 不允許此網段連線：

```bash
sudo mysql -u root
```

```sql
-- 授權 Docker 橋接網段
GRANT ALL PRIVILEGES ON rconfig.* TO 'pcc_rconfig'@'192.168.254.%' IDENTIFIED BY '<密碼>';
FLUSH PRIVILEGES;

-- 驗證授權
SELECT host, user FROM mysql.user WHERE user='pcc_rconfig';
-- 預期看到 192.168.254.%
```

### 2-5. 設定 UFW 防火牆

```bash
# Docker 容器存取 MariaDB (Port 3306)
sudo ufw allow from 192.168.254.0/24 to any port 3306 proto tcp comment 'Docker bridge to MariaDB'

# Fortigate SFTP 上傳白名單 (Port 2222)
sudo bash << 'SCRIPT'
IPS=(
    "172.16.11.2"    # TWCH-HQ2-101F
    "172.16.11.3"    # TWCH-HQ2-201F-01
    "172.16.11.4"    # TWCH-PCN-301E
    "172.16.11.5"    # TWCH-HQ2-60E-IOT
    "172.23.127.9"   # TWTC-PA-101F
    "172.23.174.9"   # TW-TC-FortiGate-121G
    "172.23.199.251" # TW-TC-UAIC-FW
    "172.23.94.9"    # TW-TP-BaoYu-FortiGate60E
    "172.23.110.30"  # TW-TP-XinYi-FortiGate60E
    "172.25.128.254" # IN-Kavin-60E
    "172.25.136.254" # IN-VSP-60E
)
for ip in "${IPS[@]}"; do
    ufw allow from $ip to any port 2222 proto tcp comment "Fortigate $ip"
done
SCRIPT

# 確認規則
sudo ufw status | grep 2222
```

> **新增設備時**: 只需在此清單加入新 IP，執行單條 `ufw allow from <新IP> to any port 2222 proto tcp`。

### 2-6. 啟動服務

```bash
cd /opt/DEV-rconfig-fortigate-bridge

# 首次啟動（需 build watcher image）
sudo docker compose up -d --build

# 確認服務狀態
sudo docker compose ps
```

**預期輸出**：
```
NAME                     STATUS    PORTS
rconfig-bridge-sftp      Up        0.0.0.0:2222->22/tcp
rconfig-bridge-watcher   Up
rconfig-bridge-web       Up        0.0.0.0:8882->5000/tcp
```

```bash
# 確認 Watcher 成功連上 DB
sudo docker compose logs watcher --tail 20
```

**預期日誌**：
```
rconfig Fortigate Bridge - Watcher 啟動
已連線到 rconfig 資料庫
Watcher 已啟動，開始監控 SFTP 上傳...
```

> **⚠️ 雷區**: 修改 `.env` 後，`docker compose restart` **不會重載 `.env`**，必須用 `docker compose up -d` 才會重新讀取。

---

## 3. Fortigate 路由設定（preferred-source）

### 3-1. 問題背景

Fortigate 執行 `execute backup config sftp` 屬於**管理平面 local-out traffic**，來源 IP 預設使用**出口介面的 IP**。遠端 Fortigate 透過 internet IPSec VPN 連回 HQ2 時，出口介面通常是 WAN 介面，來源 IP 變成**公網 IP**，導致：

1. HQ2 RPF (Reverse Path Forwarding) 驗證失敗 → DROP
2. 就算 RPF 通過，HQ2 防火牆政策無匹配公網 IP 的規則 → DROP

**解法 (FortiOS >= 7.4.0)**: 在遠端 Fortigate 加一條 static route，指定 `preferred-source` 為**內網管理 IP**，強制 local-out 流量使用內網 IP 作為來源。

### 3-2. 各台設定指令（僅遠端 Fortigate 需設定，HQ2 不動）

#### HQ2 本地 4 台（172.16.11.x）— 不需要設定

HQ2 本地設備與 stwrconfig6 同網段，local-out 來源 IP 本就是內網 IP，無需設定 preferred-source。

#### 台中 leased line — TW-TC-FortiGate-121G — 不需要設定

leased line 專線隧道的介面 IP 是內網 IP (172.23.175.175)，同樣無問題。

#### 需要設定的 6 台（internet IPSec VPN）

登入各台 Fortigate CLI，依序執行：

```
# TWTC-PA-101F (172.23.127.9)
config router static
    edit <下一個可用 ID>
        set dst 172.16.5.124 255.255.255.255
        set device "<指向 HQ2 的 tunnel 介面名稱>"
        set preferred-source 172.23.127.9
    next
end

# TW-TC-UAIC-FW (172.23.199.251)  ← 已完成，可參考
config router static
    edit 120
        set dst 172.16.5.124 255.255.255.255
        set device "UAIC-PCCTW1"
        set preferred-source 172.23.199.251
    next
end

# TW-TP-BaoYu-FortiGate60E (172.23.94.9)
config router static
    edit <下一個可用 ID>
        set dst 172.16.5.124 255.255.255.255
        set device "<指向 HQ2 的 tunnel 介面名稱>"
        set preferred-source 172.23.94.9
    next
end

# TW-TP-XinYi-FortiGate60E (172.23.110.30)
config router static
    edit <下一個可用 ID>
        set dst 172.16.5.124 255.255.255.255
        set device "<指向 HQ2 的 tunnel 介面名稱>"
        set preferred-source 172.23.110.30
    next
end

# IN-Kavin-60E (172.25.128.254)
config router static
    edit <下一個可用 ID>
        set dst 172.16.5.124 255.255.255.255
        set device "<指向 HQ2 的 tunnel 介面名稱>"
        set preferred-source 172.25.128.254
    next
end

# IN-VSP-60E (172.25.136.254)
config router static
    edit <下一個可用 ID>
        set dst 172.16.5.124 255.255.255.255
        set device "<指向 HQ2 的 tunnel 介面名稱>"
        set preferred-source 172.25.136.254
    next
end
```

### 3-3. 查詢可用的 tunnel 介面名稱

在各台 Fortigate 上執行：

```
# 查看路由表，找出目的地 172.16.x.x 走哪個介面
get router info routing-table details 172.16.5.124

# 列出所有 IPSec tunnel 介面
get vpn ipsec tunnel summary
```

### 3-4. 設定後驗證

```
# 在遠端 Fortigate 手動觸發備份（用硬編碼日期測試）
execute backup config sftp upload/<設備名>-<IP用破折號>-20260101.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# 若 preferred-source 生效，來源 IP 應為內網管理 IP
# 用 debug flow 確認：
diagnose debug flow filter addr 172.16.5.124
diagnose debug flow filter port 2222
diagnose debug flow trace start 20
diagnose debug enable
# 觸發上方的 execute backup 後觀察輸出
# 預期看到: proto=6, 172.23.x.x:xxxxx->172.16.5.124:2222
diagnose debug flow trace stop
diagnose debug disable
```

> **⚠️ 雷區**: FortiOS < 7.4.0 不支援 `preferred-source`。若設備版本過舊，需採用備選方案（參見 `docs/TROUBLESHOOTING-SFTP-ROUTING.md` 中的解法 B）。

---

## 4. Fortigate Automation Action 設定

### 4-1. 設定位置

每台 Fortigate Web UI：**Security Fabric > Automation > Create New**

| 欄位 | 值 |
|------|----|
| Name | Daily config.conf backup |
| Trigger Type | Schedule |
| Schedule | 每日 20:00 |
| Action Type | CLI Script |
| Script | 見下方各台指令 |

> Automation Action 描述建議統一填：`Daily backup at 2000 sch.` / `Exec sftp daily backup`

### 4-2. 各台 CLI 指令

#### 台灣彰化 HQ2 (172.16.11.x)

```bash
# TWCH-HQ2-101F (172.16.11.2)
execute backup config sftp upload/TWCH-HQ2-101F-172-16-11-2-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TWCH-HQ2-201F-01 (172.16.11.3)
execute backup config sftp upload/TWCH-HQ2-201F-01-172-16-11-3-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TWCH-PCN-301E (172.16.11.4)
execute backup config sftp upload/TWCH-PCN-301E-172-16-11-4-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TWCH-HQ2-60E-IOT (172.16.11.5)
execute backup config sftp upload/TWCH-HQ2-60E-IOT-172-16-11-5-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

#### 台灣台中 (172.23.x.x)

```bash
# TWTC-PA-101F (172.23.127.9)
execute backup config sftp upload/TWTC-PA-101F-172-23-127-9-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TW-TC-FortiGate-121G (172.23.174.9)
execute backup config sftp upload/TW-TC-FortiGate-121G-172-23-174-9-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TW-TC-UAIC-FW (172.23.199.251)
execute backup config sftp upload/TW-TC-UAIC-FW-172-23-199-251-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

#### 台灣台北 (172.23.x.x)

```bash
# TW-TP-BaoYu-FortiGate60E (172.23.94.9)
execute backup config sftp upload/TW-TP-BaoYu-FortiGate60E-172-23-94-9-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TW-TP-XinYi-FortiGate60E (172.23.110.30)
execute backup config sftp upload/TW-TP-XinYi-FortiGate60E-172-23-110-30-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

#### 印度 (172.25.x.x)

```bash
# IN-Kavin-60E (172.25.128.254)
execute backup config sftp upload/IN-Kavin-60E-172-25-128-254-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# IN-VSP-60E (172.25.136.254)
execute backup config sftp upload/IN-VSP-60E-172-25-136-254-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

### 4-3. 檔名格式說明

```
upload/{rconfig設備名稱}-{IP用破折號替換點}-%%date%%.conf

範例: upload/TWCH-HQ2-201F-01-172-16-11-3-%%date%%.conf
                │                │              │
                rconfig 設備名稱   IP (. 換 -)   日期變數
```

**重要規則**：
- `{rconfig設備名稱}` 必須與 rconfig 資料庫中的 `device_name` **完全一致**（含大小寫）
- IP 中的 `.` 替換為 `-`（破折號）
- `%%date%%` 僅在 Automation Action 中自動展開為 `YYYY-MM-DD`，手動 CLI 執行**不展開**

### 4-4. 手動測試 SFTP 連線

在 Fortigate CLI 手動觸發（不要用 `%%date%%`，改用硬編碼日期）：

```
execute backup config sftp upload/TWCH-HQ2-201F-01-172-16-11-3-20260101.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

**成功回應**：
```
Please wait...
Connect to sftp server 172.16.5.124:2222 ...
Backup config file to 172.16.5.124 via sftp successfully.
```

**失敗回應**：
```
Send config file to sftp server via vdom root failed.
Command fail. Return code -1
```
→ 失敗時先確認 preferred-source 路由有沒有設定，再檢查 UFW 白名單。

---

## 5. 部屬後驗證

### 5-1. 驗證 Docker 服務

```bash
cd /opt/DEV-rconfig-fortigate-bridge
sudo docker compose ps
# 預期: rconfig-bridge-sftp 和 rconfig-bridge-watcher 均為 Up

sudo docker compose logs watcher --tail 30
# 預期: "Watcher 已啟動，開始監控 SFTP 上傳..."
```

### 5-2. 驗證 SFTP 連線

從任一 Fortigate 手動執行備份指令（見 4-4），觀察 Watcher 日誌：

```bash
sudo docker compose logs watcher -f
```

**成功轉存日誌範例**：
```
📥 開始處理: FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf
   去除序列號前綴: FG201FT922913515
   設備名稱: TWCH-HQ2-201F-01
   時間戳記: 20260324
   設備 ID: 4
   rconfig 檔案: show_1930.txt
✅ 已轉存為 rconfig 格式: show_1930.txt
✅ 已保留原始備份: FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf
```

### 5-3. 驗證 rconfig 目錄結構

```bash
# 替換設備名稱和日期
ls -lh /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/

# 驗證 metadata 存在
head -5 /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/2026/Apr/08/show_1930.txt
```

**預期輸出（包含 metadata）**：
```
#config-version=FG201F-7.4.9-FW-build2829-250924:opmode=0:vdom=0:user=daemon_admin
#conf_file_ver=16611773863624424
#buildno=2829
#global_vdom=1
config system global
```

### 5-4. 驗證 rconfig UI

1. 登入 rconfig Web UI
2. 點選任一已備份的 Fortigate 設備
3. 確認最新一筆備份存在
4. 下載備份，確認第 1 行包含 `#config-version=`（表示 metadata 完整）

### 5-5. 驗證 Web 備份瀏覽器

瀏覽器開啟 `http://<主機IP>:8882`，確認：

1. 設備卡片正常顯示，且顯示最新備份日期
2. 點擊設備卡片進入月曆，有備份的日期呈綠色
3. 點擊日期可看到備份檔案清單，下載正常
4. Header 右上角語系切換（繁中 / 简中 / EN）正常運作

```bash
# 若 web 服務未啟動
sudo docker compose logs web --tail 20
```

---

## 6. 雷區預防與常見陷阱

### 雷區一：DB_HOST 不能用 localhost

| 錯誤設定 | 正確設定 |
|---------|---------|
| `RCONFIG_DB_HOST=localhost` | `RCONFIG_DB_HOST=192.168.254.1` |

**原因**: Docker 容器內的 `localhost` 指向容器自身，不是宿主機。需使用 Docker 橋接網路閘道 IP。

**症狀**: Watcher 日誌出現 `Can't connect to MySQL server on 'localhost'`

---

### 雷區二：修改 .env 後要用 up -d，不是 restart

```bash
# 錯誤做法（不重載 .env）
sudo docker compose restart

# 正確做法（重載 .env）
sudo docker compose up -d
```

**原因**: `docker compose restart` 僅重啟容器，不會重新讀取 `.env`。

---

### 雷區三：%%date%% 手動執行不展開

```bash
# 手動測試時不能用 %%date%%，會上傳一個字面上叫 %%date%%.conf 的檔案
# 錯誤：
execute backup config sftp upload/TWCH-HQ2-101F-172-16-11-2-%%date%%.conf ...

# 正確（手動測試用硬編碼日期）：
execute backup config sftp upload/TWCH-HQ2-101F-172-16-11-2-20260408.conf ...
```

**原因**: `%%date%%` 是 Fortigate Automation Action 的特殊變數，僅在排程觸發時展開。

---

### 雷區四：設備名稱必須與 rconfig 完全一致

若 Automation Action 指令中的 hostname 與 rconfig 的 `device_name` 不符，Watcher 找不到設備，檔案會移到 `failed/` 目錄。

```bash
# 查詢 rconfig 中的正確設備名稱
mysql -u pcc_rconfig -p rconfig -e "SELECT id, device_name FROM devices ORDER BY device_name;"
```

**Fortigate 序列號前綴**（FG/FW/FL/FT 開頭）會自動去除，不影響解析：
```
FG201FT922913515_TWCH-HQ2-201F-01-... → hostname: TWCH-HQ2-201F-01
```

---

### 雷區五：遠端 Fortigate preferred-source 未設定

**症狀**: HQ2 本地 4 台備份成功，但 internet VPN 的遠端設備失敗。

**診斷**（在 stwrconfig6 上）：
```bash
sudo tcpdump -i any port 2222 -nn
# 若沒有封包抵達，問題在 Fortigate/HQ2 端
```

**診斷**（在 HQ2 上）：
```
diagnose debug flow filter addr 172.16.5.124
diagnose debug flow filter port 2222
diagnose debug flow trace start 20
diagnose debug enable
# 觀察 src IP，若是公網 IP 表示未設 preferred-source
```

**解法**: 在各遠端 Fortigate 加 preferred-source static route（見第 3 節）。

---

### 雷區六：Docker Compose V1 / V2 指令差異

| V1 (舊，已棄用) | V2 (本專案使用) |
|----------------|----------------|
| `docker-compose up -d` | `docker compose up -d` |
| `docker-compose logs` | `docker compose logs` |
| `docker-compose ps` | `docker compose ps` |

**V1 與本專案的 `docker-compose.yml` 不相容，會報語法錯誤。**

---

### 雷區七：UFW 沒有放行 Docker 橋接網段到 3306

症狀：Watcher 成功啟動但無法連上資料庫（即使 `.env` 設定正確）。

```bash
# 確認 UFW 有放行
sudo ufw status | grep 3306
# 預期: 3306/tcp  ALLOW  192.168.254.0/24
```

---

## 7. 日常維運指令

### 查看服務狀態

```bash
cd /opt/DEV-rconfig-fortigate-bridge

# 服務是否正常運行
sudo docker compose ps

# 即時監控 Watcher 日誌
sudo docker compose logs -f watcher

# 查看最近 50 筆日誌
sudo docker compose logs watcher --tail 50
```

### 重啟服務

```bash
# 一般重啟（保留設定）
sudo docker compose restart

# 修改 .env 或 docker-compose.yml 後（重載設定）
sudo docker compose up -d

# 更新程式碼後重建 image
sudo git pull
sudo docker compose up -d --build

# 僅重建 web 服務（sftp/watcher 不中斷）
sudo docker compose up -d --build web
```

### Web 備份瀏覽器

```bash
# 查看 web 服務狀態
sudo docker compose ps web

# 查看 web 日誌
sudo docker compose logs web --tail 20

# 瀏覽器入口
# http://<主機IP>:8882
```

### 查看失敗的備份

```bash
# 列出失敗檔案
ls -lh /opt/DEV-rconfig-fortigate-bridge/data/INCOMING_TEMP/failed/

# 查看錯誤原因
cat /opt/DEV-rconfig-fortigate-bridge/data/INCOMING_TEMP/failed/*.error.txt

# 清理 7 天前的失敗檔案
find /opt/DEV-rconfig-fortigate-bridge/data/INCOMING_TEMP/failed/ -type f -mtime +7 -delete
```

### 新增設備流程（SOP）

1. **rconfig UI** 新增設備（確認 `device_name`）
2. **stwrconfig6 UFW** 新增白名單：
   ```bash
   sudo ufw allow from <新設備IP> to any port 2222 proto tcp comment "Fortigate <新設備名>"
   ```
3. **新設備 Fortigate CLI** 加 preferred-source 路由（如需，見第 3 節）
4. **新設備 Fortigate Web UI** 建立 Automation Action（見第 4 節）
5. **手動測試** SFTP 連線成功後，等待排程自動執行

---

**文件作者**: Max Fung (max.fung@pouchen.com)
**相關文件**: `docs/TROUBLESHOOTING-SFTP-ROUTING.md`（三種路由解法詳細分析）