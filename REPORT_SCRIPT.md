# rconfig Fortigate Bridge — 報告逐字稿

> **專案**：rconfig Fortigate Bridge
> **負責人**：Max Fung
> **日期**：2026-03-25
> **版本**：v1.2.0

---

## 一、開場白

大家好，今天要跟大家分享的是一個我們在管理 Fortigate 防火牆備份時遇到的實際問題，以及我們怎麼用一個輕量的自動化方案把它解決掉。

這個專案叫做 **rconfig Fortigate Bridge**，字面上就是在 rconfig 備份系統和 Fortigate 防火牆之間搭一座橋。

---

## 二、為什麼要做這個東西？（問題背景）

我們目前使用 **rconfig** 這套開源工具來集中管理所有網路設備的設定備份。它的運作方式很直覺——透過 SSH 連進設備，執行 `show full-configuration` 或類似指令，把輸出結果存成純文字檔。對一般的 Cisco、Juniper 設備來說，這樣就夠了。

但 Fortigate 有一個特殊的地方：

### Fortigate 備份檔的 metadata 問題

當我們從 rconfig 下載一台 Fortigate 的備份，然後嘗試把它還原到設備上的時候，Fortigate 會拒絕這份設定檔，或者還原後出現異常。

原因是什麼？

因為 Fortigate 的完整備份檔，開頭有一段非常關鍵的 metadata：

```
#config-version=FG201F-7.4.9-FW-build2829-250924:opmode=0:vdom=0:user=daemon_admin
#conf_file_ver=16611773863624424
#buildno=2829
#global_vdom=1
```

這幾行看起來像是注解，但對 Fortigate 來說，它是驗證還原檔案的依據。它記錄了：

- 這台設備的型號（`FG201F`）
- 韌體版本（`7.4.9`、`build2829`）
- 操作模式與 VDOM 設定

**問題就在這裡**——rconfig 透過 SSH 執行 `show full-configuration` 拿到的輸出，是一份「純設定文字」，這幾行 metadata 根本不會出現。

所以我們手上存的備份是「不完整的備份」。平常看起來沒問題，真的發生事故需要還原的時候，才會踩到這個坑。

這就是為什麼我們需要另一個方案：**讓 Fortigate 自己送出完整備份檔**。

---

## 三、規劃思路（套件選用原因）

確定問題之後，我們開始思考解法。

### 解法核心思路

Fortigate 本身就有一個功能叫做 `execute backup config sftp`，可以讓防火牆主動把完整備份——包含那段重要的 metadata——透過 SFTP 協定上傳到指定的伺服器。

所以解法方向就很清楚了：

> 讓 Fortigate 自己把完整備份推送過來，我們在接收端做後處理，把它整合進 rconfig 現有的目錄結構裡。

整個架構只需要兩個元件：

1. **SFTP 接收端**：讓 Fortigate 有地方傳
2. **檔案轉存器**：接到檔案之後，自動搬到 rconfig 認識的位置

### 套件選用理由

#### `atmoz/sftp`（Docker Image）

這是 Docker Hub 上一個非常輕量的 SFTP 伺服器映像，基於 OpenSSH。選用它的原因：

- **部署極簡**：在 `docker-compose.yml` 裡幾行設定就能跑起來一個獨立的 SFTP 服務，不需要動到主機的 SSH 設定
- **帳號隔離**：可以建立一個專用帳號 `autoinfra`，只用來接收防火牆備份，與主機的系統帳號完全分開
- **目錄掛載**：SFTP 的上傳目錄直接掛載到主機的共享目錄，讓後面的 Watcher 可以即時感知新檔案

> 為什麼不用主機的 SSH 直接開 SFTP？因為那樣會動到 `sshd_config`，風險較高，而且混用系統帳號不乾淨。獨立容器讓職責單一，也方便未來移除。

#### `watchdog`（Python 套件）

這個套件的用途是監控檔案系統事件。選用它的原因：

- **事件驅動，不輪詢**：不需要每幾秒去掃一次目錄，`watchdog` 會訂閱作業系統的 inotify 事件，有新檔案建立就立刻觸發處理，效率高、延遲低
- **輕量**：整個套件依賴很少，跑在一個小容器裡完全沒有問題
- **成熟穩定**：這個套件在 Python 生態系裡已經非常成熟，API 簡單直覺

#### `pymysql`（Python 套件）

這個套件負責連接 rconfig 的 MariaDB 資料庫。為什麼需要查資料庫？

因為我們需要把「Fortigate 傳來的檔名」對應到「rconfig 裡面的設備記錄」。rconfig 用 `device_name` 來識別設備，然後用設備 ID 決定檔案要存到哪個目錄。

選用 `pymysql` 而不是其他 connector 的原因很簡單——它是純 Python 實作，不需要安裝任何 C 語言的原生套件，在 Alpine Linux 的精簡容器裡也能直接使用。

#### Docker Compose

選擇用 Docker Compose 來整合兩個服務（SFTP + Watcher），原因是：

