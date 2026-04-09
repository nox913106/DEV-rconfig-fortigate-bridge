# ==========================================
# FortiGate 帳號稽核 - CLI 入口
# ==========================================
#
# 用法：
#   python -m audit.main --config-dir /path/to/configs
#   python -m audit.main --config-dir /path/to/configs --whitelist audit_config.yaml --output report.json
#

import argparse
import json
import logging
import sys
from pathlib import Path

from .auditor import AdminAuditor


def setup_logging(log_level: str) -> None:
    """設定日誌格式（與 bridge.py 一致的風格）"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    parser = argparse.ArgumentParser(
        description='FortiGate 帳號稽核工具 - 掃描 config 檔案，比對白名單，輸出 JSON 報告',
    )
    parser.add_argument(
        '--config-dir',
        required=True,
        help='FortiGate config 檔案目錄路徑',
    )
    parser.add_argument(
        '--whitelist',
        default='audit_config.yaml',
        help='白名單設定檔路徑（預設：audit_config.yaml）',
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

    # ---- 設定日誌 ----
    setup_logging(args.log_level)
    logger = logging.getLogger('FortigateAudit')

    logger.info("🚀 FortiGate 帳號稽核工具啟動")

    # ---- 驗證路徑 ----
    config_dir = Path(args.config_dir)
    if not config_dir.is_dir():
        logger.error(f"❌ config 目錄不存在: {config_dir}")
        sys.exit(1)

    whitelist_path = Path(args.whitelist)
    if not whitelist_path.is_file():
        logger.warning(f"⚠️ 白名單設定檔不存在: {whitelist_path}，將使用空白名單")

    # ---- 執行稽核 ----
    auditor = AdminAuditor(whitelist_path)
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

    # ---- 回傳退出碼 ----
    unknown_count = report['totals']['unknown']
    if unknown_count > 0:
        logger.warning(f"⚠️ 發現 {unknown_count} 個需關注帳號，請確認是否授權")
        sys.exit(2)  # 退出碼 2 = 有需關注帳號（可用於排程告警判斷）

    logger.info("✅ 所有帳號已分類完成，無需關注帳號")
    sys.exit(0)


if __name__ == '__main__':
    main()
