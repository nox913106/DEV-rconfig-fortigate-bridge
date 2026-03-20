# rconfig Fortigate Bridge

> **Fortigate 完整備份檔轉存模組 - 補足 rconfig 缺少的 metadata 支援**

## 📖 專案說明

### 問題背景

rconfig 透過 SSH 執行 `show full-configuration` 備份 Fortigate，但輸出的純文字配置**缺少關鍵 metadata**：

```bash
# ❌ rconfig 無法取得這些 metadata
#config-version=FG201F-7.4.9-FW-build2829-250924:opmode=0:vdom=0:user=Tacacs_admin
#conf_file_ver=16609656444747006
#buildno=2829
#global_vdom=1
```

**沒有這些 metadata，Fortigate 無法正確恢復配置檔** ⚠️

### 解決方案

本專案作為 rconfig 的擴充模組，專門處理 Fortigate 完整備份檔：

1. **SFTP 接收**：Fortigate 透過 `execute backup config sftp` 上傳完整備份檔（包含 metadata）
2. **自動轉存**：Watcher 監控上傳目錄，自動轉存到 rconfig 指定位置
3. **無縫整合**：覆蓋 rconfig 原本的文字備份，使用者可直接在 rconfig UI 下載完整備份

---

## 🏗️ 系統架構

```
┌──────────────────────────────────────────────────┐
│         rconfig 主機 (Ubuntu 22.04)              │
│                                                  │
│  ┌────────────────────────────────────────────┐ │
│  │  rconfig Fortigate Bridge (Docker)        │ │
│  │                                            │ │
│  │  ┌──────────┐       ┌──────────────────┐  │ │
│  │  │  SFTP    │       │  Watcher         │  │ │
│  │  │  :2222   │──────▶│  (Python)        │  │ │
│  │  └──────────┘ 上傳  │  - 監控上傳目錄  │  │ │
│  │                      │  - 查詢 rconfig  │  │ │
│  │                      │  - 轉存備份檔    │  │ │
│  │                      └──────────────────┘  │ │
│  └────────────────────────────────────────────┘ │
│                          │                       │
│                          ▼ 轉存到                │
│  ┌────────────────────────────────────────────┐ │
│  │  /var/www/html/rconfig/storage/app/        │ │
│  │    rconfig/data/FortigateFirewalls/        │ │
│  │      {設備名稱}/{年}/{月}/{日}/             │ │
│  │        showrunning-config_{ID}.conf        │ │
│  └────────────────────────────────────────────┘ │
│                                                  │
│  ┌────────────────────────────────────────────┐ │
│  │  rconfig (既有系統)                         │ │
│  │  - Reader 讀取完整備份檔                    │ │
│  │  - 下載功能支援 .conf 檔案                  │ │
│  └────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
            ▲
            │ SFTP Upload (Port 2222)
            │
    ┌───────┴────────┐
    │  Fortigate     │
    │  (10 台)       │
    │                │
    │  execute backup config sftp
    │    fw01-192.168.1.1-20260320.conf
    └────────────────┘
```

---

## 🚀 快速開始

### 前置需求

- ✅ Ubuntu 22.04 LTS
- ✅ Docker 20.10+
- ✅ Docker Compose 2.0+
- ✅ rconfig 已安裝且運作中

### Step 1: 克隆專案

```bash
# 在 rconfig 主機上執行
cd /opt
git clone https://github.com/yourusername/rconfig-fortigate-bridge.git
cd rconfig-fortigate-bridge
```

### Step 2: 配置環境變數

```bash
# 複製範本
cp .env.example .env

# 編輯配置（重要！）
nano .env
```

**必須修改的參數**：
```bash
# rconfig 資料庫密碼（從 /var/www/html/rconfig/.env 取得）
RCONFIG_DB_PASSWORD=maWH5iv7DECFtc6u  # 改成實際密碼

# rconfig 安裝路徑（預設通常正確）
RCONFIG_PATH=/var/www/html/rconfig
```

### Step 3: 設定 SSH 公鑰認證