- **環境可重現**：整個服務只要 `docker compose up -d --build` 就能啟動，換機器或重建都一樣
- **不污染主機**：所有依賴都在容器裡，主機環境乾淨
- **自訂網路**：兩個容器跑在同一個自訂橋接網路 `192.168.254.0/24` 裡，讓 Watcher 可以透過這個網段的 gateway IP 連接到主機的 MariaDB

---

## 四、工作原理（系統如何運作）

### 整體流程

```
Fortigate（11台）
    │  每天 19:30，Automation Action 觸發
    │  execute backup config sftp upload/{檔名} 172.16.5.124:2222 ...
    │
    ▼
SFTP 容器（Port 2222）
    │  接收備份檔，存放於 /home/autoinfra/upload/
    │  （掛載至主機 ./data/INCOMING_TEMP/）
    │
    ▼
Watcher 容器（Python）
    │  watchdog 偵測到新 .conf 檔案建立事件
    │  ↓
    │  解析檔名 → 取得 hostname、IP、日期
    │  ↓
    │  查詢 rconfig 資料庫 → 確認設備存在、取得設備 ID
    │  ↓
    │  複製備份檔到 rconfig 目錄結構
    │  ├── show_1930.txt  （rconfig 可辨識格式，覆蓋原本空白備份）
    │  └── {原始檔名}.conf（完整備份保留，含 metadata）
    │  ↓
    │  清除 SFTP 暫存檔
    │
    ▼
rconfig UI
    使用者下載的就是包含完整 metadata 的備份檔
```

### 關鍵細節：檔名解析邏輯

Fortigate 在透過 SFTP 上傳檔案時，有一個你沒辦法關掉的行為——**它會自動在檔名前面加上設備的序列號**，例如：

```
FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf
```

前面的 `FG201FT922913515_` 是序列號前綴，我們要去掉它才能解析真正的資訊。

去掉前綴之後，剩下的檔名格式是：

```
{設備名稱}-{IP用破折號分隔}-{日期}.conf
```

例如：

```
TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf
```

這裡有一個棘手的問題：設備名稱裡面可能含有數字，IP 也是數字，全部用破折號連起來，要怎麼知道哪裡是設備名、哪裡是 IP？

我們的解法是**反向解析**——從後面往前識別：

1. 先識別最後面的日期（格式固定，好判斷）
2. 然後取前 4 段純數字作為 IP
3. 剩下的全部就是設備名稱

這樣就不會被設備名稱裡的數字混淆。

此外，`%%date%%` 這個 Fortigate 的時間變數有兩種展開結果：

| 觸發方式 | 展開格式 | 範例 |
|---------|---------|------|
| Automation Action | `YYYY-MM-DD`（帶破折號）| `2026-03-24` |
| 手動 CLI 測試 | 不展開，需手動輸入 | `20260324` |

解析邏輯同時支援這兩種格式。

### 轉存結果

每次成功處理，會在 rconfig 目錄產生兩個檔案：

```
/var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/
  TWCH-HQ2-201F-01/
    2026/Mar/24/
      show_1930.txt          ← rconfig 認識的格式，含完整 metadata
      FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-2026-03-24.conf  ← 原始備份保留
```

`show_1930.txt` 的時間對齊 Fortigate Automation Action 排程時間（19:30），這樣 rconfig 介面上就不會出現「同天兩個備份」的混亂。

---

## 五、部署過程中的注意重點

部署的時候踩過幾個坑，值得特別說明，讓之後的人不要重蹈覆轍。

### 1. Docker Compose 版本：V2 vs V1

主機上如果裝的是舊版的 Docker Compose V1（指令是 `docker-compose`），有些語法不相容。我們這個專案使用 Docker Compose V2，指令是 `docker compose`（中間是空格，不是連字號）。

部署前先確認版本：

```bash
docker compose version
```

### 2. 容器的 `localhost` 不是主機的 `localhost`

這是 Docker 新手最常踩的坑。容器裡面的 `localhost` 指的是容器自己，不是主機。

所以 Watcher 容器要連接主機上的 MariaDB，不能用 `localhost`，必須用 Docker 橋接網路的 gateway IP：

```bash
RCONFIG_DB_HOST=192.168.254.1
```

這個 IP 是在 `docker-compose.yml` 裡面固定設定的 gateway，一定要用這個。

### 3. MariaDB 要額外授權 Docker 網段

MariaDB 預設只允許特定主機連入。Docker 容器網段是 `192.168.254.0/24`，需要明確授權：

```sql
GRANT ALL PRIVILEGES ON rconfig.* TO 'pcc_rconfig'@'192.168.254.%' IDENTIFIED BY '<密碼>';
FLUSH PRIVILEGES;
```

缺了這步，Watcher 啟動之後會一直報無法連線的錯誤。

### 4. `.env` 修改之後要用 `up -d`，不能用 `restart`

`docker compose restart` **不會重載 `.env` 檔案**。如果修改了 `.env` 的設定，必須用：

```bash
sudo docker compose up -d
```

這樣 Compose 才會重新讀取環境變數並重建容器。

