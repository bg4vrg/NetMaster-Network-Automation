import os
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('NETMASTER_DATA_DIR') or APP_DIR).resolve()


def data_path(*parts):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR.joinpath(*parts)


def runtime_dir(name):
    path = data_path(name)
    path.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = data_path('net_assets.db')
KEY_PATH = data_path('net_assets.key')
BACKUP_DIR = runtime_dir('backups')
DATA_PACKAGE_DIR = runtime_dir('data_packages')
RESTORE_BACKUP_DIR = runtime_dir('data_restore_backups')
