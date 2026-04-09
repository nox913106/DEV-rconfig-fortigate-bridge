# ==========================================
# FortiGate Config Parser
# 基於 ciscoconfparse2 的帳號提取器
# ==========================================

import logging
import re
from pathlib import Path

from ciscoconfparse2 import CiscoConfParse

logger = logging.getLogger('FortigateAudit')

# 目標區段：regex pattern → 輸出 key
TARGET_SECTIONS = {
    r'^config system admin$': 'system_admin',
    r'^config system api-user$': 'api_user',
}


def _extract_edit_name(text: str) -> str | None:
    """從 'edit "name"' 或 'edit name' 行提取名稱"""
    if not text.startswith('edit '):
        return None
    name_part = text[5:].strip()
    if name_part.startswith('"') and name_part.endswith('"'):
        return name_part[1:-1]
    return name_part


def _extract_quoted_value(text: str, key: str) -> str | None:
    """
    從 'set <key> "value"' 或 'set <key> value' 行提取值。

    Args:
        text: 已 strip 的行文字
        key: 要提取的 key（如 'accprofile', 'hostname'）
    """
    pattern = rf'^set {re.escape(key)}\s+"?([^"]+)"?$'
    match = re.match(pattern, text)
    return match.group(1) if match else None


def extract_accounts(config_lines: list[str]) -> dict:
    """
    從 FortiGate config 提取管理員帳號資訊。

    使用 ciscoconfparse2 以 syntax='ios' 解析，依據縮排自動建立父子層級樹。
    走訪目標區段（config system admin / config system api-user）的 direct children，
    擷取 edit 行中的帳號名稱，以及該帳號的 accprofile。

    巢狀區塊（如 config gui-dashboard 內的 edit 17）不會被誤擷取，
    因為它們位於 grandchild 以下層級。

    Args:
        config_lines: FortiGate config 檔案的每一行（list of str）

    Returns:
        {
            "hostname": "FW-TW-HQ-01",
            "system_admin": [
                {"name": "fg", "accprofile": "super_admin"},
                {"name": "twspadmin", "accprofile": "reviewer"},
            ],
            "api_user": [
                {"name": "API_Read", "accprofile": "reviewer"},
            ]
        }
    """
    parse = CiscoConfParse(config_lines, syntax='ios')
    result = {
        'hostname': 'unknown',
        'system_admin': [],
        'api_user': [],
    }

    # ---- 提取 hostname ----
    for obj in parse.find_objects(r'^config system global$'):
        for child in obj.children:
            hostname = _extract_quoted_value(child.text.strip(), 'hostname')
            if hostname:
                result['hostname'] = hostname
                break

    # ---- 提取帳號 + accprofile ----
    for pattern, key in TARGET_SECTIONS.items():
        for obj in parse.find_objects(pattern):
            for child in obj.children:
                name = _extract_edit_name(child.text.strip())
                if name is None:
                    continue

                # 從 edit 的 grandchildren 中提取欄位
                accprofile = None
                remote_auth = False
                remote_group = None
                for grandchild in child.children:
                    text = grandchild.text.strip()
                    if text == 'set remote-auth enable':
                        remote_auth = True
                    val = _extract_quoted_value(text, 'accprofile')
                    if val:
                        accprofile = val
                    val = _extract_quoted_value(text, 'remote-group')
                    if val:
                        remote_group = val

                result[key].append({
                    'name': name,
                    'accprofile': accprofile,
                    'remote_auth': remote_auth,
                    'remote_group': remote_group,
                })

    logger.debug(
        f"📋 解析完成: hostname={result['hostname']}, "
        f"system_admin={len(result['system_admin'])}筆, "
        f"api_user={len(result['api_user'])}筆"
    )

    return result


def parse_config_file(config_path: Path) -> dict:
    """
    讀取並解析單一 FortiGate config 檔案。

    Args:
        config_path: config 檔案路徑

    Returns:
        extract_accounts() 的結果，或 None（讀取失敗時）
    """
    try:
        with open(config_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        logger.info(f"📂 讀取 config: {config_path.name} ({len(lines)} 行)")
        return extract_accounts(lines)

    except Exception as e:
        logger.error(f"❌ 無法讀取 config: {config_path} - {e}")
        return None
