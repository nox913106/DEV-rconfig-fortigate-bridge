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

    # 檔名格式：fw01-192.168.1.1-20260320-143000.conf
    FILENAME_PATTERN = re.compile(
        r'^(?P<hostname>[\w\-]+)-(?P<ip>[\d\.]+)-(?P<timestamp>\d{8}-\d{6})\.conf$'
    )

    def __init__(self, db: RconfigDB):
        self.db = db

    def parse_filename(self, filename):
        """解析 SFTP 上傳的檔名"""
        match = self.FILENAME_PATTERN.match(filename)
        if not match:
            logger.warning(f"⚠️ 檔名格式不符: {filename}")
            return None

        return {
            'hostname': match.group('hostname'),
            'ip': match.group('ip'),
            'timestamp': match.group('timestamp'),
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
        logger.info(f"   設備名稱: {hostname}")

        # 2. 查詢 rconfig 資料庫取得設備 ID
        device = self.db.get_device_by_name(hostname)
        if not device:
            logger.warning(f"⚠️ 找不到設備: {hostname}")
            self.move_to_failed(file_path, f"設備不存在於 rconfig: {hostname}")
            return False

        device_id = device['id']
        logger.info(f"   設備 ID: {device_id}")

        # 3. 查詢最新的 config ID
        config_id = self.db.get_latest_config_id(device_id)
        if not config_id:
            logger.warning(f"⚠️ 找不到設備的 config 記錄: {hostname}")
            # 使用預設 ID（通常是設備首次備份時產生）
            config_id = device_id

        # 4. 建立目標路徑（符合 rconfig 格式）
        now = datetime.now()
        target_dir = (
            RCONFIG_DATA_DIR /
            "FortigateFirewalls" /
            hostname /
            now.strftime('%Y/%b/%d')
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        # 檔名格式：showrunning-config_{config_id}.conf
        target_file = target_dir / f"showrunning-config_{config_id}.conf"

        logger.info(f"   目標路徑: {target_file}")

        # 5. 複製檔案到 rconfig 目錄
        try:
            shutil.copy2(file_path, target_file)
            logger.info(f"✅ 成功轉存: {hostname} → {target_file}")

            # 6. 刪除 SFTP 暫存檔案
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
