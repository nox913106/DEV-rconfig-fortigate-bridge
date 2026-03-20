# rconfig Fortigate Bridge - 部署進度追蹤

> **專案狀態**：開發完成，待部署到 rconfig 主機

---

## 📊 總體進度

```
[████████████░░░░░░░░] 60% 完成

✅ Phase 1: 專案開發 (100%)
✅ Phase 2: GitHub 推送 (100%)
🚧 Phase 3: rconfig 主機部署 (0%)
🔜 Phase 4: 測試與驗證 (0%)
```

---

## ✅ 已完成項目

### Phase 1: 專案開發

- [x] 建立專案目錄結構
- [x] 撰寫 Docker Compose 配置
  - SFTP 服務 (Port 2222)
  - Watcher 服務 (Python)
  - 自訂網路 (192.168.254.0/24)
- [x] 撰寫 Watcher Python 腳本
  - 檔案監控 (watchdog)
  - rconfig 資料庫整合 (pymysql)
  - 檔名解析與轉存邏輯
- [x] 撰寫完整 README 文件 (300+ 行)
- [x] 建立環境變數範本 (.env.example)
- [x] 撰寫 UFW 防火牆批次設定腳本
- [x] Git 版本控制初始化

**程式碼統計**：
- Python: 250 行 (核心邏輯)
- YAML: 75 行 (Docker Compose)
- Bash: 50 行 (部署腳本)
- Markdown: 300+ 行 (文件)

### Phase 2: GitHub 推送

- [x] 建立 GitHub repository
  - URL: https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
- [x] 推送初始 commit (7 files)
- [x] 推送網路配置更新 (192.168.254.0/24)

**Commits**：
- `19b5602` - feat: 初始化專案
- `6a03bc9` - feat: 設定 Docker 自訂網路

---

## 🚧 待執行項目

### Phase 3: rconfig 主機部署

#### 3.1 環境準備

- [ ] **在 rconfig 主機安裝 Docker**
  ```bash
  sudo apt update
  sudo apt install -y docker.io docker-compose
  sudo systemctl start docker
  sudo systemctl enable docker
  ```

- [ ] **驗證安裝**
  ```bash
  docker --version
  docker-compose --version
  ```

#### 3.2 克隆專案

- [ ] **從 GitHub 克隆專案**
  ```bash
  cd /opt
  sudo git clone https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
  cd DEV-rconfig-fortigate-bridge
  ```

#### 3.3 配置環境變數

- [ ] **複製 .env 範本**
  ```bash
  cp .env.example .env
  ```

- [ ] **編輯 .env 設定**
  ```bash
  nano .env
  ```

  **必須修改的參數**：
  ```bash
  RCONFIG_DB_PASSWORD=maWH5iv7DECFtc6u  # rconfig 資料庫密碼
  RCONFIG_PATH=/var/www/html/rconfig    # rconfig 安裝路徑
  ```

#### 3.4 設定 UFW 防火牆

- [ ] **安裝 UFW**
  ```bash
  sudo apt install -y ufw
  ```

- [ ] **設定基礎規則**
  ```bash
  sudo ufw allow 22/tcp comment 'Allow SSH'
  sudo ufw allow 80/tcp comment 'Allow HTTP'
  sudo ufw allow 443/tcp comment 'Allow HTTPS'
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  ```

- [ ] **批次新增 Fortigate IP 白名單 (12 台)**
  ```bash
  # 執行以下腳本（已準備好）
  sudo bash << 'EOF'
  IPS=(
      "172.16.11.2" "172.16.11.3" "172.16.11.4" "172.16.11.5"
      "172.23.13.9" "172.23.174.9" "172.23.127.9" "172.23.199.251"
      "172.23.94.9" "172.23.110.30" "10.240.29.254" "10.240.13.4"
  )
  for ip in "${IPS[@]}"; do
      ufw allow from $ip to any port 2222 proto tcp comment "Fortigate $ip"
  done
  ufw --force enable
  EOF
  ```

- [ ] **驗證規則**
  ```bash
  sudo ufw status numbered | grep 2222
  ```

#### 3.5 產生 SSH 金鑰

- [ ] **產生共用金鑰（1 把，供所有 Fortigate 使用）**
  ```bash
  mkdir -p ssh_keys
  ssh-keygen -t rsa -b 4096 -f ./ssh_keys/fortigate_rsa -N ""
  chmod 600 ./ssh_keys/fortigate_rsa
  chmod 644 ./ssh_keys/fortigate_rsa.pub
  ```

- [ ] **設定 authorized_keys**
  ```bash
  cp ./ssh_keys/fortigate_rsa.pub ./ssh_keys/authorized_keys
  chmod 600 ./ssh_keys/authorized_keys
  ```

- [ ] **複製公鑰到剪貼簿**
  ```bash
  cat ./ssh_keys/fortigate_rsa.pub
  ```
  → **儲存此公鑰，稍後設定到所有 Fortigate**

#### 3.6 啟動 Docker 服務

- [ ] **啟動服務**
  ```bash
  sudo docker-compose up -d
  ```

