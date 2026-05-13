import os
import sqlite3
import tempfile

from validators import normalize_ip


def save_upload_to_temp_db(file_storage, restore_backup_dir):
    filename = str(file_storage.filename or '').lower()
    if not filename.endswith(('.db', '.sqlite', '.sqlite3')):
        raise ValueError('请选择旧版本 net_assets.db 数据库文件')
    temp_dir = os.path.abspath(os.path.join(str(restore_backup_dir), 'tmp'))
    os.makedirs(temp_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='legacy_assets_', suffix='.db', dir=temp_dir)
    os.close(fd)
    file_storage.save(temp_path)
    if os.path.getsize(temp_path) <= 0:
        os.remove(temp_path)
        raise ValueError('上传的数据库文件为空')
    return temp_path


def read_legacy_key(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    filename = str(file_storage.filename or '').lower()
    if not filename.endswith('.key'):
        raise ValueError('旧版密钥文件必须是 net_assets.key')
    raw = file_storage.read().strip()
    if not raw:
        raise ValueError('旧版密钥文件为空')
    return raw


def decrypt_legacy_password(db_module, value, legacy_key=None):
    text = str(value or '')
    if not text.startswith(db_module.ENC_PREFIX):
        return text
    if legacy_key:
        try:
            token = text[len(db_module.ENC_PREFIX):].encode('ascii')
            return db_module.Fernet(legacy_key).decrypt(token).decode('utf-8')
        except Exception:
            return ''
    return db_module.decrypt_secret(text)


def read_legacy_switch_assets(db_module, db_path, legacy_key=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='switches'")
    if not cur.fetchone():
        conn.close()
        raise ValueError('旧数据库中未找到 switches 交换机资产表')

    cur.execute('PRAGMA table_info(switches)')
    columns = {row['name'] for row in cur.fetchall()}

    def pick(*names):
        for name in names:
            if name in columns:
                return name
        return None

    field_map = {
        'name': pick('name', 'switch_name', 'device_name', '设备名称'),
        'ip': pick('ip', 'switch_ip', 'host', 'hostname', 'IP地址', '交换机IP'),
        'port': pick('port', 'ssh_port', '端口'),
        'username': pick('username', 'user', 'login_user', '用户名'),
        'password': pick('password', 'pass', 'pwd', 'login_pass', '密码'),
        'vendor': pick('vendor', '厂商'),
        'role': pick('role', '角色'),
    }
    if not field_map['ip']:
        conn.close()
        raise ValueError('旧 switches 表缺少 IP 字段，无法识别交换机资产')

    cur.execute('SELECT * FROM switches')
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()

    assets = []
    errors = []
    seen_ips = set()
    for index, row in enumerate(rows, start=1):
        try:
            ip = normalize_ip(row.get(field_map['ip']) if field_map['ip'] else '', f'第 {index} 行交换机 IP')
            if ip in seen_ips:
                errors.append(f'第 {index} 行 {ip} 在旧库中重复，已跳过重复记录')
                continue
            seen_ips.add(ip)
            password_value = row.get(field_map['password']) if field_map['password'] else ''
            password = decrypt_legacy_password(db_module, password_value, legacy_key)
            encrypted_password_unreadable = bool(password_value) and not password
            try:
                port = int(row.get(field_map['port']) if field_map['port'] else 22 or 22)
            except (TypeError, ValueError):
                port = 22
            vendor = str(row.get(field_map['vendor']) if field_map['vendor'] else 'h3c' or 'h3c').strip().lower()
            if vendor not in ('h3c', 'huawei', 'ruijie'):
                vendor = 'h3c'
            role = str(row.get(field_map['role']) if field_map['role'] else 'access' or 'access').strip().lower()
            if role not in ('access', 'backup'):
                role = 'access'
            assets.append(
                {
                    'name': str(row.get(field_map['name']) if field_map['name'] else '' or ip).strip(),
                    'ip': ip,
                    'port': port,
                    'username': str(row.get(field_map['username']) if field_map['username'] else '' or '').strip(),
                    'password': password,
                    'vendor': vendor,
                    'role': role,
                    'password_unreadable': encrypted_password_unreadable,
                }
            )
        except ValueError as exc:
            errors.append(str(exc))
    return {'assets': assets, 'errors': errors, 'columns': sorted(columns)}


def import_legacy_switch_assets(db_module, restore_backup_dir, file_storage, key_storage=None, apply=False):
    legacy_key = read_legacy_key(key_storage)
    temp_path = save_upload_to_temp_db(file_storage, restore_backup_dir)
    try:
        parsed = read_legacy_switch_assets(db_module, temp_path, legacy_key)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    assets = parsed['assets']
    existing_by_ip = {sw['ip']: sw for sw in db_module.get_all_switches()}
    summary = {
        'total': len(assets),
        'matched_existing': sum(1 for item in assets if item['ip'] in existing_by_ip),
        'will_create': sum(1 for item in assets if item['ip'] not in existing_by_ip),
        'will_update': sum(1 for item in assets if item['ip'] in existing_by_ip),
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'password_unreadable': sum(1 for item in assets if item.get('password_unreadable')),
        'errors': parsed['errors'],
        'preview': [
            {k: item.get(k) for k in ('name', 'ip', 'port', 'username', 'vendor', 'role', 'password_unreadable')}
            for item in assets[:30]
        ],
        'columns': parsed['columns'],
    }
    if not apply:
        return summary

    for item in assets:
        if item.get('password_unreadable'):
            summary['skipped'] += 1
            summary['errors'].append(f"{item['ip']} 密码无法解密，已跳过；请提供旧版 net_assets.key 或手工重新录入")
            continue
        existing = existing_by_ip.get(item['ip'])
        if existing:
            db_module.update_switch(
                existing['id'],
                item['name'],
                item['ip'],
                item['port'],
                item['username'],
                item['password'],
                item['vendor'],
                item['role'],
            )
            summary['updated'] += 1
        else:
            db_module.add_switch(
                item['name'],
                item['ip'],
                item['port'],
                item['username'],
                item['password'],
                item['vendor'],
                item['role'],
            )
            summary['created'] += 1
    return summary
