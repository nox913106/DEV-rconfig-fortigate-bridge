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

import yaml

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


def parse_backup_time(path: Path) -> str | None:
    """
    從備份路徑解析資料更新時間。
    路徑格式: .../FortigateFirewalls/{device}/{YYYY}/{Mon}/{DD}/show_{HHmm}.txt
    回傳格式: "2026-04-08 19:30 (UTC+8)"，解析失敗回傳 None
    """
    try:
        from datetime import datetime, timezone, timedelta
        parts = path.parts
        # 從後往前取: show_HHmm.txt / DD / Mon / YYYY
        filename = path.stem          # show_1930
        day      = parts[-2]          # 08
        month    = parts[-3]          # Apr
        year     = parts[-4]          # 2026
        hhmm     = filename.replace('show_', '')  # 1930
        # 解析為 datetime（rconfig 以台灣本地時間命名備份檔）
        dt = datetime.strptime(
            f"{year} {month} {day} {hhmm[:2]}:{hhmm[2:]}",
            "%Y %b %d %H:%M"
        ).replace(tzinfo=timezone(timedelta(hours=8)))
        return dt.strftime("%Y-%m-%d %H:%M (UTC+8)")
    except Exception:
        return None


def collect_latest_configs(rconfig_dir: Path, tmp_dir: Path, logger,
                           allowed_devices: set[str] | None = None) -> tuple[int, dict[str, str]]:
    """
    從 rconfig FortigateFirewalls 目錄結構中，取每台設備最新的 show_*.txt，
    複製到 tmp_dir（平層），回傳 (複製成功台數, {device_name: last_backup_time})。

    allowed_devices: 若指定，只掃清單內的目錄名稱（None 表示全掃）
    """
    if not rconfig_dir.is_dir():
        logger.error(f"❌ rconfig 目錄不存在: {rconfig_dir}")
        return 0, {}

    count = 0
    skipped = 0
    device_times: dict[str, str] = {}

    for device_dir in sorted(rconfig_dir.iterdir()):
        if not device_dir.is_dir():
            continue

        if allowed_devices is not None and device_dir.name not in allowed_devices:
            logger.debug(f"⏭️  略過舊目錄: {device_dir.name}")
            skipped += 1
            continue

        def _path_to_dt(p: Path):
            """路徑排序 key：解析 {YYYY}/{Mon}/{DD}/show_{HHmm}.txt → datetime（失敗用 mtime）"""
            try:
                from datetime import datetime as _dt
                parts = p.parts
                return _dt.strptime(
                    f"{parts[-4]} {parts[-3]} {parts[-2]} {p.stem.replace('show_', '')}",
                    "%Y %b %d %H%M"
                )
            except Exception:
                return p.stat().st_mtime

        candidates = sorted(device_dir.rglob('show_*.txt'), key=_path_to_dt)
        if not candidates:
            logger.warning(f"⚠️ {device_dir.name}: 沒有找到備份檔案，略過")
            continue

        latest = candidates[-1]
        dest = tmp_dir / f"{device_dir.name}.txt"
        shutil.copy2(latest, dest)

        backup_time = parse_backup_time(latest)
        if backup_time:
            device_times[device_dir.name] = backup_time

        logger.debug(f"📋 {device_dir.name}: 使用 {latest.relative_to(rconfig_dir)} ({backup_time})")
        count += 1

    if skipped:
        logger.info(f"⏭️  略過 {skipped} 個舊目錄（不在 DB 有效設備清單中）")

    return count, device_times


def query_tacacs_members(tacacs_cfg: dict, logger) -> list[str]:
    """
    從 LDAP 查詢 TACACS+ 群組成員清單。
    密碼從 tacacs_cfg['bind_pw_env'] 指定的環境變數讀取。
    查詢失敗時回傳空 list（不中斷主流程）。
    """
    try:
        from ldap3 import Server, Connection, ALL
    except ImportError:
        logger.warning("⚠️ 缺少 ldap3，跳過 TACACS 成員查詢。請執行: pip3 install ldap3")
        return []

    bind_pw = os.getenv(tacacs_cfg.get('bind_pw_env', ''), '')
    if not bind_pw:
        logger.warning("⚠️ 找不到 TACACS LDAP 密碼（環境變數未設定），跳過成員查詢")
        return []

    try:
        server = Server(tacacs_cfg['host'], get_info=ALL)
        conn = Connection(
            server,
            user=tacacs_cfg['bind_dn'],
            password=bind_pw,
            auto_bind=True,
        )
        conn.search(tacacs_cfg['group_dn'], '(objectClass=*)', attributes=['member'])
        if not conn.entries:
            return []
        members = []
        for dn in conn.entries[0]['member'].values:
            # uid=MAX.FUNG,ou=K0,c=tw,o=pcc → MAX.FUNG
            uid = dn.split(',')[0].replace('uid=', '')
            members.append(uid)
        conn.unbind()
        return sorted(members)
    except Exception as e:
        logger.warning(f"⚠️ TACACS 成員查詢失敗: {e}")
        return []


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
        count, device_times = collect_latest_configs(rconfig_dir, tmp_dir, logger, allowed_devices)
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
        report = auditor.audit_directory(scan_dir, device_times if args.rconfig_dir else {})
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---- 查詢 TACACS 成員 ----
    audit_cfg_raw = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    tacacs_cfg = audit_cfg_raw.get('tacacs_ldap')
    if tacacs_cfg:
        tacacs_members = query_tacacs_members(tacacs_cfg, logger)
        report['tacacs_members'] = tacacs_members
        logger.info(f"✅ TACACS 成員: {len(tacacs_members)} 人 {tacacs_members}")
    else:
        report['tacacs_members'] = []

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