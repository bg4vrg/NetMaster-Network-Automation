import ipaddress
import re


def require_fields(data, fields):
    missing = []
    for field in fields:
        value = data.get(field)
        if value is None or str(value).strip() == '':
            missing.append(field)
    if missing:
        raise ValueError(f"缺少必填参数：{', '.join(missing)}")


def normalize_ip(value, field_name='IP'):
    text = str(value).strip()
    try:
        ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError(f'{field_name} 格式不正确') from exc
    return text


def normalize_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('端口必须是数字') from exc
    if not 1 <= port <= 65535:
        raise ValueError('端口范围必须在 1-65535 之间')
    return port


def normalize_vlan(value, field_name='VLAN', allow_empty=False):
    text = str(value or '').strip()
    if not text:
        if allow_empty:
            return ''
        raise ValueError(f'{field_name} 不能为空')
    if not text.isdigit():
        raise ValueError(f'{field_name} 必须是数字')
    vlan = int(text)
    if not 1 <= vlan <= 4094:
        raise ValueError(f'{field_name} 范围必须在 1-4094 之间')
    return str(vlan)


def normalize_vendor(value):
    vendor = str(value or 'h3c').strip().lower()
    if vendor not in {'h3c', 'huawei', 'ruijie'}:
        raise ValueError('厂商仅支持 h3c、huawei 或 ruijie')
    return vendor


def normalize_switch_role(value):
    role = str(value or 'access').strip().lower()
    if role not in {'access', 'backup'}:
        raise ValueError('设备角色仅支持 access 或 backup')
    return role


def normalize_bool_flag(value, default=True):
    if value is None:
        return 1 if default else 0
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in {'1', 'true', 'yes', 'on', '启用', '是'}:
        return 1
    if text in {'0', 'false', 'no', 'off', '禁用', '否'}:
        return 0
    raise ValueError('布尔字段只能是启用/禁用或 true/false')


def validate_password_policy(password):
    text = str(password or '')
    if len(text) < 8:
        raise ValueError('密码至少 8 位')
    if not re.search(r'[A-Za-z]', text) or not re.search(r'\d', text):
        raise ValueError('密码必须同时包含字母和数字')
    if text.lower() in {'admin888', 'password123', '12345678', 'qwer1234'}:
        raise ValueError('密码过于简单，请更换更安全的密码')
    return text


def normalize_mac(value, field_name='MAC'):
    text = str(value).strip()
    clean = text.replace(':', '').replace('-', '').replace('.', '')
    if len(clean) != 12 or any(ch not in '0123456789abcdefABCDEF' for ch in clean):
        raise ValueError(f'{field_name} 格式不正确')
    return text


def normalize_mode(value, field_name='模式'):
    mode = str(value or 'access').strip().lower()
    if mode not in {'access', 'trunk'}:
        raise ValueError(f'{field_name} 仅支持 access 或 trunk')
    return mode


def normalize_acl_number(value, field_name='ACL 组号'):
    number = int(str(value or '4000').strip())
    if number < 2000 or number > 4999:
        raise ValueError(f'{field_name} 必须在 2000-4999 范围内')
    return str(number)