```bash
# 產生 SSH 金鑰對
ssh-keygen -t rsa -b 4096 -f ./ssh_keys/fortigate_rsa -N ""

# 顯示公鑰（稍後需複製到 Fortigate）
cat ./ssh_keys/fortigate_rsa.pub
```

**輸出範例**：
```
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC... root@host
```

### Step 4: 啟動服務

```bash
# 建置並啟動 Docker 容器
docker-compose up -d

# 檢查服務狀態
docker-compose ps
docker-compose logs -f watcher
```

**預期輸出**：
```
✅ rconfig Fortigate Bridge - Watcher 啟動
✅ 已連線到 rconfig 資料庫
✅ Watcher 已啟動，開始監控 SFTP 上傳...
```

---

## 🔧 Fortigate 設定

### Step 1: 設定 SSH 公鑰認證

```bash
# 在 Fortigate CLI 執行
config system admin
    edit "sftp-backup"
        set ssh-public-key1 "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC..."
        set accprofile "super_admin"
    next
end
```

### Step 2: 測試 SFTP 連線

```bash
# 在 Fortigate CLI 執行
execute backup config sftp test-backup.conf <rconfig-ip>:2222 sftp-backup
```

**成功訊息**：
```
Please wait...
Connect to ftp server <rconfig-ip>:2222 ...
Backup config file to <rconfig-ip> via ftp successfully.
```

### Step 3: 設定自動排程

```bash
# 在 Fortigate CLI 執行（每日 02:00 備份）
config system auto-script
    edit "daily-config-backup"
        set interval 86400
        set start auto
        set script "execute backup config sftp fw01-$(FGT_SERIAL_NUMBER)-$(FGT_HOSTNAME)-$(TIMESTAMP).conf <rconfig-ip>:2222 sftp-backup"
    next
end
```

**檔名格式要求**：
```
✅ fw01-192.168.1.1-20260320-143000.conf
❌ backup.conf (無法解析設備資訊)
```

---

## 📂 目錄結構

```
rconfig-fortigate-bridge/
├── docker-compose.yml          # Docker 服務編排
├── .env.example                # 環境變數範本
├── .env                        # 實際配置（不提交 Git）
├── README.md                   # 本文件
├── watcher/                    # Watcher 服務
│   ├── Dockerfile
│   ├── requirements.txt        # Python 依賴
│   └── bridge.py               # 核心轉存邏輯
├── ssh_keys/                   # SSH 公鑰目錄
│   ├── fortigate_rsa           # 私鑰（僅伺服器持有）
│   └── fortigate_rsa.pub       # 公鑰（複製到 Fortigate）
├── data/
│   └── INCOMING_TEMP/          # SFTP 上傳暫存目錄
│       └── failed/             # 處理失敗的檔案
└── logs/                       # Watcher 日誌
    └── watcher.log
```

---

## 🔍 驗證測試

### 1. 檢查 Docker 服務

```bash
# 檢查容器狀態
docker-compose ps

# 預期輸出
NAME                     STATE     PORTS
rconfig-bridge-sftp      Up        0.0.0.0:2222->22/tcp
rconfig-bridge-watcher   Up
```

### 2. 檢查 Watcher 日誌

```bash
docker-compose logs -f watcher
```

**成功處理範例**：
```
📥 開始處理: fw01-192.168.1.1-20260320-143000.conf
   設備名稱: fw01
   設備 ID: 123
   目標路徑: /rconfig/.../FortigateFirewalls/fw01/2026/Mar/20/showrunning-config_123.conf
✅ 成功轉存: fw01 → showrunning-config_123.conf
   已清理暫存檔: fw01-192.168.1.1-20260320-143000.conf
```

### 3. 檢查轉存結果

```bash
# 查看 rconfig 目錄中的備份檔
ls -lh /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/

# 驗證檔案包含 metadata
head -5 /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/fw01/2026/Mar/20/showrunning-config_123.conf
```

