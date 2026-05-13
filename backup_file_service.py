import datetime
import os
import re

from runtime_paths import BACKUP_DIR


BACKUP_ROOT = str(BACKUP_DIR)


def backup_root_abs():
    return os.path.abspath(BACKUP_ROOT)


def resolve_backup_file(rel_path):
    text = str(rel_path or '').strip().replace('\\', os.sep).replace('/', os.sep)
    if not text or text.startswith(os.sep) or '..' in text.split(os.sep):
        raise ValueError('备份文件路径不合法')
    full_path = os.path.abspath(os.path.join(backup_root_abs(), text))
    if not full_path.startswith(backup_root_abs() + os.sep):
        raise ValueError('备份文件路径越界')
    if not os.path.isfile(full_path):
        raise ValueError('备份文件不存在')
    return full_path


def read_backup_text(rel_path):
    full_path = resolve_backup_file(rel_path)
    with open(full_path, 'r', encoding='utf-8', errors='replace') as fh:
        return fh.read().splitlines()


def list_backup_config_files(limit=500):
    root = backup_root_abs()
    files = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if not filename.lower().endswith(('.cfg', '.txt')):
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root).replace(os.sep, '/')
            stat = os.stat(full_path)
            date_part = rel_path.split('/', 1)[0] if '/' in rel_path else ''
            base_name = os.path.splitext(filename)[0]
            device_name = base_name
            device_ip = ''
            if '_' in base_name:
                device_name, device_ip = base_name.rsplit('_', 1)
            files.append(
                {
                    'path': rel_path,
                    'date': date_part,
                    'filename': filename,
                    'device_name': device_name,
                    'device_ip': device_ip,
                    'size': stat.st_size,
                    'mtime': datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                }
            )
    files.sort(key=lambda item: (item['date'], item['mtime'], item['filename']), reverse=True)
    return files[:limit]


def count_backup_days():
    root = backup_root_abs()
    days = set()
    for dirpath, _, filenames in os.walk(root):
        config_files = [filename for filename in filenames if filename.lower().endswith(('.cfg', '.txt'))]
        if not config_files:
            continue
        rel = os.path.relpath(dirpath, root)
        day = rel.split(os.sep, 1)[0] if rel != '.' else ''
        if re.match(r'^\d{4}-\d{2}-\d{2}$', day):
            days.add(day)
        else:
            for filename in config_files:
                full_path = os.path.join(dirpath, filename)
                days.add(datetime.datetime.fromtimestamp(os.path.getmtime(full_path)).strftime('%Y-%m-%d'))
    return len(days)
