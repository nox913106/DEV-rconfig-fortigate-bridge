# Fortigate SFTP 備份路由問題排查紀錄

> **事件日期**: 2026-03-26 ~ 2026-03-27
> **影響範圍**: 7/12 台遠端 Fortigate 無法透過 SFTP 傳送備份至 stwrconfig6
> **狀態**: 已解決 — 採用解法 C (preferred-source)

---

## 1. 問題描述

### 現象

2026-03-26 晚間 19:30 首次全量備份，12 台 Fortigate 中僅 5 台成功：

| 類別 | 設備 | 結果 |
|------|------|------|
| HQ2 本地 (172.16.11.x) | TWCH-HQ2-101F, TWCH-HQ2-201F-01, TWCH-PCN-301E, TWCH-HQ2-60E-IOT | 成功 |
| 台中 leased line | TW-TC-FortiGate-121G | 成功 |
| 台中 internet VPN | TWTC-PA-101F, TW-TC-UAIC-FW | 失敗 |
| 台北 internet VPN | TW-TP-BaoYu-FortiGate60E, TW-TP-XinYi-FortiGate60E | 失敗 |
| 印度 internet VPN | IN-Kavin-60E, IN-VSP-60E | 失敗 |

**成功的共同點**: 與 stwrconfig6 同網段 (HQ2 本地) 或透過 leased line 專線隧道連線。
**失敗的共同點**: 透過 internet IPSec VPN 隧道連線。

### 錯誤訊息

遠端 Fortigate 執行 `execute backup config sftp` 時回報：
```
Send config file to sftp server via vdom root failed.
Command fail. Return code -1
```

---

## 2. 根因分析 (Root Cause Analysis)

### 排查路徑

依序排除了以下可能性：

| 步驟 | 假設 | 驗證方法 | 結果 |
|------|------|---------|------|
| 1 | stwrconfig6 UFW 阻擋 | `ufw status` 確認規則 | 排除 — 所有 IP 的 port 2222 已開放 |
| 2 | stwrconfig6 收不到封包 | `tcpdump port 2222` | 確認 — 0 packets，封包未到達主機 |
| 3 | 中間路由/ISP 阻擋 port 2222 | traceroute + IPSec 確認 | 排除 — 兩端有 IPSec VPN 隧道 |
| 4 | 遠端 FG 路由問題 | `get router info routing-table` | 排除 — 172.16.0.0/16 路由存在 |
| 5 | **來源 IP 異常** | `diagnose debug flow` on UAIC | **確認 — 來源 IP 為 WAN 公網 IP** |
| 6 | HQ2 RPF 檢查失敗 | `diagnose debug flow` on HQ2 | **確認 — reverse path check fail, drop** |
| 7 | HQ2 防火牆政策阻擋 | 加 static route 後再測 | **確認 — Denied by forward policy check** |

### 根因：三層阻擋

```
遠端 Fortigate                        HQ2 (TWCH-HQ2-101F-1)                stwrconfig6
     |                                        |                               |
     |  execute backup config sftp             |                               |
     |  (FortiOS local-out traffic)            |                               |
     |                                         |                               |
     |  [問題 1] Source IP = WAN 公網 IP        |                               |
     |  (非內網 IP，FortiOS 行為)               |                               |
     |                                         |                               |
     |-------- IPSec Tunnel -------->          |                               |
     |  src: 61.216.106.145 (WAN IP)           |                               |
     |  dst: 172.16.5.124:2222                 |                               |
     |                                         |                               |
     |                              [問題 2] RPF Check Fail                    |
     |                              (61.216.106.145 的反向路徑                  |
     |                               不是這條 tunnel → DROP)                   |
     |                                         |                               |
     |                              (加 static route 修復 RPF 後)              |
     |                                         |                               |
     |                              [問題 3] Firewall Policy Deny              |
     |                              (tunnel→port1, src=公網 IP                 |
     |                               不匹配任何允許規則 → DROP)                |
     |                                         |                               |
```

#### 問題 1: FortiOS Local-Out Traffic 來源 IP

`execute backup config sftp` 屬於 FortiOS **管理平面 (management plane)** 的 local-out traffic：

- 不經過防火牆政策 (firewall policy)
- 不受 SD-WAN 規則控制
- **來源 IP 預設是出口介面的 IP**（通常是 WAN 介面的公網 IP）
- SD-WAN member 的 `set source` 僅對 transit traffic 生效，對 local-out 無效
- Automation Action (CLI script 類型) 沒有 `source-ip` 選項可設定
- **FortiOS v7.4.0+ 可透過 `preferred-source` 覆寫來源 IP**（見解法 C）

