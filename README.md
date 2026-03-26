# rconfig Fortigate Bridge

> **Fortigate 完整備份檔轉存模組 - 補足 rconfig 缺少的 metadata 支援**

## 專案說明

### 問題背景

rconfig 透過 SSH 執行 `show full-configuration` 備份 Fortigate，但輸出的純文字配置**缺少關鍵 metadata**：

```bash
# rconfig 無法取得這些 metadata
#config-version=FG201F-7.4.9-FW-build2829-250924:opmode=0:vdom=0:user=daemon_admin
#conf_file_ver=16611773863624424
#buildno=2829
#global_vdom=1
```

**沒有這些 metadata，Fortigate 無法正確恢復配置檔**

### 解決方案

本專案作為 rconfig 的擴充模組，專門處理 Fortigate 完整備份檔：

1. **SFTP 接收**：Fortigate 透過 `execute backup config sftp` 上傳完整備份檔（包含 metadata）
2. **自動轉存**：Watcher 監控上傳目錄，自動轉存到 rconfig 指定位置
3. **無縫整合**：覆蓋 rconfig 原本的文字備份，使用者可直接在 rconfig UI 下載完整備份

---

## 系統架構

```
+--------------------------------------------------+
|         rconfig 主機 (Ubuntu 22.04)              |
|                                                  |
|  +--------------------------------------------+ |
|  |  rconfig Fortigate Bridge (Docker)          | |
|  |  Network: 192.168.254.0/24                  | |
|  |                                             | |
|  |  +----------+       +------------------+   | |
|  |  |  SFTP    |       |  Watcher         |   | |
|  |  |  :2222   |------>|  (Python)        |   | |
|  |  +----------+ 上傳  |  - 監控上傳目錄  |   | |
|  |                      |  - 查詢 rconfig  |   | |
|  |                      |  - 轉存備份檔    |   | |
|  |                      +------------------+   | |
|  +--------------------------------------------+ |
|                          |                       |
|                          v 轉存到                |
|  +--------------------------------------------+ |
|  |  /var/www/html/rconfig/storage/app/         | |
|  |    rconfig/data/FortigateFirewalls/          | |
|  |      {設備名稱}/{YYYY}/{Mon}/{DD}/           | |
|  |        show_{HHmm}.txt       (rconfig 格式) | |
|  |        {原始檔名}.conf       (完整備份)      | |
|  +--------------------------------------------+ |
+--------------------------------------------------+
            ^
            | SFTP Upload (Port 2222)
            |
    +----------------+
    |  Fortigate     |
    |  (11 台)       |
    |                |
    |  Automation Action:
    |  execute backup config sftp
    |    upload/{hostname}-{ip}-%%date%%.conf
    |    172.16.5.124:2222 autoinfra
    +----------------+
```

---

## 設備清單

### 運作中 (11 台)

| 區域 | rconfig 設備名稱 | IP | Fortigate 型號 |
|------|-----------------|-----|---------------|
| 台灣彰化 HQ2 | TWCH-HQ2-101F | 172.16.11.2 | FortiGate 101F |
| 台灣彰化 HQ2 | TWCH-HQ2-201F-01 | 172.16.11.3 | FortiGate 201F |
| 台灣彰化 HQ2 | TWCH-PCN-301E | 172.16.11.4 | FortiGate 301E |
| 台灣彰化 HQ2 | TWCH-HQ2-60E-IOT | 172.16.11.5 | FortiGate 60E |
| 台灣台中 | TWTC-PA-101F | 172.23.127.9 | FortiGate 101F |
| 台灣台中 | TW-TC-FortiGate-121G | 172.23.174.9 | FortiGate 121G |
| 台灣台中 | TW-TC-UAIC-FW | 172.23.199.251 | FortiGate |
| 台灣台北 | TW-TP-BaoYu-FortiGate60E | 172.23.94.9 | FortiGate 60E |
| 台灣台北 | TW-TP-XinYi-FortiGate60E | 172.23.110.30 | FortiGate 60E |
| 印度 | IN-Kavin-60E | 172.25.128.254 | FortiGate 60E |
| 印度 | IN-VSP-60E | 172.25.136.254 | FortiGate 60E |

