# rconfig Fortigate Bridge — 演示流程與實機操作指令

> **用途**：簡報現場實機 Demo 操作手冊
> **目標主機**：stwrconfig6 (172.16.5.124)
> **部署路徑**：`/opt/DEV-rconfig-fortigate-bridge`
> **預計 Demo 時間**：10～15 分鐘

---

## 事前準備（Demo 開始前完成）

### 連線到主機

```bash
ssh max.fung@172.16.5.124
```

### 切換到專案目錄

```bash
cd /opt/DEV-rconfig-fortigate-bridge
```

### 確認服務正在運行

```bash
sudo docker compose ps
```

**預期看到**：
```
NAME                     IMAGE                     STATUS    PORTS
rconfig-bridge-sftp      atmoz/sftp:alpine         Up        0.0.0.0:2222->22/tcp
rconfig-bridge-watcher   ...bridge-watcher          Up
```

> 如果 STATUS 不是 Up，執行：`sudo docker compose up -d`

---

## Demo 段落一：展示「問題」

> **口述**：「先讓大家看看 rconfig 原本備份的內容長什麼樣子。」

### 找一台已有備份的 Fortigate，看 rconfig 的舊備份

```bash
# 查看 rconfig 備份目錄（以 TWCH-HQ2-201F-01 為例）
ls -lh /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/
```

### 進到今天的備份目錄，看兩個檔案的差異

```bash
# 先看目錄結構
ls -lh /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/$(date +%Y)/$(date +%b)/$(date +%d)/
```

> **口述**：「這裡會看到兩個檔案，一個是 show_1930.txt，一個是原始的 .conf 檔。它們的內容其實是一樣的，關鍵差異在開頭幾行。」

### 驗證備份檔確實包含 metadata（核心展示點）

```bash
# 看 show_1930.txt 開頭（這就是 rconfig 會呈現給使用者的內容）
head -6 /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/$(date +%Y)/$(date +%b)/$(date +%d)/show_1930.txt
```

**預期看到**（有 metadata = 正確）：
```
#config-version=FG201F-7.4.9-FW-build2829-250924:opmode=0:vdom=0:user=daemon_admin
#conf_file_ver=16611773863624424
#buildno=2829
#global_vdom=1
config system global
    set admin-concurrent enable
```

> **口述**：「這幾行就是關鍵。有這些 metadata，Fortigate 還原的時候才能正確識別這份設定檔。rconfig 原本 SSH 備份的版本，這幾行是不存在的。」

---

## Demo 段落二：展示「系統架構」（邊說邊看 log）

> **口述**：「我們來看看這個系統平常是怎麼運作的。」

### 開一個分割視窗持續監控 Watcher log

```bash
# 視窗 1（保持監控）
sudo docker compose logs -f watcher --tail 30
```

> **口述**：「這是 Watcher 的即時 log。等一下我們觸發一次手動備份，可以在這裡看到整個處理過程。」

---

## Demo 段落三：實機觸發備份（核心展示）

> **口述**：「現在我要到 Fortigate 上手動觸發一次備份，模擬每天 19:30 自動排程的行為。」

### 操作方式 A：SSH 進 Fortigate CLI 手動觸發

```bash
# 連線到 Fortigate（以 TWCH-HQ2-201F-01 為例）
ssh admin@172.16.11.3
```

在 Fortigate CLI 執行（使用今天日期）：

```
execute backup config sftp upload/TWCH-HQ2-201F-01-172-16-11-3-20260407.conf 172.16.5.124:2222 autoinfra #%2021Radiu$PcC
```

**Fortigate 回應**（成功）：
```
Please wait...
Connect to sftp server 172.16.5.124:2222 ...
Backup config file to 172.16.5.124 via sftp successfully.
```

### 操作方式 B：直接在主機模擬上傳（若無法 SSH 進 Fortigate）

```bash
# 視窗 2（在主機上模擬 Fortigate 上傳，用 scp 傳一個假檔案）
# 先準備一個測試檔（用現有備份複製）
LATEST=$(ls /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/$(date +%Y)/$(date +%b)/$(date +%d)/*.conf 2>/dev/null | head -1)

if [ -n "$LATEST" ]; then
    cp "$LATEST" /tmp/TWCH-HQ2-201F-01-172-16-11-3-20260407.conf
    sftp -P 2222 autoinfra@127.0.0.1 <<EOF
put /tmp/TWCH-HQ2-201F-01-172-16-11-3-20260407.conf upload/TWCH-HQ2-201F-01-172-16-11-3-20260407.conf
EOF
else
    echo "找不到現有備份檔，請使用操作方式 A"
fi
```

> SFTP 密碼：`#%2021Radiu$PcC`

---

## Demo 段落四：即時觀察 Watcher 處理過程

切回視窗 1（Watcher log），應該會看到：

```
📥 開始處理: TWCH-HQ2-201F-01-172-16-11-3-20260407.conf
   設備名稱: TWCH-HQ2-201F-01
   時間戳記: 20260407
   設備 ID: 4
   rconfig 檔案: show_1930.txt
   備份檔案: TWCH-HQ2-201F-01-172-16-11-3-20260407.conf
✅ 已轉存為 rconfig 格式: show_1930.txt
✅ 已保留原始備份: TWCH-HQ2-201F-01-172-16-11-3-20260407.conf
   已清理暫存檔: TWCH-HQ2-201F-01-172-16-11-3-20260407.conf
```