**預期輸出（包含 metadata）**：
```
#config-version=FG201F-7.4.9-FW-build2829-250924:opmode=0:vdom=0:user=Tacacs_admin
#conf_file_ver=16609656444747006
#buildno=2829
#global_vdom=1
config system global
```

---

## 🛠️ 故障排除

### 問題 1：Watcher 無法連線到資料庫

**錯誤訊息**：
```
❌ 無法連線到 rconfig 資料庫: (2003, "Can't connect to MySQL server...")
```

**解決方式**：
```bash
# 1. 檢查 .env 中的資料庫密碼
cat .env | grep RCONFIG_DB_PASSWORD

# 2. 從 rconfig 配置檔確認正確密碼
sudo cat /var/www/html/rconfig/.env | grep DB_PASSWORD

# 3. 更新 .env 後重啟
docker-compose restart watcher
```

### 問題 2：找不到設備

**錯誤訊息**：
```
⚠️ 找不到設備: fw01
```

**解決方式**：
```bash
# 1. 檢查 rconfig 資料庫中的設備名稱
mysql -u pcc_rconfig -p rconfig -e "SELECT id, device_name FROM devices WHERE device_name LIKE 'fw%';"

# 2. 確保 Fortigate 上傳的檔名與 rconfig 設備名稱一致
# 範例：rconfig 中設備名為 "FW01-TAIPEI"，則檔名應為：
# FW01-TAIPEI-192.168.1.1-20260320-143000.conf
```

### 問題 3：檔案移至 failed 目錄

**檢查失敗原因**：
```bash
# 查看錯誤訊息
cat data/INCOMING_TEMP/failed/*.error.txt

# 常見原因
# - 檔名格式錯誤
# - 設備不存在於 rconfig
# - 檔案權限問題
```

---

## 📊 監控與維運

### 日誌查看

```bash
# 即時監控 Watcher 日誌
docker-compose logs -f watcher

# 查看歷史日誌
cat logs/watcher.log

# 查看最近 100 行
tail -100 logs/watcher.log
```

### 服務重啟

```bash
# 重啟所有服務
docker-compose restart

# 僅重啟 Watcher
docker-compose restart watcher

# 完整重建（更新程式碼後）
docker-compose down
docker-compose up -d --build
```

### 清理失敗檔案

```bash
# 檢查 failed 目錄
ls -lh data/INCOMING_TEMP/failed/

# 清理 7 天前的失敗檔案
find data/INCOMING_TEMP/failed/ -type f -mtime +7 -delete
```

---

## 🔐 安全性建議

1. **SSH 金鑰管理**
   ```bash
   # 設定私鑰權限
   chmod 600 ssh_keys/fortigate_rsa

   # 定期輪換金鑰（建議每年一次）
   ```

2. **SFTP 埠號保護**
   ```bash
   # 使用防火牆限制來源 IP
   sudo ufw allow from 192.168.1.0/24 to any port 2222
   ```

3. **資料庫密碼加密**
   ```bash
   # .env 檔案僅 root 可讀
   chmod 600 .env
   ```

---

## 📝 常見問題 (FAQ)

### Q1: 是否需要修改 rconfig 程式碼？

**A**: 完全不需要！本專案僅轉存檔案到 rconfig 目錄，rconfig 無需任何修改。

### Q2: 可以處理多台 Fortigate 嗎？

**A**: 可以！只要檔名包含設備名稱，Watcher 會自動識別並轉存到對應目錄。

### Q3: 會覆蓋 rconfig 原本的備份嗎？

**A**: 是的，會覆蓋同一天的備份檔。這樣確保 rconfig UI 下載到的永遠是包含 metadata 的完整備份。

### Q4: 如何新增其他設備廠牌支援？

**A**: 目前僅支援 Fortigate。如需擴展，需修改 `watcher/bridge.py` 中的檔名解析邏輯。

---

## 🤝 貢獻指南

歡迎提交 Issue 或 Pull Request！

---

## 📄 授權條款

MIT License

---

**最後更新**: 2026-03-20
**適用 rconfig 版本**: v6.x
**適用 Fortigate 版本**: 7.x (含以上)