**診斷證據** (UAIC debug flow):
```
msg="vd-root:0 received a packet(proto=6, 61.216.106.145:13023->172.16.5.124:2222)
     tun_id=0.0.0.0 from local"
```

#### 問題 2: HQ2 RPF (Reverse Path Forwarding) 檢查失敗

HQ2 收到來自 tunnel 的封包，來源 IP 為 `61.216.106.145`：
- RPF 反向查詢：「我要回覆 61.216.106.145，路由會走哪裡？」
- 答案：預設路由 → WAN（不是這條 tunnel）
- 結論：**來源偽造 (spoofed) → 丟棄**

**診斷證據** (HQ2 debug flow):
```
func=ip_route_input_slow line=2268 msg="reverse path check fail, drop"
```

**修復**: 在 HQ2 加 static route `61.216.106.145/32 via PCCTW-UAIC_L`，RPF 通過。

#### 問題 3: HQ2 防火牆政策無匹配規則

RPF 通過後，HQ2 進行防火牆政策比對：
- 入口介面: `PCCTW-UAIC_L` (tunnel)
- 出口介面: `port1` (to stwrconfig6)
- 來源: `61.216.106.145` (公網 IP)
- 現有 tunnel→port1 政策僅允許內網網段 (172.x.x.x / 10.x.x.x)
- **公網 IP 不匹配 → implicit deny (policy 0)**

**診斷證據** (HQ2 debug flow):
```
func=fw_forward_handler line=829 msg="Denied by forward policy check (policy 0)"
```

### 為什麼 TW-TC-FortiGate-121G 能成功？

| 項目 | 121G (成功) | UAIC (失敗) |
|------|------------|-------------|
| VPN 類型 | leased line (專線) | internet IPSec |
| 連線路徑 | 單一隧道 PCCTC-CH_L | ECMP 多隧道 |
| Local-out 來源 IP | 172.23.175.175 (專線介面 IP) | 61.216.106.145 (WAN 公網 IP) |
| HQ2 RPF | 通過 (內網 IP，路由正常) | 失敗 (公網 IP，反向路由不匹配) |
| HQ2 防火牆政策 | 匹配 (內網 IP 在允許範圍) | 不匹配 (公網 IP 不在任何 address object) |

**關鍵差異**: 專線隧道的出口介面 IP 是內網 IP，internet VPN 的出口介面 IP 是公網 IP。

---

## 3. 解法比較

### 解法 A: IPSec Tunnel 路由修復 (逐台修)

**原理**: 維持現有架構，在 HQ2 為每台遠端 FG 的 WAN IP 加上 static route + firewall policy。

#### 每台遠端 FG 需要的設定

**在遠端 FG 上**:
```
# 強制走 leased line tunnel（避免 ECMP 選到 internet tunnel）
config router static
    edit <next-id>
        set dst 172.16.5.124 255.255.255.255
        set device "<leased-line-tunnel-name>"
    next
end
```

**在 HQ2 上**:
```
# 1. 修復 RPF：加回程路由
config router static
    edit <next-id>
        set dst <remote-FG-WAN-IP> 255.255.255.255
        set device "<corresponding-tunnel-name>"
    next
end

# 2. 修復防火牆政策：允許公網 IP 來源
config firewall address
    edit "<remote-FG-name>-WAN"
        set subnet <remote-FG-WAN-IP> 255.255.255.255
    next
end

# 建立 address group 或逐一加入政策
config firewall policy
    edit 0
        set name "Remote-FG-SFTP-to-rconfig"
        set srcintf "<tunnel-interface>"
        set dstintf "port1"
        set srcaddr "<remote-FG-name>-WAN"
        set dstaddr "stwrconfig6"
        set action accept
        set schedule "always"
        set service "SFTP-2222"
        set logtraffic all
    next
end
```

#### 優點

- 流量走私網隧道，不暴露 SFTP 於公網
- 不需要額外的公網 port 開放
- 符合既有 VPN 架構設計意圖

#### 缺點

- **每台遠端 FG 都要改** (static route)
- **HQ2 需為每台加 static route + address object + policy**（7 台 = 7 條 route + 7 個 address）
- 遠端 FG 的 WAN IP 若變動（DHCP、ISP 更換），需同步更新 HQ2 的 route 和 address
- 部分遠端 FG 可能沒有 leased line tunnel，只能走 internet tunnel
- RPF + policy 的雙重修復增加排錯複雜度
- 對 FortiOS local-out 行為的 workaround，本質上是在對抗系統設計

