# ==========================================
# FortiGate 帳號清冊 - CLI 入口
# ==========================================
#
# 用法：
#
#   # 掃描平層目錄（手動備份）
#   python -m audit.main --config-dir /tmp/audit_input/
#
#   # 直接掃描 rconfig 目錄，自動取每台設備最新備份（掃全部）
#   python -m audit.main --rconfig-dir /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/
#
#   # 從 rconfig DB 過濾有效設備（推薦，自動排除舊目錄）
#   python -m audit.main --rconfig-dir /var/.../FortigateFirewalls/ --db-filter --output /tmp/report.json
#

import argparse
import json
import logging
import os
import sys
import tempfile
import shutil
from pathlib import Path

from .auditor import AdminAuditor

# 分類設定檔預設與 main.py 同目錄（audit/audit_config.yaml）
_DEFAULT_CONFIG = Path(__file__).parent / 'audit_config.yaml'

# rconfig DB 中 FortigateFirewalls category ID
FORTIGATE_CATEGORY_ID = 8


def setup_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def get_active_devices_from_db(logger) -> set[str] | None:
    """
    從 rconfig DB 查詢 FortigateFirewalls category 下的有效設備名稱。
    連線資訊從環境變數（.env）讀取。

    Returns:
        有效 device_name 的 set，或 None（連線失敗時）
    """
    try:
        import pymysql
    except ImportError:
        logger.error("❌ 缺少 pymysql，請執行: pip3 install pymysql")
        return None

    host = os.getenv('RCONFIG_DB_HOST', '127.0.0.1')
    # audit 工具在宿主機直接執行，不走 Docker 橋接網路
    # 若 .env 填的是 Docker 閘道 IP（192.168.254.1），自動改用 127.0.0.1
    if host == '192.168.254.1':
        host = '127.0.0.1'
    port = int(os.getenv('RCONFIG_DB_PORT', '3306'))
    user = os.getenv('RCONFIG_DB_USER', 'pcc_rconfig')
    password = os.getenv('RCONFIG_DB_PASSWORD', '')
    database = os.getenv('RCONFIG_DB_NAME', 'rconfig')

    try:
        conn = pymysql.connect(
            host=host, port=port, user=user,
            password=password, database=database,
            connect_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.device_name
                FROM devices d
                JOIN category_device cd ON cd.device_id = d.id
                WHERE cd.category_id = %s
                """,
                (FORTIGATE_CATEGORY_ID,)
            )
            rows = cur.fetchall()
        conn.close()

        devices = {row[0] for row in rows}
        logger.info(f"✅ 從 DB 取得 {len(devices)} 台有效 FortiGate 設備")
        return devices

    except Exception as e:
        logger.error(f"❌ DB 查詢失敗: {e}")
        return None


def collect_latest_configs(rconfig_dir: Path, tmp_dir: Path, logger,
                           allowed_devices: set[str] | None = None) -> int:
    """
    從 rconfig FortigateFirewalls 目錄結構中，取每台設備最新的 show_*.txt，
    複製到 tmp_dir（平層），回傳複製成功的台數。

    allowed_devices: 若指定，只掃清單內的目錄名稱（None 表示全掃）
    """
    if not rconfig_dir.is_dir():
        logger.error(f"❌ rconfig 目錄不存在: {rconfig_dir}")
        return 0

    count = 0
    skipped = 0
    for device_dir in sorted(rconfig_dir.iterdir()):
        if not device_dir.is_dir():
            continue

        if allowed_devices is not None and device_dir.name not in allowed_devices:
            logger.debug(f"⏭️  略過舊目錄: {device_dir.name}")
            skipped += 1
            continue

        candidates = sorted(device_dir.rglob('show_*.txt'))
        if not candidates:
            logger.warning(f"⚠️ {device_dir.name}: 沒有找到備份檔案，略過")
            continue

        latest = candidates[-1]
        dest = tmp_dir / f"{device_dir.name}.txt"
        shutil.copy2(latest, dest)
        logger.debug(f"📋 {device_dir.name}: 使用 {latest.relative_to(rconfig_dir)}")
        count += 1

    if skipped:
        logger.info(f"⏭️  略過 {skipped} 個舊目錄（不在 DB 有效設備清單中）")

    return count


def main():
    parser = argparse.ArgumentParser(
        description='FortiGate 帳號清冊工具 - 分類帳號角色，輸出 Grafana 相容 JSON 報告',
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        '--config-dir',
        help='平層 config 目錄（每台一個 .conf/.txt 檔案）',
    )
    source_group.add_argument(
        '--rconfig-dir',
        help='rconfig FortigateFirewalls 目錄，自動取每台設備最新備份',
    )

    parser.add_argument(
        '--db-filter',
        action='store_true',
        default=False,
        help='從 rconfig DB 查詢有效設備清單，自動排除已停用/更名的舊目錄（推薦）',
    )
    parser.add_argument(
        '--config',
        default=str(_DEFAULT_CONFIG),
        help=f'分類設定檔路徑（預設：{_DEFAULT_CONFIG}）',
    )
    parser.add_argument(
        '--output',
        default=None,
        help='JSON 報告輸出路徑（預設：stdout）',
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='日誌級別（預設：INFO）',
    )

    args = parser.parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger('FortigateAudit')
    logger.info("🚀 FortiGate 帳號清冊工具啟動")

    # ---- 決定掃描目錄 ----
    tmp_dir = None
    if args.rconfig_dir:
        rconfig_dir = Path(args.rconfig_dir)

        # 載入 .env（讓 DB 連線資訊可用）
        env_path = Path(__file__).parent.parent / '.env'
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    os.environ.setdefault(k.strip(), v.strip())

        # DB 過濾
        allowed_devices = None
        if args.db_filter:
            allowed_devices = get_active_devices_from_db(logger)
            if allowed_devices is None:
                logger.error("❌ 無法從 DB 取得設備清單，中止執行")
                sys.exit(1)

        tmp_dir = Path(tempfile.mkdtemp(prefix='fg_audit_'))
        logger.info(f"📂 rconfig 模式：從 {rconfig_dir} 收集最新備份")
        count = collect_latest_configs(rconfig_dir, tmp_dir, logger, allowed_devices)
        if count == 0:
            logger.error("❌ 沒有收集到任何備份檔案")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            sys.exit(1)
        logger.info(f"✅ 已收集 {count} 台設備的最新備份")
        scan_dir = tmp_dir
    else:
        scan_dir = Path(args.config_dir)
        if not scan_dir.is_dir():
            logger.error(f"❌ config 目錄不存在: {scan_dir}")
            sys.exit(1)

    # ---- 執行清冊 ----
    try:
        auditor = AdminAuditor(Path(args.config))
        report = auditor.audit_directory(scan_dir)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---- 輸出報告 ----
    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_json, encoding='utf-8')
        logger.info(f"📄 報告已寫入: {output_path}")
    else:
        print(report_json)

    # ---- 退出碼 ----
    unknown_count = report['totals']['unknown']
    if unknown_count > 0:
        logger.warning(f"⚠️ 發現 {unknown_count} 個需關注帳號，請確認是否授權")
        sys.exit(2)

    logger.info("✅ 所有帳號已分類完成，無需關注帳號")
    sys.exit(0)


if __name__ == '__main__':
    main()