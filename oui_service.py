import re
from functools import lru_cache

from runtime_paths import APP_DIR


DATA_DIR = APP_DIR / 'static' / 'data'

FALLBACK_OUI = {
    '000C29': 'VMware, Inc.',
    '001C14': 'VMware, Inc.',
    '005056': 'VMware, Inc.',
    '080027': 'PCS Systemtechnik GmbH / VirtualBox',
    '00155D': 'Microsoft Corporation',
    '001C42': 'Parallels, Inc.',
    '00E0FC': 'H3C Technologies Co., Limited',
}


def normalize_mac_prefix(value):
    text = re.sub(r'[^0-9A-Fa-f]', '', str(value or '')).upper()
    return text[:12]


def _load_txt(path):
    rows = {}
    if not path.exists():
        return rows
    for raw_line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(
            r'^([0-9A-Fa-f]{6}|[0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){2})\s+\((?:hex|base 16)\)\s+(.+)$',
            line,
        )
        if not match:
            continue
        prefix = normalize_mac_prefix(match.group(1))
        org = match.group(2).strip()
        if prefix and org:
            rows[prefix[:6]] = org
    return rows


@lru_cache(maxsize=1)
def load_oui_maps():
    """Load local IEEE oui.txt, with a small seed fallback."""
    txt_oui = _load_txt(DATA_DIR / 'oui.txt')
    return {
        6: {**FALLBACK_OUI, **txt_oui},
    }


def lookup_mac_vendor(mac):
    compact = normalize_mac_prefix(mac)
    if len(compact) < 6:
        return '无法识别厂商'
    maps = load_oui_maps()
    for length in (6,):
        if len(compact) >= length:
            vendor = maps.get(length, {}).get(compact[:length])
            if vendor:
                return vendor
    return '无法识别厂商'