### 已下架

- IN-KK-60E
- TW-CH-PCN-Firewall
- TW-CH-PGT-Fortigate60E
- TW-TC-FortiGate301E
- TWTC-HQ-60E-IOT

---

## 快速開始

### 前置需求

- Ubuntu 22.04 LTS
- Docker 20.10+
- Docker Compose V2 (`docker compose`，非 `docker-compose`)
- rconfig 已安裝且運作中

### Step 1: 克隆專案

```bash
cd /opt
sudo git clone https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
cd DEV-rconfig-fortigate-bridge
```

### Step 2: 配置環境變數

```bash
# 建立 .env 檔案
sudo nano .env
```

**必要參數**：
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

> **注意**：`RCONFIG_DB_HOST` 必須使用 Docker 橋接網路閘道 IP (`192.168.254.1`)，不能用 `localhost`。

### Step 3: MariaDB 授權 Docker 容器連線

```bash
sudo mysql -u root
```

```sql
GRANT ALL PRIVILEGES ON rconfig.* TO 'pcc_rconfig'@'192.168.254.%' IDENTIFIED BY '<密碼>';
FLUSH PRIVILEGES;
```

### Step 4: 設定 UFW 防火牆

```bash
# Docker 容器存取 MariaDB
sudo ufw allow from 192.168.254.0/24 to any port 3306 proto tcp comment 'Docker bridge to MariaDB'

# Fortigate SFTP 白名單
sudo bash << 'SCRIPT'
IPS=(
    "172.16.11.2" "172.16.11.3" "172.16.11.4" "172.16.11.5"
    "172.23.127.9" "172.23.174.9" "172.23.199.251"
    "172.23.94.9" "172.23.110.30"
    "172.25.128.254" "172.25.136.254"
)
for ip in "${IPS[@]}"; do
    ufw allow from $ip to any port 2222 proto tcp comment "Fortigate $ip"
done
SCRIPT
```

### Step 5: 啟動服務

```bash
sudo docker compose up -d --build

# 檢查服務狀態
sudo docker compose ps
sudo docker compose logs -f watcher
```

**預期輸出**：
```
rconfig Fortigate Bridge - Watcher 啟動
已連線到 rconfig 資料庫
Watcher 已啟動，開始監控 SFTP 上傳...
```

---

## Fortigate 設定

### 檔名格式

Fortigate Automation Action 的 CLI 檔名必須遵循以下格式：

```
upload/{rconfig設備名稱}-{IP用破折號分隔}-%%date%%.conf
```

**Fortigate 會自動加上序列號前綴**（如 `FG201FT922913515_`），Watcher 會自動去除。

**`%%date%%` 展開格式**：`YYYY-MM-DD`（例如 `2026-03-24`）

### Automation Action CLI 指令 (11 台)

Daily config.conf backup

Daily backup at 2000 sch.

Exec sftp daily backup

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

Daily config.conf backup

Daily backup at 2000 sch.

Exec sftp daily backup

#### 台灣台中 (172.23.x.x)

```bash
# TWTC-PA-101F (172.23.127.9)
execute backup config sftp upload/TWTC-PA-101F-172-23-127-9-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TW-TC-FortiGate-121G (172.23.174.9)
execute backup config sftp upload/TW-TC-FortiGate-121G-172-23-174-9-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TW-TC-UAIC-FW (172.23.199.251)
execute backup config sftp upload/TW-TC-UAIC-FW-172-23-199-251-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

Daily config.conf backup

Daily backup at 2000 sch.

Exec sftp daily backup

#### 台灣台北 (172.23.x.x)

```bash
# TW-TP-BaoYu-FortiGate60E (172.23.94.9)
execute backup config sftp upload/TW-TP-BaoYu-FortiGate60E-172-23-94-9-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# TW-TP-XinYi-FortiGate60E (172.23.110.30)
execute backup config sftp upload/TW-TP-XinYi-FortiGate60E-172-23-110-30-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

Daily config.conf backup

Daily backup at 2000 sch.

Exec sftp daily backup

#### 印度 (172.25.x.x)

