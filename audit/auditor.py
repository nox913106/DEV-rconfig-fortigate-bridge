# ==========================================
# FortiGate 帳號清冊引擎
# 分類統計 + Grafana 相容 JSON 輸出
# ==========================================

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from .parser import parse_config_file

logger = logging.getLogger('FortigateAudit')

# 台灣時區 UTC+8
TW_TZ = timezone(timedelta(hours=8))

# 支援的 config 副檔名
CONFIG_EXTENSIONS = {'.conf', '.txt'}

# 帳號分類定義（用於報告標籤與欄位順序）
CATEGORIES = ['local_rw', 'local_ro', 'remote_rw', 'remote_guest', 'api_ro', 'unknown']

CATEGORY_LABELS = {
    'local_rw':     '本機 R/W 管理員',
    'local_ro':     '本機 RO 管理員',
    'remote_rw':    '遠端 R/W 管理員',
    'remote_guest': 'Guest Wi-Fi 管理員',
    'api_ro':       'API RO 管理員',
    'unknown':      '未知帳號',
}


class AdminAuditor:
    """FortiGate 帳號清冊引擎"""

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self._cfg = self._load_config()

        # 建立 name → category 反查表
        named = self._cfg.get('account_categories', {}).get('named_accounts', {})
        self._name_to_category: dict[str, str] = {}
        for category, names in named.items():
            for name in (names or []):
                self._name_to_category[name] = category

        # 建立 remote_group → category 反查表
        group_cats = self._cfg.get('account_categories', {}).get('remote_group_categories', {})
        self._group_to_category: dict[str, str] = {}
        for category, groups in group_cats.items():
            for group in (groups or []):
                self._group_to_category[group] = category

    def _load_config(self) -> dict:
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            logger.info(f"✅ 載入分類設定: {self.config_path.name}")
            return cfg or {}
        except FileNotFoundError:
            logger.error(f"❌ 找不到分類設定檔: {self.config_path}")
            return {}
        except yaml.YAMLError as e:
            logger.error(f"❌ 分類設定 YAML 格式錯誤: {e}")
            return {}

    def categorize(self, account: dict, account_type: str) -> str:
        """
        判斷帳號所屬分類。

        優先順序：
        1. api_user 區段的帳號 → api_ro
        2. 帳號名稱在 named_accounts → 對應分類
        3. remote_group 在 remote_group_categories → 對應分類
        4. 以上皆不符 → unknown
        """
        if account_type == 'api_user':
            return 'api_ro'

        name = account.get('name', '')
        if name in self._name_to_category:
            return self._name_to_category[name]

        remote_group = account.get('remote_group')
        if remote_group and remote_group in self._group_to_category:
            return self._group_to_category[remote_group]

        return 'unknown'

    def audit_single(self, config_path: Path) -> dict | None:
        """
        解析單一 config 檔案，回傳該防火牆的帳號清冊。

        Returns:
            {
                "hostname": "TWCH-HQ2-201F-01",
                "config_file": "TWCH-HQ2-201F-01.txt",
                "counts": {"local_rw": 1, "local_ro": 1, ...},
                "total": 10,
                "accounts": [...]   ← 扁平化帳號清單（供 Grafana 用）
            }
        """
        parsed = parse_config_file(config_path)
        if parsed is None:
            return None

        hostname = parsed['hostname']
        counts = {cat: 0 for cat in CATEGORIES}
        accounts = []

        for account_type in ('system_admin', 'api_user'):
            for account in parsed[account_type]:
                category = self.categorize(account, account_type)
                counts[category] += 1

                accounts.append({
                    'firewall':       hostname,
                    'config_file':    config_path.name,
                    'account_type':   account_type,
                    'name':           account['name'],
                    'category':       category,
                    'category_label': CATEGORY_LABELS[category],
                    'accprofile':     account.get('accprofile'),
                    'remote_group':   account.get('remote_group'),
                })

                if category == 'unknown':
                    logger.warning(
                        f"⚠️ 未知帳號: [{hostname}] {account['name']} "
                        f"(accprofile={account.get('accprofile')}, "
                        f"remote_group={account.get('remote_group')})"
                    )

        total = sum(counts.values())
        status = "❌" if counts['unknown'] > 0 else "✅"
        logger.info(
            f"{status} {hostname}: {total} 帳號 "
            f"(local={counts['local_rw']+counts['local_ro']}, "
            f"remote_rw={counts['remote_rw']}, "
            f"guest={counts['remote_guest']}, "
            f"api={counts['api_ro']}, "
            f"unknown={counts['unknown']})"
        )

        return {
            'hostname':    hostname,
            'config_file': config_path.name,
            'counts':      counts,
            'total':       total,
        }, accounts

    def audit_directory(self, config_dir: Path) -> dict:
        """
        掃描目錄下所有 config 檔案，產生完整帳號清冊報告。

        輸出格式（Grafana Infinity 外掛相容）：
        {
            "scan_time": "...",
            "firewalls": [...],   ← 每台一列，含各分類數量（統計表格用）
            "accounts": [...],    ← 每個帳號一列（清單表格用）
            "totals": {...}       ← 全域加總
        }
        """
        config_dir = Path(config_dir)
        config_files = sorted(
            f for f in config_dir.iterdir()
            if f.is_file() and f.suffix in CONFIG_EXTENSIONS
        )

        if not config_files:
            logger.warning(f"⚠️ 目錄中沒有 config 檔案: {config_dir}")
            return self._empty_report(str(config_dir))

        logger.info(f"📂 掃描 {len(config_files)} 個 config 檔案: {config_dir}")

        firewalls = []
        all_accounts = []
        totals = {cat: 0 for cat in CATEGORIES}
        totals['total_accounts'] = 0
        totals['total_firewalls'] = 0

        for config_file in config_files:
            result = self.audit_single(config_file)
            if result is None:
                continue
            fw_summary, accounts = result

            firewalls.append(fw_summary)
            all_accounts.extend(accounts)

            for cat in CATEGORIES:
                totals[cat] += fw_summary['counts'][cat]
            totals['total_accounts'] += fw_summary['total']
            totals['total_firewalls'] += 1

        unknown_total = totals['unknown']
        logger.info(
            f"📊 清冊完成: {totals['total_firewalls']} 台防火牆, "
            f"{totals['total_accounts']} 帳號"
            + (f", ⚠️ {unknown_total} 個未知帳號需確認" if unknown_total else "")
        )

        return {
            'scan_time':    datetime.now(TW_TZ).isoformat(),
            'config_dir':   str(config_dir),
            'firewalls':    firewalls,
            'accounts':     all_accounts,
            'totals':       totals,
        }

    def _empty_report(self, config_dir: str) -> dict:
        return {
            'scan_time':  datetime.now(TW_TZ).isoformat(),
            'config_dir': config_dir,
            'firewalls':  [],
            'accounts':   [],
            'totals':     {cat: 0 for cat in CATEGORIES} | {
                'total_accounts': 0,
                'total_firewalls': 0,
            },
        }