### 5. 容器時區要手動設定

容器預設時區是 UTC，跟台灣時間差了 8 小時。如果不修正，產生的 `show_{時間}.txt` 會跑掉，檔案也會存到錯誤的日期目錄。

在 `docker-compose.yml` 的 watcher 服務加上：

```yaml
environment:
  TZ: Asia/Taipei
```

### 6. 經由 IPsec Tunnel 的設備：Static Route 要設定 Prefer Source IP

這個問題只會發生在透過 IPsec Tunnel 連線的 Fortigate（例如分支站點），但它很隱晦，非常容易被忽略。

**問題描述**：

當 Fortigate 執行 `execute backup config sftp` 時，系統需要決定「用哪個 IP 作為來源封包的 Source IP」連出去。如果前往 rconfig 主機的路由是走 IPsec Tunnel，Fortigate 的預設行為是用**硬體第一個介面（通常是 `port1` 或 `wan1`）的 IP** 作為 Source IP。

這個 IP 往往不在 IPsec Tunnel 允許的流量範圍內，導致：
- 封包從 Tunnel 出去，但 Source IP 對不上 Tunnel 的 Proxy ID
- rconfig 主機收不到連線，或 Fortigate 回報連線失敗

**解決方式**：

在 Fortigate 的 **Network > Static Routes** 裡，找到前往 rconfig 主機（`172.16.5.124`）的路由規則，加上 **Preferred Source IP**，明確指定要用哪個介面 IP 作為來源。

```
Network > Static Routes > 編輯對應規則
  Destination:     172.16.5.124/32
  Gateway:         （Tunnel 介面）
  Preferred Source: {該站點與 rconfig 所在網段互通的介面 IP}
```

CLI 設定方式：

```
config router static
    edit <rule_id>
        set dst 172.16.5.124 255.255.255.255
        set device <tunnel_interface>
        set preferred-source <本端與rconfig互通的IP>
    next
end
```

> **為什麼要這樣做？** IPsec Tunnel 的流量是根據 Source/Destination IP 對做 Proxy ID 比對，如果 Source IP 用錯，封包雖然往 Tunnel 方向走，但 Tunnel 兩端的 Phase 2 SA 不匹配，封包會被丟棄。加上 `preferred-source` 之後，Fortigate 送出的封包 Source IP 就會固定使用正確的介面 IP，讓 Tunnel 正常放行。

### 7. UFW 防火牆要針對 Fortigate IP 個別開放

主機的 UFW 防火牆預設會擋掉 Port 2222 的連入。需要設定：

- 只允許 Fortigate IP 清單連入 Port 2222（白名單制）
- 允許 Docker 網段 `192.168.254.0/24` 連接到 MariaDB Port 3306

```bash
# Docker 容器連 MariaDB
sudo ufw allow from 192.168.254.0/24 to any port 3306 proto tcp

# Fortigate SFTP 白名單（每台個別設定）
sudo ufw allow from 172.16.11.2 to any port 2222 proto tcp
# ... 其餘各台依此類推
```

---

## 六、成果總結

目前這個系統已經穩定運行在 stwrconfig6（172.16.5.124），涵蓋台灣彰化、台中、台北，以及印度共 **11 台 Fortigate** 防火牆。

每天 19:30 各台防火牆自動透過 Automation Action 推送備份，Watcher 自動接收、解析、轉存，整個過程無需人工介入。

rconfig 介面上，運維人員下載到的設定檔，現在是帶有完整 metadata 的**可直接還原**備份，解決了原本潛在的災難恢復風險。

整個專案只有 **2 個 Python 套件**、**1 個現成 Docker Image**，不需要修改任何 rconfig 現有程式碼，以最小的侵入性達成了目標。

謝謝大家。

---

### 附錄：涵蓋設備清單

| 區域 | 設備名稱 | IP |
|------|---------|-----|
| 台灣彰化 HQ2 | TWCH-HQ2-101F | 172.16.11.2 |
| 台灣彰化 HQ2 | TWCH-HQ2-201F-01 | 172.16.11.3 |
| 台灣彰化 HQ2 | TWCH-PCN-301E | 172.16.11.4 |
| 台灣彰化 HQ2 | TWCH-HQ2-60E-IOT | 172.16.11.5 |
| 台灣台中 | TWTC-PA-101F | 172.23.127.9 |
| 台灣台中 | TW-TC-FortiGate-121G | 172.23.174.9 |
| 台灣台中 | TW-TC-UAIC-FW | 172.23.199.251 |
| 台灣台北 | TW-TP-BaoYu-FortiGate60E | 172.23.94.9 |
| 台灣台北 | TW-TP-XinYi-FortiGate60E | 172.23.110.30 |
| 印度 | IN-Kavin-60E | 172.25.128.254 |
| 印度 | IN-VSP-60E | 172.25.136.254 |

---

**最後更新**：2026-03-25
**GitHub**：https://github.com/nox913106/DEV-rconfig-fortigate-bridge.git
**部署主機**：stwrconfig6 (172.16.5.124)