- [ ] **檢查容器狀態**
  ```bash
  sudo docker-compose ps
  ```

  **預期輸出**：
  ```
  NAME                        STATE       PORTS
  rconfig-bridge-sftp         Up          0.0.0.0:2222->22/tcp
  rconfig-bridge-watcher      Up
  ```

- [ ] **查看 Watcher 日誌**
  ```bash
  sudo docker-compose logs -f watcher
  ```

  **預期日誌**：
  ```
  ✅ rconfig Fortigate Bridge - Watcher 啟動
  ✅ 已連線到 rconfig 資料庫
  ✅ Watcher 已啟動，開始監控 SFTP 上傳...
  ```

---

### Phase 4: Fortigate 設定與測試

#### 4.1 設定 Fortigate SSH 公鑰（12 台）

**需要設定的 Fortigate IP**：
- 172.16.11.2, .3, .4, .5
- 172.23.13.9, 174.9, 127.9, 199.251, 94.9, 110.30
- 10.240.29.254, 13.4

**在每台 Fortigate CLI 執行**：
```bash
config system admin
    edit "autoinfra"
        set accprofile "super_admin"
        set ssh-public-key1 "<PUBLIC_KEY>"  # 替換為實際公鑰
        set password-expire never
    next
end
```

#### 4.2 測試 SFTP 連線

- [ ] **從其中一台 Fortigate 測試**
  ```bash
  # 在 Fortigate CLI 執行
  execute backup config sftp test-172.16.11.2-20260320.conf <rconfig-ip>:2222 autoinfra
  ```

  **成功訊息**：
  ```
  Backup config file to <rconfig-ip> via ftp successfully.
  ```

- [ ] **檢查 Watcher 日誌**
  ```bash
  sudo docker-compose logs watcher | tail -20
  ```

  **預期日誌**：
  ```
  📥 開始處理: test-172.16.11.2-20260320.conf
     設備名稱: test
     設備 ID: 123
  ✅ 成功轉存: test → showrunning-config_123.conf
  ```

- [ ] **檢查轉存結果**
  ```bash
  # 查看 rconfig 目錄
  ls -lh /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/

  # 驗證檔案包含 metadata
  head -5 /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/test/2026/Mar/20/showrunning-config_123.conf
  ```

  **預期輸出（包含 metadata）**：
  ```
  #config-version=FG201F-7.4.9-FW-build2829-250924:opmode=0:vdom=0:user=autoinfra
  #conf_file_ver=16609656444747006
  #buildno=2829
  #global_vdom=1
  ```

#### 4.3 設定 Fortigate 自動排程

- [ ] **在每台 Fortigate 設定每日備份（02:00）**
  ```bash
  config system auto-script
      edit "daily-config-backup"
          set interval 86400
          set start auto
          set script "execute backup config sftp $(FGT_HOSTNAME)-$(FGT_SERIAL_NUMBER)-$(TIMESTAMP).conf <rconfig-ip>:2222 autoinfra"
      next
  end
  ```

---

## 📝 部署檢查清單

### 前置確認

- [ ] rconfig 主機 OS: Ubuntu 22.04 LTS
- [ ] rconfig 主機 IP: __________________
- [ ] rconfig 資料庫密碼已確認: `maWH5iv7DECFtc6u`
- [ ] 12 台 Fortigate IP 清單已確認

### 部署步驟

- [ ] 安裝 Docker 與 Docker Compose
- [ ] 克隆 GitHub repository
- [ ] 配置 .env 環境變數
- [ ] 設定 UFW 防火牆規則
- [ ] 產生 SSH 金鑰對
- [ ] 啟動 Docker 服務
- [ ] 驗證 Watcher 連線到資料庫

### Fortigate 設定

- [ ] 複製 SSH 公鑰到所有 Fortigate (12 台)
- [ ] 測試 SFTP 連線（至少 1 台）
- [ ] 驗證檔案轉存成功
- [ ] 驗證 metadata 完整性
- [ ] 設定自動排程（所有 Fortigate）

---

## 🎯 下一步行動

### 立即執行（Phase 3.1 - 3.6）

1. **在 rconfig 主機安裝 Docker**
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose
   ```

2. **克隆專案**
   ```bash
   cd /opt && sudo git clone https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
   ```

3. **配置與啟動**
   ```bash
   cd DEV-rconfig-fortigate-bridge
   cp .env.example .env
   nano .env  # 修改資料庫密碼
   # 執行 UFW 腳本
   # 產生 SSH 金鑰
   sudo docker-compose up -d
   ```

### 後續執行（Phase 4）

1. **設定 Fortigate SSH 公鑰**（需要公鑰產生後）
2. **測試 SFTP 連線**
3. **驗證完整流程**

---

## 📞 聯絡資訊

**專案負責人**: Max Fung (max.fung@pouchen.com)
**GitHub Repository**: https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
**部署目標**: rconfig 主機 (stwrconfig6)

---

## 🔄 版本記錄

| 版本 | 日期 | 變更內容 |
|------|------|---------|
| v1.0.0 | 2026-03-20 | 初始版本：專案開發完成，待部署 |

---

**最後更新**: 2026-03-20
**當前狀態**: 專案開發完成，待部署到 rconfig 主機
**預計完成**: 部署後 1 日內完成測試驗證
