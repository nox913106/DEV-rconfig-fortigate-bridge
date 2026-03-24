#!/usr/bin/env python3
"""
rconfig Fortigate Bridge - Watcher Service
監控 SFTP 上傳目錄，自動轉存 Fortigate 完整備份檔到 rconfig
"""

import os
import re
import sys
import time
import shutil
import logging
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import pymysql

# ==========================================
# 配置與環境變數
# ==========================================
INCOMING_DIR = Path(os.getenv('INCOMING_DIR', '/app/incoming'))
RCONFIG_DATA_DIR = Path(os.getenv('RCONFIG_DATA_DIR', '/rconfig/storage/app/rconfig/data'))
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# rconfig 資料庫連線
DB_CONFIG = {
    'host': os.getenv('RCONFIG_DB_HOST', 'localhost'),
    'port': int(os.getenv('RCONFIG_DB_PORT', 3306)),
    'user': os.getenv('RCONFIG_DB_USER', 'pcc_rconfig'),
    'password': os.getenv('RCONFIG_DB_PASSWORD'),
    'database': os.getenv('RCONFIG_DB_NAME', 'rconfig'),
    'charset': 'utf8mb4',
}

# ==========================================
# 日誌設定
# ==========================================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/bridge/watcher.log')
    ]
)
logger = logging.getLogger('RconfigBridge')


