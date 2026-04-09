# ==========================================
# FortiGate 帳號清冊 - CLI 入口
# ==========================================
#
# 用法：
#   python -m audit.main --config-dir /path/to/configs
#   python -m audit.main --config-dir /path/to/configs --output report.json
#   python -m audit.main --config-dir /path/to/configs --config /custom/audit_config.yaml
#

import argparse
import json
import logging
import sys
from pathlib import Path

from .auditor import AdminAuditor

# 預設分類設定檔與 main.py 同目錄（audit/audit_config.yaml）
_DEFAULT_CONFIG = Path(__file__).parent / 'audit_config.yaml'


def setup_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    parser = argparse.ArgumentParser(
        description='FortiGate 帳號清冊工具 - 掃描 config 檔案，分類帳號，輸出 JSON 報告',
    )
    parser.add_argument(
        '--config-dir',
        required=True,
        help='FortiGate config 檔案目錄路徑',
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

    config_dir = Path(args.config_dir)
    if not config_dir.is_dir():
        logger.error(f"❌ config 目錄不存在: {config_dir}")
        sys.exit(1)

    # ---- 執行清冊 ----
    auditor = AdminAuditor(Path(args.config))
    report = auditor.audit_directory(config_dir)

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