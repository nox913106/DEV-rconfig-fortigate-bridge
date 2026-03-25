# rconfig Fortigate Bridge - 部署進度追蹤

> **專案狀態**：部署完成，Automation Action 設定中

---

## 總體進度

```
[██████████████████░░] 90% 完成

✅ Phase 1: 專案開發 (100%)
✅ Phase 2: GitHub 推送 (100%)
✅ Phase 3: rconfig 主機部署 (100%)
✅ Phase 4: 測試與驗證 (100%)
🚧 Phase 5: Fortigate Automation Action 設定 (進行中)
```

---

## 已完成項目

### Phase 1: 專案開發

- [x] 建立專案目錄結構
- [x] 撰寫 Docker Compose 配置
  - SFTP 服務 (Port 2222, autoinfra 帳號)
  - Watcher 服務 (Python watchdog)
  - 自訂網路 (192.168.254.0/24)
- [x] 撰寫 Watcher Python 腳本
  - 檔案監控 (watchdog)
  - rconfig 資料庫整合 (pymysql)
  - 反向解析檔名邏輯（支援 %%date%% 格式）
  - 序列號前綴自動去除
- [x] 建立環境變數範本 (.env.example)
- [x] 撰寫 UFW 防火牆批次設定腳本
- [x] Git 版本控制初始化

### Phase 2: GitHub 推送

- [x] 建立 GitHub repository
  - URL: https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
- [x] 推送所有 commits

**Commits**：
- `19b5602` - feat: 初始化專案
- `6a03bc9` - feat: 設定 Docker 自訂網路
- `35f6ac4` - feat: 更新 SFTP 帳號/密碼、UID/GID、檔案命名邏輯
- `5941c63` - fix: 反向解析 hostname/IP 邊界
- `2ddfebb` - fix: 支援 %%date%% 展開格式 (YYYY-MM-DD)

### Phase 3: rconfig 主機部署

- [x] Docker 已安裝 (28.2.2)
- [x] Docker Compose V2 已安裝
- [x] 從 GitHub 克隆至 `/opt/DEV-rconfig-fortigate-bridge`
- [x] 配置 .env（DB_HOST=192.168.254.1）
- [x] UFW 防火牆規則（11 台 Fortigate IP + Docker 網段）
- [x] MariaDB 授權 Docker 容器連線（`pcc_rconfig@192.168.254.%`）
- [x] Docker 服務啟動，SFTP + Watcher 容器運行中

**部署過程解決的問題**：
- Docker Compose V1 不相容 → 改用 V2 (`docker compose`)
- 容器 localhost ≠ 主機 → DB_HOST 改為 192.168.254.1
- MariaDB 未授權 Docker IP → GRANT 192.168.254.%
- `docker compose restart` 不重載 .env → 改用 `docker compose up -d`

### Phase 4: 測試與驗證

- [x] %%date%% 實際展開格式確認：`YYYY-MM-DD`（如 `2026-03-24`）
- [x] 序列號前綴自動去除驗證（FG101F/FG201F 序列號）
- [x] 手動 SFTP 測試成功（TWCH-HQ2-201F-01）
- [x] Automation Action 測試成功（TWCH-HQ2-201F-01, TWCH-HQ2-101F）
- [x] rconfig 目錄結構正確：`FortigateFirewalls/{hostname}/{YYYY}/{Mon}/{DD}/`
- [x] rconfig 格式檔案正確：`show_{HHmm}.txt`
- [x] 原始備份 `.conf` 保留完整（含序列號前綴）
- [x] Metadata 驗證通過：`#config-version=`, `#buildno=`, `#global_vdom=`
- [x] HA 叢集場景驗證：兩台序列號各自保留原始 `.conf`
- [x] rconfig 設備更名：`TW-TC-CBD-Fortigate100D` → `TWTC-PA-101F`
- [x] README.md 全面更新（含 11 台 CLI 指令、實際測試日誌）

---

## 進行中

### Phase 5: Fortigate Automation Action 設定 (11 台)

#### 台灣彰化 HQ2 (172.16.11.x)

| 設備 | IP | 狀態 |
|------|-----|------|
| TWCH-HQ2-101F | 172.16.11.2 | ✅ 已設定並測試通過 |
| TWCH-HQ2-201F-01 | 172.16.11.3 | ✅ 已設定並測試通過 |
| TWCH-PCN-301E | 172.16.11.4 | 🚧 待設定 |
| TWCH-HQ2-60E-IOT | 172.16.11.5 | 🚧 待設定 |

#### 台灣台中 (172.23.x.x)

| 設備 | IP | 狀態 |
|------|-----|------|
| TWTC-PA-101F | 172.23.127.9 | ✅ 已設定並測試通過 |
| TW-TC-FortiGate-121G | 172.23.174.9 | 🚧 待設定 |
| TW-TC-UAIC-FW | 172.23.199.251 | 🚧 待設定 |

#### 台灣台北 (172.23.x.x)

| 設備 | IP | 狀態 |
|------|-----|------|
| TW-TP-BaoYu-FortiGate60E | 172.23.94.9 | 🚧 待設定 |
| TW-TP-XinYi-FortiGate60E | 172.23.110.30 | 🚧 待設定 |

#### 印度 (172.25.x.x)

| 設備 | IP | 狀態 |
|------|-----|------|
| IN-Kavin-60E | 172.25.128.254 | 🚧 待設定（需先新增 UFW 白名單） |
| IN-VSP-60E | 172.25.136.254 | 🚧 待設定（需先新增 UFW 白名單） |

**進度**：3/11 台已完成

---

## 待辦事項

- [ ] 完成剩餘 8 台 Fortigate Automation Action 設定
- [ ] 新增印度 2 台 UFW 白名單 (172.25.128.254, 172.25.136.254)
- [ ] 推送 README.md 更新到 GitHub
- [ ] （未來）密碼認證改為 SSH 金鑰認證

---

## 聯絡資訊

**專案負責人**: Max Fung (max.fung@pouchen.com)
**GitHub Repository**: https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
**部署主機**: stwrconfig6 (172.16.5.124)

---

## 版本記錄

| 版本 | 日期 | 變更內容 |
|------|------|---------|
| v1.0.0 | 2026-03-20 | 初始版本：專案開發完成 |
| v1.1.0 | 2026-03-24 | 部署完成、檔名解析修正（%%date%%/序列號/反向解析）、3 台測試通過 |

---

**最後更新**: 2026-03-24
**當前狀態**: 部署完成，Automation Action 逐台設定中 (3/11)
**下次繼續**: 完成剩餘 8 台 Automation Action 設定
