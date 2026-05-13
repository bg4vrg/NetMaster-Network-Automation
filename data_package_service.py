import datetime
import io
import json
import os
import re
import shutil
import zipfile


def create_data_package(db_module, app_version):
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    memory_file = io.BytesIO()
    db_path = os.path.abspath(db_module.DB_NAME)
    key_path = os.path.abspath(db_module.KEY_FILE)
    switch_headers = ['id', 'name', 'ip', 'port', 'username', 'vendor', 'role']
    binding_headers = ['mac_address', 'ip_address', 'switch_ip', 'switch_name', 'port', 'vlan', 'mode', 'update_time']
    manifest = {
        'app': 'NetMaster',
        'version': app_version,
        'created_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'contains': ['net_assets.db', 'net_assets.key', 'switch_assets.csv', 'mac_bindings.csv'],
        'note': 'net_assets.db 与 net_assets.key 必须成对保存，否则加密后的交换机密码无法解密。',
    }

    def csv_text(headers, rows):
        import csv
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in headers})
        return '\ufeff' + buffer.getvalue()

    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as package:
        package.write(db_path, 'net_assets.db')
        if os.path.exists(key_path):
            package.write(key_path, 'net_assets.key')
        package.writestr('switch_assets.csv', csv_text(switch_headers, db_module.get_all_switches()))
        package.writestr('mac_bindings.csv', csv_text(binding_headers, db_module.get_mac_bindings(limit=100000)))
        package.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    memory_file.seek(0)
    return memory_file, f'netmaster_data_package_{timestamp}.zip'


def write_data_package_to_dir(db_module, app_version, data_package_dir, target_dir=None):
    settings = db_module.get_system_settings()
    target_dir = target_dir or settings.get('auto_data_export_dir') or str(data_package_dir)
    target_dir = os.path.abspath(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    memory_file, filename = create_data_package(db_module, app_version)
    full_path = os.path.join(target_dir, filename)
    with open(full_path, 'wb') as fh:
        fh.write(memory_file.getvalue())
    return full_path


def restore_data_package(db_module, restore_backup_dir_root, file_storage):
    raw = file_storage.read()
    if not raw:
        raise ValueError('上传文件为空')
    try:
        package = zipfile.ZipFile(io.BytesIO(raw), 'r')
    except zipfile.BadZipFile:
        raise ValueError('导入文件不是有效 zip 数据包')
    names = set(package.namelist())
    if 'net_assets.db' not in names:
        raise ValueError('数据包缺少 net_assets.db')

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    restore_backup_dir = os.path.abspath(os.path.join(str(restore_backup_dir_root), timestamp))
    os.makedirs(restore_backup_dir, exist_ok=True)
    db_path = os.path.abspath(db_module.DB_NAME)
    key_path = os.path.abspath(db_module.KEY_FILE)
    if os.path.exists(db_path):
        shutil.copy2(db_path, os.path.join(restore_backup_dir, 'net_assets.db'))
    if os.path.exists(key_path):
        shutil.copy2(key_path, os.path.join(restore_backup_dir, 'net_assets.key'))

    tmp_db = db_path + f'.import_{timestamp}.tmp'
    tmp_key = key_path + f'.import_{timestamp}.tmp'
    try:
        with open(tmp_db, 'wb') as fh:
            fh.write(package.read('net_assets.db'))
        if 'net_assets.key' in names:
            with open(tmp_key, 'wb') as fh:
                fh.write(package.read('net_assets.key'))
        shutil.move(tmp_db, db_path)
        if os.path.exists(tmp_key):
            shutil.move(tmp_key, key_path)
    finally:
        for path in [tmp_db, tmp_key]:
            if os.path.exists(path):
                os.remove(path)
        package.close()
    return restore_backup_dir


def backup_current_db_key(db_module, restore_backup_dir_root, reason='manual'):
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_reason = re.sub(r'[^A-Za-z0-9_\-]+', '_', str(reason or 'manual')).strip('_') or 'manual'
    backup_dir = os.path.abspath(os.path.join(str(restore_backup_dir_root), f'{timestamp}_{safe_reason}'))
    os.makedirs(backup_dir, exist_ok=True)
    copied = []
    for src_path, name in [(os.path.abspath(db_module.DB_NAME), 'net_assets.db'), (os.path.abspath(db_module.KEY_FILE), 'net_assets.key')]:
        if os.path.exists(src_path):
            shutil.copy2(src_path, os.path.join(backup_dir, name))
            copied.append(name)
    return {'backup_dir': backup_dir, 'files': copied}


def preview_data_package(file_storage):
    raw = file_storage.read()
    if not raw:
        raise ValueError('上传文件为空')
    try:
        package = zipfile.ZipFile(io.BytesIO(raw), 'r')
    except zipfile.BadZipFile:
        raise ValueError('导入文件不是有效 zip 数据包')
    names = set(package.namelist())
    manifest = {}
    if 'manifest.json' in names:
        try:
            manifest = json.loads(package.read('manifest.json').decode('utf-8', errors='replace'))
        except Exception:
            manifest = {}
    result = {
        'has_db': 'net_assets.db' in names,
        'has_key': 'net_assets.key' in names,
        'has_switch_csv': 'switch_assets.csv' in names,
        'has_binding_csv': 'mac_bindings.csv' in names,
        'manifest': manifest,
        'files': sorted(names),
    }
    if 'switch_assets.csv' in names:
        result['switch_csv_rows'] = max(0, len(package.read('switch_assets.csv').decode('utf-8-sig', errors='replace').splitlines()) - 1)
    if 'mac_bindings.csv' in names:
        result['binding_csv_rows'] = max(0, len(package.read('mac_bindings.csv').decode('utf-8-sig', errors='replace').splitlines()) - 1)
    package.close()
    return result
