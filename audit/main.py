# ==========================================
# FortiGate 帳號清冊 - CLI 入口
# ==========================================
#
# 用法：
#
#   # 掃描平層目錄（手動備份）
#   python -m audit.main --config-dir /tmp/audit_input/
#
#   # 直接掃描 rconfig 目錄，自動取每台設備最新備份
#   python -m audit.main --rconfig-dir /var/www/html/rconfig/storage/app/rconfig/data/FortigateFirewalls/
#
#   # 輸出 JSON 報告
#   python -m audit.main --rconfig-dir /var/.../FortigateFirewalls/ --output /tmp/report.json
#

import argparse
import json
import logging
import sys
import tempfile
import shutil
from pathlib import Path

from .auditor import AdminAuditor

# 分類設定檔預設與 main.py 同目錄（audit/audit_config.yaml）
_DEFAULT_CONFIG = Path(__file__).parent / 'audit_config.yaml'


def setup_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def collect_latest_configs(rconfig_dir: Path, tmp_dir: Path, logger) -> int:
    """
    從 rconfig FortigateFirewalls 目錄結構中，取每台設備最新的 show_*.txt，
    複製到 tmp_dir（平層），回傳複製成功的台數。

    目錄結構：
        {rconfig_dir}/{device_name}/{YYYY}/{Mon}/{DD}/show_{HHmm}.txt
    """
    if not rconfig_dir.is_dir():
        logger.error(f"❌ rconfig 目錄不存在: {rconfig_dir}")
        return 0

    count = 0
    for device_dir in sorted(rconfig_dir.iterdir()):
        if not device_dir.is_dir():
            continue

        # 找出所有 show_*.txt，依路徑排序取最新（路徑包含年月日，字串排序即時間排序）
        candidates = sorted(device_dir.rglob('show_*.txt'))
        if not candidates:
            logger.warning(f"⚠️ {device_dir.name}: 沒有找到備份檔案，略過")
            continue

        latest = candidates[-1]
        dest = tmp_dir / f"{device_dir.name}.txt"
        shutil.copy2(latest, dest)
        logger.debug(f"📋 {device_dir.name}: 使用 {latest.relative_to(rconfig_dir)}")
        count += 1

    return count


def main():
    parser = argparse.ArgumentParser(
        description='FortiGate 帳號清冊工具 - 分類帳號角色，輸出 Grafana 相容 JSON 報告',
    )

    # 輸入來源（二擇一）
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
        tmp_dir = Path(tempfile.mkdtemp(prefix='fg_audit_'))
        logger.info(f"📂 rconfig 模式：從 {rconfig_dir} 收集最新備份")
        count = collect_latest_configs(rconfig_dir, tmp_dir, logger)
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