# ==========================================
# 資料庫連線管理
# ==========================================
class RconfigDB:
    """rconfig 資料庫連線管理"""

    def __init__(self, config):
        self.config = config
        self.conn = None

    def connect(self):
        """建立資料庫連線"""
        try:
            self.conn = pymysql.connect(**self.config)
            logger.info("✅ 已連線到 rconfig 資料庫")
            return True
        except Exception as e:
            logger.error(f"❌ 無法連線到 rconfig 資料庫: {e}")
            return False

    def get_device_by_name(self, device_name):
        """根據設備名稱查詢設備資訊"""
        try:
            with self.conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    "SELECT id, device_name FROM devices WHERE device_name = %s",
                    (device_name,)
                )
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"查詢設備失敗 ({device_name}): {e}")
            return None

    def get_latest_config_id(self, device_id):
        """查詢設備最新的 config ID"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM configs WHERE device_id = %s ORDER BY created_at DESC LIMIT 1",
                    (device_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"查詢 config ID 失敗 (device_id={device_id}): {e}")
            return None


# ==========================================
# 檔案處理邏輯
# ==========================================
class FortigateBridge:
    """Fortigate 備份檔轉存邏輯"""

    # Fortigate 備份檔名格式（Fortigate 會自動加上序列號前綴）：
    # 實際檔名：FG201FT922913515_TWCH-HQ2-201F-01-172-16-11-3-20260324.conf
    # 去除前綴後：TWCH-HQ2-201F-01-172-16-11-3-20260324.conf
    # 解析策略：從後向前 → timestamp(>=8位數字) → IP(4段數字) → hostname(剩餘)

    def __init__(self, db: RconfigDB):
        self.db = db

    def strip_serial_prefix(self, filename):
        """去除 Fortigate 自動加上的序列號前綴 (例如 FG201FT922913515_)"""
        if '_' in filename:
            prefix, rest = filename.split('_', 1)
            if prefix.startswith(('FG', 'FW', 'FL', 'FT')):
                logger.info(f"   去除序列號前綴: {prefix}")
                return rest
        return filename

    def parse_filename(self, filename):
        """解析 SFTP 上傳的檔名（從後向前解析，避免 hostname/IP 邊界混淆）"""
        # 1. 去除 Fortigate 序列號前綴
        clean_filename = self.strip_serial_prefix(filename)

        # 2. 驗證副檔名
        if not clean_filename.endswith('.conf'):
            logger.warning(f"⚠️ 非 .conf 檔案: {filename}")
            return None

        # 3. 去掉副檔名，用破折號分割
        name = clean_filename[:-5]  # 去掉 .conf
        parts = name.split('-')

        if len(parts) < 6:  # 最少需要：hostname(1) + IP(4) + timestamp(1)
            logger.warning(f"⚠️ 檔名段數不足: {filename}")
            return None

        # 4. 從後面找 timestamp（>= 8 位的純數字段）
        i = len(parts) - 1
        timestamp_parts = []

        # 先收集末尾的短數字段（可能是 HHmmss）
        while i >= 0 and parts[i].isdigit() and len(parts[i]) <= 6:
            timestamp_parts.insert(0, parts[i])
            i -= 1

        # 找到主要的日期段（>= 8 位數字）
        if i >= 0 and parts[i].isdigit() and len(parts[i]) >= 8:
            timestamp_parts.insert(0, parts[i])
            i -= 1
        elif not timestamp_parts:
            # 如果前面沒收集到短段，也沒找到長段，嘗試合併末尾
            logger.warning(f"⚠️ 找不到時間戳記: {filename}")
            return None
        else:
            # 短段本身可能就是完整 timestamp（如 20260324 被拆成多段的情況不存在）
            pass

        timestamp = '-'.join(timestamp_parts)

        # 5. 接下來的 4 段純數字（每段 <= 3 位）是 IP
        ip_parts = []
        for _ in range(4):
            if i >= 0 and parts[i].isdigit() and len(parts[i]) <= 3:
                ip_parts.insert(0, parts[i])
                i -= 1
            else:
                logger.warning(f"⚠️ 無法解析 IP 段: {filename}")
                return None

        ip = '-'.join(ip_parts)

        # 6. 剩餘的就是 hostname
        hostname = '-'.join(parts[:i + 1])
        if not hostname:
            logger.warning(f"⚠️ hostname 為空: {filename}")
            return None

        return {
            'hostname': hostname,
            'ip': ip,
            'timestamp': timestamp,
        }

    def process_file(self, file_path: Path):
        """處理單一備份檔案"""
        logger.info(f"📥 開始處理: {file_path.name}")

        # 1. 解析檔名
        parsed = self.parse_filename(file_path.name)
        if not parsed:
            self.move_to_failed(file_path, "檔名格式錯誤")
            return False

        hostname = parsed['hostname']
        timestamp = parsed['timestamp']  # 格式：20260320-143000
        logger.info(f"   設備名稱: {hostname}")
        logger.info(f"   時間戳記: {timestamp}")

        # 2. 查詢 rconfig 資料庫取得設備 ID
        device = self.db.get_device_by_name(hostname)
        if not device:
            logger.warning(f"⚠️ 找不到設備: {hostname}")
            self.move_to_failed(file_path, f"設備不存在於 rconfig: {hostname}")
            return False

        device_id = device['id']
        logger.info(f"   設備 ID: {device_id}")

        # 3. 建立目標路徑（符合 rconfig 格式）
        now = datetime.now()
        target_dir = (
            RCONFIG_DATA_DIR /
            "FortigateFirewalls" /
            hostname /
            now.strftime('%Y/%b/%d')
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        # 4. 解析時間戳記取得 HHmm
        # 支援多種格式：
        # - 20260320-143000 → 1430
        # - 20260320153045 → 1530
        # - 20260320 → 使用當前時間
        try:
            # 移除所有破折號，取得純數字字串
            timestamp_clean = timestamp.replace('-', '')

            if len(timestamp_clean) >= 12:
                # 格式：YYYYMMDDHHmmss (14 位) 或 YYYYMMDDHHmm (12 位)
                hhmm = timestamp_clean[8:12]  # 取第 9-12 位 → HHmm
            elif len(timestamp_clean) == 8:
                # 格式：YYYYMMDD (僅日期，無時間)
                logger.warning(f"⚠️ 時間戳記僅包含日期，使用當前時間")
                hhmm = now.strftime('%H%M')
            else:
                raise ValueError(f"無法識別的時間戳記格式: {timestamp}")

            logger.info(f"   解析時間: {hhmm[:2]}:{hhmm[2:]}")

        except Exception as e:
            logger.warning(f"⚠️ 無法解析時間戳記 ({timestamp}): {e}，使用當前時間")
            hhmm = now.strftime('%H%M')

        # 5. 生成兩個檔案
        # (a) rconfig 格式：show_{HHmm}.txt (覆蓋現有備份)
        rconfig_file = target_dir / f"show_{hhmm}.txt"

        # (b) 原始檔案：保留完整檔名作為備份
        backup_file = target_dir / file_path.name

        logger.info(f"   rconfig 檔案: {rconfig_file.name}")
        logger.info(f"   備份檔案: {backup_file.name}")

        # 6. 複製檔案到 rconfig 目錄（兩份）
        try:
            # 複製為 rconfig 格式（覆蓋）
            shutil.copy2(file_path, rconfig_file)
            logger.info(f"✅ 已轉存為 rconfig 格式: {rconfig_file.name}")

            # 保留原始檔名
            shutil.copy2(file_path, backup_file)
            logger.info(f"✅ 已保留原始備份: {backup_file.name}")

            # 7. 刪除 SFTP 暫存檔案
            file_path.unlink()
            logger.info(f"   已清理暫存檔: {file_path.name}")

            return True

        except Exception as e:
            logger.error(f"❌ 轉存失敗: {e}")
            self.move_to_failed(file_path, str(e))
            return False

    def move_to_failed(self, file_path: Path, reason: str):
        """將失敗檔案移至 failed 目錄"""
        failed_dir = INCOMING_DIR / 'failed'
        failed_dir.mkdir(exist_ok=True)

        failed_file = failed_dir / file_path.name
        shutil.move(str(file_path), str(failed_file))

        # 寫入失敗原因
        reason_file = failed_dir / f"{file_path.name}.error.txt"
        reason_file.write_text(f"{datetime.now().isoformat()}\n{reason}\n")

        logger.error(f"❌ 檔案處理失敗，已移至 failed/: {file_path.name}")


# ==========================================
# Watchdog 事件處理器
# ==========================================
class SFTPUploadHandler(FileSystemEventHandler):
    """監控 SFTP 上傳目錄的事件處理器"""

    def __init__(self, bridge: FortigateBridge):
        self.bridge = bridge
        self.processing = set()  # 避免重複處理

    def on_created(self, event):
        """檔案建立事件"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # 只處理 .conf 檔案
        if file_path.suffix != '.conf':
            return

        # 避免重複處理
        if str(file_path) in self.processing:
            return

        self.processing.add(str(file_path))

        try:
            # 等待檔案完全上傳完成（檢查檔案大小穩定）
            time.sleep(2)
            self.bridge.process_file(file_path)
        finally:
            self.processing.discard(str(file_path))


# ==========================================
# 主程式
# ==========================================
def main():
    logger.info("=" * 60)
    logger.info("🚀 rconfig Fortigate Bridge - Watcher 啟動")
    logger.info("=" * 60)
    logger.info(f"   監控目錄: {INCOMING_DIR}")
    logger.info(f"   rconfig 目錄: {RCONFIG_DATA_DIR}")
    logger.info("=" * 60)

    # 1. 建立資料庫連線
    db = RconfigDB(DB_CONFIG)
    if not db.connect():
        logger.error("❌ 無法啟動 Watcher - 資料庫連線失敗")
        sys.exit(1)

    # 2. 建立 Bridge 處理器
    bridge = FortigateBridge(db)

    # 3. 建立 Watchdog Observer
    event_handler = SFTPUploadHandler(bridge)
    observer = Observer()
    observer.schedule(event_handler, str(INCOMING_DIR), recursive=False)
    observer.start()

    logger.info("✅ Watcher 已啟動，開始監控 SFTP 上傳...")

    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("⏹️  收到停止訊號，正在關閉 Watcher...")
        observer.stop()

    observer.join()
    logger.info("👋 Watcher 已停止")


if __name__ == '__main__':
    main()