```bash
# IN-Kavin-60E (172.25.128.254)
execute backup config sftp upload/IN-Kavin-60E-172-25-128-254-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC

# IN-VSP-60E (172.25.136.254)
execute backup config sftp upload/IN-VSP-60E-172-25-136-254-%%date%%.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

### Automation Action 設定方式

在每台 Fortigate 的 Web UI 中：

1. **Security Fabric** > **Automation** > **Create New**
2. **Trigger**: Schedule (每日排程)
3. **Action**: CLI Script
4. 貼上對應的 `execute backup config sftp ...` 指令

> **注意**：`%%date%%` 變數僅在 Automation Action 中展開，手動 CLI 執行不會展開。

### 手動測試 SFTP 連線

```bash
# 在 Fortigate CLI 手動測試（使用硬編碼日期）
execute backup config sftp upload/TWCH-HQ2-201F-01-172-16-11-3-20260324.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

**成功訊息**：
```
Please wait...
Connect to sftp server 172.16.5.124:2222 ...
Backup config file to 172.16.5.124 via sftp successfully.
```

---

## 檔名解析邏輯

Watcher 使用**反向解析**策略處理檔名：

```
原始檔名: FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf
          |_______________|  |______________|  |__________|  |________|
          序列號前綴(自動去除) hostname        IP(破折號)    %%date%%

解析順序（從後向前）：
1. 去除序列號前綴 (FG/FW/FL/FT 開頭 + 底線)
2. 識別 timestamp：格式 A (20260324) 或 格式 B (2026-03-24)
3. 取 4 段數字作為 IP (每段 <= 3 位)
4. 剩餘部分 = hostname (用於查詢 rconfig 資料庫)
```

**支援的檔名格式**：
| 格式 | 範例 | 來源 |
|------|------|------|
| 格式 A | `TWCH-HQ2-201F-01-172-16-11-3-20260324.conf` | 手動 CLI |
| 格式 B | `TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf` | Automation Action `%%date%%` |
| 含前綴 | `FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf` | Fortigate 自動加上 |

---

## 轉存結果

每次備份產生兩個檔案，存放於 rconfig 目錄結構中：

```
/var/www/html/rconfig/storage/app/rconfig/data/
  FortigateFirewalls/
    TWCH-HQ2-201F-01/
      2026/
        Mar/
          24/
            show_0625.txt                                           <-- rconfig 格式（覆蓋）
            FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf  <-- 原始備份（保留）
```

- **`show_{HHmm}.txt`**：rconfig 可辨識的格式，同日同時間會覆蓋
- **原始 `.conf` 檔**：完整保留 Fortigate 原始備份，含序列號前綴

---

## 目錄結構

```
DEV-rconfig-fortigate-bridge/
├── docker-compose.yml          # Docker 服務編排
├── .env                        # 環境變數配置（不提交 Git）
├── .env.example                # 環境變數範本
├── README.md                   # 本文件
├── DEPLOYMENT_PROGRESS.md      # 部署進度追蹤
├── watcher/                    # Watcher 服務
│   ├── Dockerfile
│   ├── requirements.txt        # Python 依賴
│   └── bridge.py               # 核心轉存邏輯
├── scripts/
│   └── setup-ufw-fortigate.sh  # UFW 防火牆設定腳本
├── ssh_keys/                   # SSH 金鑰目錄
├── data/
│   └── INCOMING_TEMP/          # SFTP 上傳暫存目錄
│       └── failed/             # 處理失敗的檔案
└── logs/                       # Watcher 日誌
    └── watcher.log
```

---

## 驗證測試

### 1. 檢查 Docker 服務

```bash
sudo docker compose ps

# 預期輸出
NAME                     STATE     PORTS
rconfig-bridge-sftp      Up        0.0.0.0:2222->22/tcp
rconfig-bridge-watcher   Up
```

### 2. 檢查 Watcher 日誌

```bash
sudo docker compose logs watcher --tail 20
```

**成功處理範例**：
```
📥 開始處理: FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf
   去除序列號前綴: FG201FT922913515
   設備名稱: TWCH-HQ2-201F-01
   時間戳記: 20260324
   設備 ID: 4
   rconfig 檔案: show_0625.txt
   備份檔案: FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf
✅ 已轉存為 rconfig 格式: show_0625.txt
✅ 已保留原始備份: FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf
```

