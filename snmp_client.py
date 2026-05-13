import time
import asyncio
import re


IF_NAME_OID = '1.3.6.1.2.1.31.1.1.1.1'
IF_DESCR_OID = '1.3.6.1.2.1.2.2.1.2'
IF_ADMIN_STATUS_OID = '1.3.6.1.2.1.2.2.1.7'
IF_OPER_STATUS_OID = '1.3.6.1.2.1.2.2.1.8'
IF_SPEED_OID = '1.3.6.1.2.1.2.2.1.5'
IF_ALIAS_OID = '1.3.6.1.2.1.31.1.1.1.18'
IF_IN_ERRORS_OID = '1.3.6.1.2.1.2.2.1.14'
IF_OUT_ERRORS_OID = '1.3.6.1.2.1.2.2.1.20'

STATUS_LABELS = {
    '1': 'up',
    '2': 'down',
    '3': 'testing',
    '4': 'unknown',
    '5': 'dormant',
    '6': 'notPresent',
    '7': 'lowerLayerDown',
}

PHYSICAL_PREFIXES = ('ge', 'xge', 'mge', 'hge', 'fge', 'eth', '10ge', 'gigabitethernet', 'xgigabitethernet')


class SnmpUnavailable(RuntimeError):
    pass


def _load_pysnmp():
    try:
        from pysnmp.hlapi.asyncio import (  # type: ignore
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            get_cmd,
            walk_cmd,
        )
    except Exception as exc:
        raise SnmpUnavailable('当前 Python 环境未安装 pysnmp，无法执行 SNMP 查询') from exc
    return {
        'CommunityData': CommunityData,
        'ContextData': ContextData,
        'ObjectIdentity': ObjectIdentity,
        'ObjectType': ObjectType,
        'SnmpEngine': SnmpEngine,
        'UdpTransportTarget': UdpTransportTarget,
        'get_cmd': get_cmd,
        'walk_cmd': walk_cmd,
    }


async def _make_target(hlapi, host, timeout, retries):
    return await hlapi['UdpTransportTarget'].create((host, 161), timeout=timeout, retries=retries)


async def _walk_async(hlapi, host, community, oid, timeout, retries):
    rows = {}
    target = await _make_target(hlapi, host, timeout, retries)
    async for error_indication, error_status, error_index, var_binds in hlapi['walk_cmd'](
        hlapi['SnmpEngine'](),
        hlapi['CommunityData'](community, mpModel=1),
        target,
        hlapi['ContextData'](),
        hlapi['ObjectType'](hlapi['ObjectIdentity'](oid)),
        lexicographicMode=False,
    ):
        if error_indication:
            raise RuntimeError(str(error_indication))
        if error_status:
            raise RuntimeError('%s at %s' % (error_status.prettyPrint(), error_index))
        for name, value in var_binds:
            name_text = name.prettyPrint()
            index = name_text.rsplit('.', 1)[-1]
            rows[index] = value.prettyPrint()
    return rows


async def _get_many_async(hlapi, host, community, oids, timeout, retries):
    target = await _make_target(hlapi, host, timeout, retries)
    error_indication, error_status, error_index, var_binds = await hlapi['get_cmd'](
        hlapi['SnmpEngine'](),
        hlapi['CommunityData'](community, mpModel=1),
        target,
        hlapi['ContextData'](),
        *[hlapi['ObjectType'](hlapi['ObjectIdentity'](oid)) for oid in oids],
    )
    if error_indication:
        raise RuntimeError(str(error_indication))
    if error_status:
        raise RuntimeError('%s at %s' % (error_status.prettyPrint(), error_index))
    return [value.prettyPrint() for _, value in var_binds]


def _normalize_port_name(value):
    text = str(value or '').strip().lower().replace(' ', '')
    replacements = [
        ('hundredgige', 'hge'),
        ('hundredgigabitethernet', 'hge'),
        ('fortygige', 'fge'),
        ('fortygigabitethernet', 'fge'),
        ('tengige', 'xge'),
        ('tengigabitethernet', 'xge'),
        ('xgigabitethernet', 'xge'),
        ('gigabitethernet', 'ge'),
        ('ethernet', 'eth'),
    ]
    for source, target in replacements:
        text = text.replace(source, target)
    return text


def _short_port_name(value):
    text = str(value or '').strip().replace(' ', '')
    replacements = [
        ('HundredGigE', 'HGE'),
        ('HundredGigabitEthernet', 'HGE'),
        ('FortyGigE', 'FGE'),
        ('FortyGigabitEthernet', 'FGE'),
        ('Ten-GigabitEthernet', 'XGE'),
        ('TenGigabitEthernet', 'XGE'),
        ('XGigabitEthernet', 'XGE'),
        ('GigabitEthernet', 'GE'),
        ('M-GigabitEthernet', 'MGE'),
        ('Ethernet', 'Eth'),
    ]
    for source, target in replacements:
        text = text.replace(source, target)
    return text


def _is_physical_port(value):
    normalized = _normalize_port_name(value)
    if not normalized:
        return False
    if any(normalized.startswith(prefix) for prefix in PHYSICAL_PREFIXES):
        return bool(re.search(r'\d', normalized))
    return False


def _natural_port_key(value):
    text = _normalize_port_name(value)
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', text)]