#### 維護複雜度: **高**

| 項目 | 工作量 |
|------|--------|
| 新增 1 台遠端 FG | 遠端加 1 條 route + HQ2 加 1 條 route + 1 個 address + 更新 policy |
| 遠端 WAN IP 變動 | HQ2 改 route + address（需即時知道 IP 變了） |
| 排錯 | 需同時檢查 3 層：遠端 route → HQ2 RPF → HQ2 policy |
| 文件維護 | 需記錄每台的 WAN IP ↔ tunnel 對應關係 |

---

### 解法 B: Internet 直連 (VIP Port Forward)

**原理**: 在 HQ2 建立 VIP，將公網 IP:2222 NAT 到 stwrconfig6:2222，遠端 FG 直接走 internet 連線。

#### HQ2 設定

```
# 1. VIP: 公網 IP:2222 → stwrconfig6:2222
config firewall vip
    edit "VIP-SFTP-rconfig"
        set extip <HQ2-WAN-IP>
        set mappedip "172.16.5.124"
        set extintf "wan1"
        set portforward enable
        set extport 2222
        set mappedport 2222
    next
end

# 2. Address Group: 所有遠端 FG 的 WAN IP
config firewall address
    edit "TWTC-PA-101F-WAN"
        set subnet <IP> 255.255.255.255
    next
    edit "TW-TC-UAIC-FW-WAN"
        set subnet 61.216.106.145 255.255.255.255
    next
    # ... 其他遠端 FG
end

config firewall addrgrp
    edit "Remote-Fortigate-WAN-IPs"
        set member "TWTC-PA-101F-WAN" "TW-TC-UAIC-FW-WAN" ...
    next
end

# 3. Firewall Policy: WAN → stwrconfig6
config firewall policy
    edit 0
        set name "Remote-FG-SFTP-Internet"
        set srcintf "wan1"
        set dstintf "port1"
        set srcaddr "Remote-Fortigate-WAN-IPs"
        set dstaddr "VIP-SFTP-rconfig"
        set action accept
        set schedule "always"
        set service "SFTP-2222"
        set logtraffic all
    next
end
```

#### 遠端 FG 設定

```
# Automation Action 目標改為 HQ2 公網 IP
execute backup config sftp upload/<filename>.conf <HQ2-WAN-IP>:2222 autoinfra <password>
```

#### 優點

- **一次性設定**: HQ2 建 1 個 VIP + 1 條 policy + 1 個 address group，完成
- **新增遠端 FG 只需加 1 個 address** 到 group，不需改 route
- 不需要在遠端 FG 加 static route
- 不對抗 FortiOS local-out 行為（來源就是 WAN IP，走 internet 天經地義）
- 排錯簡單：連不上就是 policy 或 address 問題
- HQ2 本地的 4 台和 leased line 的 121G **不受影響**，維持原有 tunnel 路徑

#### 缺點

- SFTP port 2222 暴露於公網（需嚴格限制 srcaddr）
- 流量走 internet，非加密隧道（但 SFTP 本身有 SSH 加密）
- 依賴 HQ2 WAN IP 固定不變
- 遠端 FG WAN IP 變動時仍需更新 HQ2 的 address group（但僅 1 處）
- 備份檔案內容透過公網傳輸（Fortigate config 含敏感資訊，但有 SFTP/SSH 加密保護）

#### 維護複雜度: **低**

| 項目 | 工作量 |
|------|--------|
| 新增 1 台遠端 FG | HQ2 加 1 個 address 到 group + 遠端設 Automation Action |
| 遠端 WAN IP 變動 | HQ2 改 1 個 address object |
| 排錯 | 單層檢查：HQ2 policy 有沒有匹配 |
| 文件維護 | 僅需記錄 WAN IP 清單 |

---

### 解法 C: preferred-source (FortiOS v7.4.0+) — 已採用

**原理**: 在遠端 FG 的 static route 上設定 `preferred-source`，強制 local-out traffic 使用內網 IP 作為來源，從根源解決問題。

#### 官方文件依據