### 3. 檢查轉存結果

```bash
# 查看轉存目錄
ls -lh /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/2026/Mar/24/

# 驗證 metadata
head -5 /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/2026/Mar/24/show_0625.txt
```

**預期輸出（包含 metadata）**：
```
#config-version=FG201F-7.4.9-FW-build2829-250924:opmode=0:vdom=0:user=daemon_admin
#conf_file_ver=16611773863624424
#buildno=2829
#global_vdom=1
config system global
```

---

## 故障排除

### Watcher 無法連線到資料庫

```
無法連線到 rconfig 資料庫: (2003, "Can't connect to MySQL server...")
```

**原因**：Docker 容器的 `localhost` 是容器自身，不是主機。

**解決**：
```bash
# 確認 .env 中 DB_HOST 設為 Docker 橋接閘道
grep RCONFIG_DB_HOST .env
# 應為: RCONFIG_DB_HOST=192.168.254.1

# 確認 MariaDB 已授權 Docker 網段
sudo mysql -u root -e "SELECT host, user FROM mysql.user WHERE user='pcc_rconfig';"
# 應包含: 192.168.254.%

# 更新 .env 後必須 recreate（restart 不會重載 .env）
sudo docker compose up -d
```

### 找不到設備

```
找不到設備: HQ2-201F
```

**原因**：Automation Action CLI 的檔名 hostname 與 rconfig 設備名稱不一致。

**解決**：確保檔名中的 hostname 部分完全等於 rconfig 的 `device_name`。

```bash
# 查詢 rconfig 設備名稱
mysql -u pcc_rconfig -p rconfig -e "SELECT id, device_name FROM devices;"
```

### 檔案移至 failed 目錄

```bash
# 查看錯誤原因
cat data/INCOMING_TEMP/failed/*.error.txt

# 常見原因：
# - 檔名格式不符（缺少 IP 或 timestamp）
# - 設備名稱不存在於 rconfig
# - %%date%% 未展開（手動 CLI 不支援，僅 Automation Action 支援）
```

---

## 監控與維運

### 日誌查看

```bash
# 即時監控
sudo docker compose logs -f watcher

# 查看歷史日誌
tail -100 logs/watcher.log
```

### 服務管理

```bash
# 重啟所有服務
sudo docker compose restart

# 更新程式碼後重建
cd /opt/DEV-rconfig-fortigate-bridge
sudo git pull
sudo docker compose up -d --build
```

### 清理失敗檔案

```bash
# 檢查 failed 目錄
ls -lh data/INCOMING_TEMP/failed/

# 清理 7 天前的失敗檔案
find data/INCOMING_TEMP/failed/ -type f -mtime +7 -delete
```

---

## 安全性

1. **UFW 防火牆**：SFTP Port 2222 僅允許白名單 IP 連入
2. **Docker 網路隔離**：使用自訂橋接網路 `192.168.254.0/24`
3. **SFTP 帳號隔離**：`autoinfra` 帳號僅用於 SFTP 上傳，與主機帳號獨立
4. **`.env` 檔案權限**：`chmod 600 .env` 僅 root 可讀

---

## FAQ

### Q1: 是否需要修改 rconfig 程式碼？

不需要。本專案僅轉存檔案到 rconfig 目錄，rconfig 無需任何修改。

### Q2: `%%date%%` 在手動 CLI 不展開？

正常。`%%date%%` 僅在 Fortigate Automation Action 中展開為 `YYYY-MM-DD`。手動測試請使用硬編碼日期（如 `20260324`）。

### Q3: Fortigate 自動加的序列號前綴會影響嗎？

不會。Watcher 會自動去除 `FG`/`FW`/`FL`/`FT` 開頭的序列號前綴（如 `FG201FT922913515_`）。

### Q4: 兩台 Fortigate 同時上傳會衝突嗎？

不會。每台設備的 hostname 不同，會存入各自的 rconfig 目錄。

---

**最後更新**: 2026-03-24
**適用 rconfig 版本**: v6.x
**適用 Fortigate 版本**: 7.x (含以上)
**部署目標**: stwrconfig6 (172.16.5.124)