def _speed_label(raw_speed):
    try:
        value = int(str(raw_speed))
    except Exception:
        return str(raw_speed or '-')
    if value >= 1000000000:
        return f'{value // 1000000000}Gbps'
    if value >= 1000000:
        return f'{value // 1000000}Mbps'
    if value >= 1000:
        return f'{value // 1000}Kbps'
    return f'{value}bps'


def _clean_interface_alias(alias, short_name, raw_name=''):
    text = str(alias or '').strip()
    if not text or text.lower().startswith('no such'):
        return ''
    compact = text.replace(' ', '')
    lower = compact.lower()
    if lower.endswith('interface'):
        base = compact[:-9]
        if _normalize_port_name(base) in {
            _normalize_port_name(short_name),
            _normalize_port_name(raw_name),
        }:
            return ''
        if any(base.lower().startswith(prefix) for prefix in (
            'gigabitethernet',
            'tengigabitethernet',
            'ten-gigabitethernet',
            'xgigabitethernet',
            'hundredgigabitethernet',
            'fortygigabitethernet',
        )):
            return ''
    if _normalize_port_name(text) in {
        _normalize_port_name(short_name),
        _normalize_port_name(raw_name),
    }:
        return ''
    return text


def get_port_status(host, interface, community, timeout=1.5, retries=1):
    return asyncio.run(get_port_status_async(host, interface, community, timeout=timeout, retries=retries))


def get_interface_list(host, community, timeout=1.5, retries=1):
    return asyncio.run(get_interface_list_async(host, community, timeout=timeout, retries=retries))


async def get_interface_list_async(host, community, timeout=1.5, retries=1):
    hlapi = _load_pysnmp()
    started = time.time()
    names = await _walk_async(hlapi, host, community, IF_NAME_OID, timeout, retries)
    if not names:
        names = await _walk_async(hlapi, host, community, IF_DESCR_OID, timeout, retries)
    admin_rows = await _walk_async(hlapi, host, community, IF_ADMIN_STATUS_OID, timeout, retries)
    oper_rows = await _walk_async(hlapi, host, community, IF_OPER_STATUS_OID, timeout, retries)
    alias_rows = await _walk_async(hlapi, host, community, IF_ALIAS_OID, timeout, retries)

    interfaces = []
    for index, raw_name in names.items():
        short_name = _short_port_name(raw_name)
        if not _is_physical_port(short_name):
            continue
        admin_status = STATUS_LABELS.get(str(admin_rows.get(index, '')), str(admin_rows.get(index, '') or '-'))
        oper_status = STATUS_LABELS.get(str(oper_rows.get(index, '')), str(oper_rows.get(index, '') or '-'))
        alias = _clean_interface_alias(alias_rows.get(index, ''), short_name, raw_name)
        text = f'[SNMP {oper_status}] {short_name}'
        if alias:
            text += f' - {alias}'
        interfaces.append({
            'value': short_name,
            'text': text,
            'name': short_name,
            'raw_name': raw_name,
            'if_index': index,
            'admin_status': admin_status,
            'oper_status': oper_status,
            'alias': alias,
            'source': 'snmp',
        })

    interfaces.sort(key=lambda item: _natural_port_key(item.get('name') or item.get('value')))
    return {
        'switch_ip': host,
        'source': 'snmp',
        'elapsed_ms': int((time.time() - started) * 1000),
        'interfaces': interfaces,
    }


async def get_port_status_async(host, interface, community, timeout=1.5, retries=1):
    hlapi = _load_pysnmp()
    interface_key = _normalize_port_name(interface)
    started = time.time()

    names = await _walk_async(hlapi, host, community, IF_NAME_OID, timeout, retries)
    if not names:
        names = await _walk_async(hlapi, host, community, IF_DESCR_OID, timeout, retries)

    match_index = None
    match_name = ''
    for index, name in names.items():
        if _normalize_port_name(name) == interface_key:
            match_index = index
            match_name = name
            break
    if not match_index:
        for index, name in names.items():
            normalized = _normalize_port_name(name)
            if normalized.endswith(interface_key) or interface_key.endswith(normalized):
                match_index = index
                match_name = name
                break
    if not match_index:
        raise RuntimeError(f'SNMP 未找到端口 {interface}')

    admin, oper, speed, alias, in_errors, out_errors = await _get_many_async(
        hlapi,
        host,
        community,
        [
            f'{IF_ADMIN_STATUS_OID}.{match_index}',
            f'{IF_OPER_STATUS_OID}.{match_index}',
            f'{IF_SPEED_OID}.{match_index}',
            f'{IF_ALIAS_OID}.{match_index}',
            f'{IF_IN_ERRORS_OID}.{match_index}',
            f'{IF_OUT_ERRORS_OID}.{match_index}',
        ],
        timeout,
        retries,
    )

    return {
        'switch_ip': host,
        'interface': interface,
        'if_index': match_index,
        'if_name': match_name or interface,
        'admin_status': STATUS_LABELS.get(str(admin), str(admin)),
        'oper_status': STATUS_LABELS.get(str(oper), str(oper)),
        'speed': _speed_label(speed),
        'alias': '' if str(alias).lower().startswith('no such') else str(alias),
        'in_errors': in_errors,
        'out_errors': out_errors,
        'elapsed_ms': int((time.time() - started) * 1000),
    }