| 文件 | 連結 |
|------|------|
| FortiOS 7.4.0 New Features | [Allow better control over the source IP used by each egress interface for local out traffic](https://docs.fortinet.com/document/fortigate/7.4.0/new-features/184807/allow-better-control-over-the-source-ip-used-by-each-egress-interface-for-local-out-traffic) |
| CLI Reference (router static) | [config router static - FortiOS 7.4.0](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/522620/config-router-static) |
| SD-WAN preferred-source | [Defining a preferred source IP for local-out egress interfaces on SD-WAN members](https://docs.fortinet.com/document/fortigate/7.6.4/administration-guide/486222/defining-a-preferred-source-ip-for-local-out-egress-interfaces-on-sd-wan-members) |
| 技術文件: TFTP backup source IP | [Technical Tip: Directing FortiGate TFTP Backup Traffic Using a Specific Source IP Address](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Directing-FortiGate-TFTP-Backup-Traffic-Using-a/ta-p/399826) |
| 技術文件: Automation backup over IPsec | [Technical Tip: Configure automation backup over IPsec tunnel](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Configure-automation-backup-over-IPsec-tunnel/ta-p/197725) |
| 技術文件: preferred-source for local-out | [Technical Tip: Configuring preferred-source in source IP for local-out traffic](https://community.fortinet.com/t5/FortiGate/Technical-Tip-Configuring-preferred-source-in-source-IP-for/ta-p/271952) |

**關鍵說明**: `preferred-source` 是 FortiOS v7.4.0 引入的新功能，允許在 static route 上指定 local-out traffic 的來源 IP。使用此路由的本機產生流量（如 SFTP 備份）會以 `preferred-source` 的 IP 取代預設的介面 IP。

#### 每台遠端 FG 設定（僅需 1 條指令）

```
config router static
    edit <new-id>
        set dst 172.16.5.124 255.255.255.255
        set device "<any-tunnel-interface>"
        set preferred-source <該台的內網管理 IP>
    next
end
```

#### 實測驗證 (TW-TC-UAIC-FW, FortiOS v7.4.8)

**設定：**
```
config router static
    edit 120
        set dst 172.16.5.124 255.255.255.255
        set device "UAIC-PCCTW1"
        set preferred-source 172.23.199.251
    next
end
```

**修復前** (debug flow):
```
received a packet(proto=6, 61.216.106.145:13023->172.16.5.124:2222) from local
# → HQ2: reverse path check fail, drop
# → HQ2: Denied by forward policy check (policy 0)
```

**修復後** (debug flow):
```
received a packet(proto=6, 172.23.199.251:23606->172.16.5.124:2222) from local
# → SYN-ACK 正常回來 (flag [S.])
# → TCP 連線建立成功
# → "Send config file to sftp server OK."
```

#### HQ2 不需要任何修改

- 來源 IP 變為內網 IP (172.23.199.251)，與 121G (172.23.175.175) 走相同路徑
- RPF 檢查通過（172.23.x.x 的回程路由本就指向 tunnel）
- 防火牆政策通過（內網 IP 匹配現有 tunnel→port1 規則）

#### 優點

- **從根源解決問題** — 直接修正 local-out 來源 IP，不需要任何 workaround
- **僅需修改遠端 FG** — HQ2 零修改，不碰核心設備
- **每台只加 1 條 static route** — 設定最少
- **流量走既有 IPSec 隧道** — 安全性最高，不暴露公網 port
- **FortiOS 官方支援功能** — 不是 hack，是 Fortinet 設計的解法
- **排錯簡單** — 只需檢查遠端 FG 的 route 有沒有 `preferred-source`

#### 缺點

- **要求 FortiOS >= 7.4.0** — 舊版本不支援
- 每台遠端 FG 仍需手動加 route（但僅 1 條，且 HQ2 不用動）
- `device` 為必填欄位，需指定 tunnel interface

#### 維護複雜度: **極低**

| 項目 | 工作量 |
|------|--------|
| 新增 1 台遠端 FG | 遠端加 1 條 route（含 preferred-source），HQ2 不動 |
| 遠端 WAN IP 變動 | 不影響（preferred-source 用的是內網 IP） |
| 排錯 | 單層檢查：遠端 route 有沒有 preferred-source |
| 文件維護 | 僅需記錄每台的內網管理 IP |

---

## 4. 綜合比較

| 面向 | 解法 A (Tunnel 修復) | 解法 B (Internet VIP) | 解法 C (preferred-source) |
|------|---------------------|----------------------|--------------------------|
| **設定複雜度** | 高 (每台 3~4 項設定) | 低 (HQ2 一次性 + 每台 1 項) | **極低 (每台 1 條 route)** |
| **維護複雜度** | 高 (多處同步更新) | 低 (單點更新) | **極低 (僅遠端 FG)** |
| **安全性** | 高 (流量在 VPN 隧道內) | 中 (SFTP/SSH 加密，但暴露公網 port) | **高 (流量在 VPN 隧道內)** |
| **排錯難度** | 高 (3 層排查) | 低 (1 層排查) | **低 (1 層排查)** |
| **對既有架構的影響** | 低 (利用現有隧道) | 中 (新增 VIP + 公網 port) | **無 (HQ2 零修改)** |
| **擴展性** | 差 (每台都要手動處理) | 好 (加 address 即可) | **好 (每台加 1 條 route)** |
| **FortiOS 相容性** | 差 (對抗 local-out 行為) | 好 (順應 local-out 行為) | **最佳 (官方設計功能)** |
| **WAN IP 變動容忍度** | 差 (需改 route + address) | 中 (僅改 address) | **完全不受影響** |
| **版本要求** | 無 | 無 | **FortiOS >= 7.4.0** |
| **建議適用場景** | 舊版 FortiOS + 安全性極高 | 舊版 FortiOS + 追求簡單 | **v7.4.0+ 環境 (首選)** |

---

## 5. 最終決策

**採用解法 C (preferred-source)**，原因：

1. **官方功能** — `preferred-source` 是 Fortinet 在 v7.4.0 專門為此場景設計的功能，不是 workaround
2. **從根源解決** — 直接修正 local-out 來源 IP，HQ2 不需要任何修改
3. **設定最少** — 每台遠端 FG 只加 1 條 static route
4. **安全性最高** — 流量走既有 IPSec 隧道，不暴露公網 port
5. **WAN IP 無關** — 使用內網 IP 作為 preferred-source，WAN IP 變動完全不受影響
6. **已驗證** — TW-TC-UAIC-FW (FortiOS v7.4.8) 實測成功

### Fallback 方案

若遇到 FortiOS < 7.4.0 的設備，改用解法 B (Internet VIP) 作為備選。

---

## 6. 實施狀態

### 已完成

| 設備 | 設定 | 狀態 |
|------|------|------|
| TW-TC-UAIC-FW | static route #120: dst 172.16.5.124/32, device UAIC-PCCTW1, preferred-source 172.23.199.251 | 已設定，測試通過 |

### 待實施 (需確認 FortiOS >= 7.4.0)

| 設備 | 內網管理 IP | 需執行指令 |
|------|------------|-----------|
| TWTC-PA-101F | 172.23.127.9 | `set preferred-source 172.23.127.9` |
| TW-TP-BaoYu-FortiGate60E | 172.23.94.9 | `set preferred-source 172.23.94.9` |
| TW-TP-XinYi-FortiGate60E | 172.23.110.30 | `set preferred-source 172.23.110.30` |
| IN-Kavin-60E | 172.25.128.254 | `set preferred-source 172.25.128.254` |
| IN-VSP-60E | 172.25.136.254 | `set preferred-source 172.25.136.254` |

### 已清理

| 設備 | 設定 | 狀態 |
|------|------|------|
| HQ2 (TWCH-HQ2-101F-1) | static route: dst 61.216.106.145/32 via PCCTW-UAIC_L | 已刪除 |

---

## 7. 診斷指令備忘

以下為本次排查中使用的關鍵診斷指令，供未來參考：

```bash
# 封包抓取 (Fortigate)
diagnose sniffer packet any "host <IP> and port 2222" 4 10

# 封包路徑追蹤 (Fortigate)
diagnose debug flow filter addr <IP>
diagnose debug flow filter port 2222
diagnose debug flow trace start 20
diagnose debug enable
# ... 觸發流量後 ...
diagnose debug flow trace stop
diagnose debug disable

# 防火牆政策查詢 (Fortigate)
diagnose firewall iprope lookup <src-IP> <dst-IP> 6 0 <dst-port>

# 路由查詢 (Fortigate)
get router info routing-table details <IP>

# SFTP 容器日誌 (stwrconfig6)
docker logs rconfig-bridge-sftp --tail 50

# 主機封包抓取 (stwrconfig6)
tcpdump -i any port 2222 -nn

# UFW 規則確認 (stwrconfig6)
ufw status | grep 2222
```

---

**文件建立**: 2026-03-27
**作者**: Max Fung
