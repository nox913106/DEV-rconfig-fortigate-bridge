# ==========================================
# FortiGate 帳號稽核引擎
# 白名單比對 + JSON 報告輸出
# ==========================================

import json
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


class AdminAuditor:
    """FortiGate 帳號稽核引擎"""

    def __init__(self, whitelist_path: Path):
        """
        載入白名單設定檔。

        Args:
            whitelist_path: audit_config.yaml 路徑
        """
        self.whitelist_path = Path(whitelist_path)
        self.config = self._load_whitelist()

    def _load_whitelist(self) -> dict:
        """載入並驗證白名單 YAML 設定"""
        try:
            with open(self.whitelist_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            if not config or 'global_whitelist' not in config:
                logger.warning("⚠️ 白名單設定檔缺少 global_whitelist，使用空白名單")
                return {
                    'global_whitelist': {},
                    'compliant_profiles': [],
                    'firewall_exceptions': {},
                }

            logger.info(f"✅ 載入白名單: {self.whitelist_path.name}")
            return config

        except FileNotFoundError:
            logger.error(f"❌ 找不到白名單設定檔: {self.whitelist_path}")
            return {
                'global_whitelist': {},
                'compliant_profiles': [],
                'firewall_exceptions': {},
            }
        except yaml.YAMLError as e:
            logger.error(f"❌ 白名單 YAML 格式錯誤: {e}")
            return {
                'global_whitelist': {},
                'compliant_profiles': [],
                'firewall_exceptions': {},
            }

    def get_whitelist(self, hostname: str, account_type: str) -> set:
        """
        取得合併後的名稱白名單（global + exceptions）。

        Args:
            hostname: 防火牆 hostname
            account_type: 'system_admin' 或 'api_user'

        Returns:
            合規帳號名稱的 set
        """
        global_list = self.config.get('global_whitelist', {}).get(account_type, [])
        allowed = set(global_list)

        exceptions = self.config.get('firewall_exceptions', {})
        if exceptions and hostname in exceptions:
            fw_list = exceptions[hostname].get(account_type, [])
            allowed.update(fw_list)

        return allowed

    def get_compliant_profiles(self) -> set:
        """取得合規 accprofile 清單"""
        profiles = self.config.get('compliant_profiles', [])
        return set(profiles) if profiles else set()

    def _is_compliant(self, name: str, accprofile: str | None,
                      whitelist: set, compliant_profiles: set) -> tuple[bool, str]:
        """
        判斷帳號是否合規。

        判定優先順序：
        1. 帳號名稱在白名單中 → 合規（依據：名稱白名單）
        2. accprofile 在合規 profile 清單中 → 合規（依據：profile 白名單）
        3. 以上皆非 → 不合規

        Returns:
            (is_compliant, reason)
        """
        if name in whitelist:
            return True, 'whitelisted_name'
        if accprofile and compliant_profiles and accprofile in compliant_profiles:
            return True, 'compliant_profile'
        return False, 'non_compliant'

    def audit_single(self, config_path: Path) -> dict | None:
        """
        稽核單一防火牆 config 檔案。

        Args:
            config_path: FortiGate config 檔案路徑

        Returns:
            結構化稽核結果 dict，或 None（解析失敗時）
        """
        parsed = parse_config_file(config_path)
        if parsed is None:
            return None

        hostname = parsed['hostname']
        compliant_profiles = self.get_compliant_profiles()
        accounts = {}
        total = 0
        compliant_count = 0
        non_compliant_count = 0

        for account_type in ('system_admin', 'api_user'):
            whitelist = self.get_whitelist(hostname, account_type)
            account_list = []

            for account in parsed[account_type]:
                name = account['name']
                accprofile = account['accprofile']

                is_compliant, reason = self._is_compliant(
                    name, accprofile, whitelist, compliant_profiles
                )

                account_list.append({
                    'name': name,
                    'accprofile': accprofile,
                    'compliant': is_compliant,
                    'reason': reason,
                })
                total += 1
                if is_compliant:
                    compliant_count += 1
                else:
                    non_compliant_count += 1
                    logger.warning(
                        f"⚠️ 不合規帳號: [{hostname}] {account_type}/{name} "
                        f"(accprofile={accprofile})"
                    )

            accounts[account_type] = account_list

        result = {
            'hostname': hostname,
            'config_file': config_path.name,
            'accounts': accounts,
            'summary': {
                'total': total,
                'compliant': compliant_count,
                'non_compliant': non_compliant_count,
                'is_compliant': non_compliant_count == 0,
            },
        }

        status = "✅" if result['summary']['is_compliant'] else "❌"
        logger.info(
            f"{status} {hostname}: "
            f"{total} 帳號 ({compliant_count} 合規 / {non_compliant_count} 不合規)"
        )

        return result

    def audit_directory(self, config_dir: Path) -> dict:
        """
        掃描目錄下所有 config 檔案，產生完整稽核報告。

        Args:
            config_dir: 包含 FortiGate config 檔案的目錄

        Returns:
            完整稽核報告 dict（適配 Grafana JSON Data Source）
        """
        config_dir = Path(config_dir)

        if not config_dir.is_dir():
            logger.error(f"❌ 目錄不存在: {config_dir}")
            return self._empty_report(str(config_dir))

        config_files = sorted(
            f for f in config_dir.iterdir()
            if f.is_file() and f.suffix in CONFIG_EXTENSIONS
        )

        if not config_files:
            logger.warning(f"⚠️ 目錄中沒有 config 檔案: {config_dir}")
            return self._empty_report(str(config_dir))

        logger.info(f"📂 掃描 {len(config_files)} 個 config 檔案: {config_dir}")

        firewalls = []
        for config_file in config_files:
            result = self.audit_single(config_file)
            if result:
                firewalls.append(result)

        # 彙總統計
        total_fw = len(firewalls)
        compliant_fw = sum(1 for fw in firewalls if fw['summary']['is_compliant'])
        total_accounts = sum(fw['summary']['total'] for fw in firewalls)
        non_compliant_accounts = sum(
            fw['summary']['non_compliant'] for fw in firewalls
        )

        report = {
            'scan_time': datetime.now(TW_TZ).isoformat(),
            'config_directory': str(config_dir),
            'firewalls': firewalls,
            'overall': {
                'total_firewalls': total_fw,
                'compliant_firewalls': compliant_fw,
                'non_compliant_firewalls': total_fw - compliant_fw,
                'total_accounts': total_accounts,
                'non_compliant_accounts': non_compliant_accounts,
            },
        }

        logger.info(
            f"📊 稽核完成: {total_fw} 台防火牆, "
            f"{total_accounts} 帳號, "
            f"{non_compliant_accounts} 不合規"
        )

        return report

    def _empty_report(self, config_dir: str) -> dict:
        """產生空的稽核報告"""
        return {
            'scan_time': datetime.now(TW_TZ).isoformat(),
            'config_directory': config_dir,
            'firewalls': [],
            'overall': {
                'total_firewalls': 0,
                'compliant_firewalls': 0,
                'non_compliant_firewalls': 0,
                'total_accounts': 0,
                'non_compliant_accounts': 0,
            },
        }