> **口述**：「看到了嗎？從檔案出現到處理完成，不到 3 秒。系統自動完成了：解析檔名、查詢資料庫確認設備、轉存到 rconfig 目錄。」

---

## Demo 段落五：驗證轉存結果

### 確認檔案已出現在 rconfig 目錄

```bash
ls -lh /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/$(date +%Y)/$(date +%b)/$(date +%d)/
```

**預期看到兩個檔案**：
```
-rw-r--r-- 1 root root  XXK Apr  7 19:30 show_1930.txt
-rw-r--r-- 1 root root  XXK Apr  7 19:30 TWCH-HQ2-201F-01-172-16-11-3-20260407.conf
```

### 再次確認 metadata 存在

```bash
head -4 /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/TWCH-HQ2-201F-01/$(date +%Y)/$(date +%b)/$(date +%d)/show_1930.txt
```

---

## Demo 段落六：查看全部 11 台的備份狀況（選用）

> **口述**：「目前 11 台 Fortigate 每天都會自動備份，我們可以快速確認昨天的備份是否都有成功。」

```bash
# 查看昨天所有備份是否存在
YESTERDAY=$(date -d "yesterday" +%Y/%b/%d)
echo "=== 昨日備份狀況 ($YESTERDAY) ==="
for device in \
    "TWCH-HQ2-101F" \
    "TWCH-HQ2-201F-01" \
    "TWCH-PCN-301E" \
    "TWCH-HQ2-60E-IOT" \
    "TWTC-PA-101F" \
    "TW-TC-FortiGate-121G" \
    "TW-TC-UAIC-FW" \
    "TW-TP-BaoYu-FortiGate60E" \
    "TW-TP-XinYi-FortiGate60E" \
    "IN-Kavin-60E" \
    "IN-VSP-60E"
do
    BACKUP_PATH="/var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/$device/$YESTERDAY/show_1930.txt"
    if [ -f "$BACKUP_PATH" ]; then
        SIZE=$(du -h "$BACKUP_PATH" | cut -f1)
        echo "  ✅ $device ($SIZE)"
    else
        echo "  ❌ $device — 備份不存在"
    fi
done
```

---

## 常用備援指令（現場突發狀況處理）

### 服務沒起來 → 強制重建

```bash
sudo docker compose down && sudo docker compose up -d --build
```

### Watcher log 沒動靜 → 確認暫存目錄

```bash
# 看暫存目錄有沒有卡住的檔案
ls -lh /opt/DEV-rconfig-fortigate-bridge/data/INCOMING_TEMP/

# 看 failed 目錄有沒有處理失敗的
ls -lh /opt/DEV-rconfig-fortigate-bridge/data/INCOMING_TEMP/failed/

# 看失敗原因
cat /opt/DEV-rconfig-fortigate-bridge/data/INCOMING_TEMP/failed/*.error.txt 2>/dev/null
```

### 資料庫連線失敗 → 快速診斷

```bash
# 確認 .env 設定
grep RCONFIG_DB_HOST /opt/DEV-rconfig-fortigate-bridge/.env

# 確認 MariaDB 授權
sudo mysql -u root -e "SELECT host, user FROM mysql.user WHERE user='pcc_rconfig';"

# 重建容器（重載 .env）
sudo docker compose up -d
```

### 特定設備備份失敗 → 確認是否走 IPsec Tunnel

若某台設備昨日備份顯示 ❌，且該設備是透過 IPsec Tunnel 連回 rconfig 主機，檢查步驟：

```bash
# SSH 進該 Fortigate，確認 Static Route 有無設定 preferred-source
# （在 Fortigate CLI 執行）
show router static | grep -A5 "172.16.5.124"

# 正確設定應包含：
#   set preferred-source x.x.x.x   ← 該設備與 rconfig 互通的介面 IP
# 若無此行，代表 Source IP 會使用預設的 port1/wan1，可能被 IPsec Tunnel 丟棄
```

> **現場口述重點**：走 IPsec Tunnel 的設備，Fortigate 送出 SFTP 封包時，預設會用硬體第一個介面的 IP 當 Source IP，但這個 IP 不在 Tunnel 的 Proxy ID 範圍內，封包會被丟棄。Static Route 加上 `preferred-source` 才能讓封包正確走進 Tunnel。

### 手動 SFTP 連線測試

```bash
sftp -P 2222 autoinfra@172.16.5.124
# 密碼：#%2021Radiu$PcC
# 連線成功後輸入 exit 離開
```

### 確認 UFW 防火牆規則

```bash
sudo ufw status | grep -E "(2222|3306|254)"
```

---

## Demo 環境資訊速查

| 項目 | 值 |
|------|-----|
| 主機 | stwrconfig6 (172.16.5.124) |
| 專案路徑 | `/opt/DEV-rconfig-fortigate-bridge` |
| SFTP Port | 2222 |
| SFTP 帳號 | autoinfra |
| SFTP 密碼 | `#%2021Radiu$PcC` |
| DB Host（容器內） | 192.168.254.1 |
| rconfig 備份根目錄 | `/var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/` |
| 示範設備 | TWCH-HQ2-201F-01 (172.16.11.3) |
| Fortigate 備份排程 | 每日 19:30 |

---

**最後更新**：2026-04-07