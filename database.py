import datetime
import sqlite3
import base64
import hashlib
import os
import json
import re

from werkzeug.security import check_password_hash, generate_password_hash
from cryptography.fernet import Fernet
from runtime_paths import APP_DIR, DATA_PACKAGE_DIR, DB_PATH, KEY_PATH


BASE_DIR = APP_DIR
DB_NAME = DB_PATH
KEY_FILE = KEY_PATH
ENC_PREFIX = 'enc:v1:'


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def get_cipher():
    if not KEY_FILE.exists():
        raw_key = base64.urlsafe_b64encode(os.urandom(32))
        KEY_FILE.write_bytes(raw_key)
    raw_key = KEY_FILE.read_bytes().strip()
    if len(raw_key) != 44:
        raw_key = base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest())
    return Fernet(raw_key)


def encrypt_secret(value):
    text = str(value or '')
    if not text or text.startswith(ENC_PREFIX):
        return text
    try:
        return ENC_PREFIX + get_cipher().encrypt(text.encode('utf-8')).decode('ascii')
    except Exception:
        return text


def decrypt_secret(value):
    text = str(value or '')
    if not text.startswith(ENC_PREFIX):
        return text
    try:
        token = text[len(ENC_PREFIX):].encode('ascii')
        return get_cipher().decrypt(token).decode('utf-8')
    except Exception:
        return ''


def decrypt_switch_row(row):
    data = dict(row)
    data['password'] = decrypt_secret(data.get('password'))
    return data


def init_db():
    """初始化数据库结构，并在首次运行时创建默认管理员。"""
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator',
            status TEXT NOT NULL DEFAULT 'active',
            display_name TEXT,
            create_time DATETIME DEFAULT (datetime('now', 'localtime')),
            last_login_at DATETIME,
            password_changed_at DATETIME,
            failed_login_count INTEGER NOT NULL DEFAULT 0,
            locked_until DATETIME
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS switches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip TEXT NOT NULL,
            port INTEGER DEFAULT 22,
            username TEXT,
            password TEXT,
            model TEXT,
            note TEXT,
            vendor TEXT DEFAULT 'h3c',
            role TEXT DEFAULT 'access',
            terminal_sync_enabled INTEGER DEFAULT 1
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            username TEXT NOT NULL,
            client_ip TEXT NOT NULL,
            device_ip TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            status TEXT NOT NULL
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS mac_bindings (
            mac_address TEXT PRIMARY KEY,
            ip_address TEXT NOT NULL,
            switch_ip TEXT NOT NULL,
            port TEXT NOT NULL,
            vlan TEXT,
            mode TEXT NOT NULL DEFAULT 'access',
            update_time DATETIME DEFAULT (datetime('now', 'localtime'))
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS port_snapshots (
            switch_ip TEXT NOT NULL,
            port TEXT NOT NULL,
            link_status TEXT,
            mode TEXT,
            description TEXT,
            raw_text TEXT,
            snapshot_time DATETIME DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (switch_ip, port)
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            update_time DATETIME DEFAULT (datetime('now', 'localtime'))
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS runtime_tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            status TEXT NOT NULL,
            message TEXT,
            progress INTEGER DEFAULT 0,
            actor TEXT,
            target TEXT,
            metadata TEXT,
            result TEXT,
            error TEXT,
            traceback TEXT,
            created_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS switch_alarm_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            switch_ip TEXT NOT NULL,
            switch_name TEXT,
            vendor TEXT,
            status TEXT NOT NULL,
            total_lines INTEGER DEFAULT 0,
            critical_count INTEGER DEFAULT 0,
            warning_count INTEGER DEFAULT 0,
            risk_level TEXT DEFAULT 'normal',
            risk_score INTEGER DEFAULT 0,
            category_counts TEXT,
            top_ports TEXT,
            suggestions TEXT,
            matched_lines TEXT,
            error TEXT
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS switch_alarm_states (
            switch_ip TEXT PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'open',
            note TEXT,
            ignore_until TEXT,
            updated_by TEXT,
            update_time DATETIME DEFAULT (datetime('now', 'localtime'))
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS compliance_analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            username TEXT,
            ipam_filename TEXT,
            agent_filename TEXT,
            registry_filename TEXT,
            summary TEXT,
            risks TEXT
        )
        '''
    )

    cur.execute(
        '''
        INSERT OR IGNORE INTO system_settings (key, value)
        VALUES ('auto_save_after_backup', '1')
        '''
    )
    default_settings = {
        'mac_sync_timeout': '90',
        'mac_sync_max_workers': '4',
        'protected_keywords': 'Uplink,Trunk,Core,Connect,To,hexin,huiju,link',
        'auto_backup_hour': '2',
        'auto_backup_minute': '37',
        'auto_sync_hour': '3',
        'auto_sync_minute': '20',
        'auto_data_export_enabled': '1',
        'auto_data_export_hour': '4',
        'auto_data_export_minute': '10',
        'auto_data_export_dir': str(DATA_PACKAGE_DIR),
        'auto_alarm_collect_enabled': '1',
        'auto_alarm_collect_hour': '4',
        'auto_alarm_collect_minute': '40',
        'snmp_read_community': 'suyuga0527',
        'snmp_timeout': '2.5',
        'snmp_retries': '2',
    }
    for key, value in default_settings.items():
        cur.execute(
            "INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    default_user = 'admin'
    default_pass = 'admin888'
    cur.execute("SELECT 1 FROM users WHERE username = ?", (default_user,))
    if not cur.fetchone():
        print(f"正在初始化默认管理员账号: {default_user}")
        cur.execute(
            "INSERT INTO users (username, password_hash, role, status, display_name) VALUES (?, ?, ?, ?, ?)",
            (default_user, generate_password_hash(default_pass), 'admin', 'active', '系统管理员'),
        )

    conn.commit()
    conn.close()


def upgrade_db():
    """为旧库补齐字段和索引。"""
    conn = get_db()
    cur = conn.cursor()

    user_columns = [
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'operator'",
        "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE users ADD COLUMN display_name TEXT",
        "ALTER TABLE users ADD COLUMN create_time DATETIME",
        "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
        "ALTER TABLE users ADD COLUMN password_changed_at DATETIME",
        "ALTER TABLE users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN locked_until DATETIME",
    ]
    for column_sql in user_columns:
        try:
            cur.execute(column_sql)
        except sqlite3.OperationalError:
            pass
    cur.execute(
        '''
        UPDATE users
        SET role = 'admin',
            status = 'active',
            display_name = COALESCE(display_name, '系统管理员')
        WHERE username = 'admin'
        '''
    )
    cur.execute(
        "UPDATE users SET create_time = COALESCE(create_time, datetime('now', 'localtime'))"
    )

    try:
        cur.execute("ALTER TABLE switches ADD COLUMN vendor TEXT DEFAULT 'h3c'")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE switches ADD COLUMN role TEXT DEFAULT 'access'")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE switches ADD COLUMN terminal_sync_enabled INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_switches_ip_unique ON switches(ip)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_mac_bindings_ip ON mac_bindings(ip_address)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_mac_bindings_switch_port ON mac_bindings(switch_ip, port)"
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS port_snapshots (
            switch_ip TEXT NOT NULL,
            port TEXT NOT NULL,
            link_status TEXT,
            mode TEXT,
            description TEXT,
            raw_text TEXT,
            snapshot_time DATETIME DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (switch_ip, port)
        )
        '''
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_port_snapshots_switch ON port_snapshots(switch_ip)"
    )

    try:
        cur.execute("ALTER TABLE mac_bindings ADD COLUMN mode TEXT DEFAULT 'access'")
    except sqlite3.OperationalError:
        pass

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            update_time DATETIME DEFAULT (datetime('now', 'localtime'))
        )
        '''
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS runtime_tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            status TEXT NOT NULL,
            message TEXT,
            progress INTEGER DEFAULT 0,
            actor TEXT,
            target TEXT,
            metadata TEXT,
            result TEXT,
            error TEXT,
            traceback TEXT,
            created_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT
        )
        '''
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_tasks_created ON runtime_tasks(created_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_tasks_category ON runtime_tasks(category)"
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS switch_alarm_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            switch_ip TEXT NOT NULL,
            switch_name TEXT,
            vendor TEXT,
            status TEXT NOT NULL,
            total_lines INTEGER DEFAULT 0,
            critical_count INTEGER DEFAULT 0,
            warning_count INTEGER DEFAULT 0,
            risk_level TEXT DEFAULT 'normal',
            risk_score INTEGER DEFAULT 0,
            category_counts TEXT,
            top_ports TEXT,
            suggestions TEXT,
            matched_lines TEXT,
            error TEXT
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS switch_alarm_states (
            switch_ip TEXT PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'open',
            note TEXT,
            ignore_until TEXT,
            updated_by TEXT,
            update_time DATETIME DEFAULT (datetime('now', 'localtime'))
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS compliance_analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            username TEXT,
            ipam_filename TEXT,
            agent_filename TEXT,
            registry_filename TEXT,
            summary TEXT,
            risks TEXT
        )
        '''
    )
    for column_sql in [
        "ALTER TABLE switch_alarm_reports ADD COLUMN risk_level TEXT DEFAULT 'normal'",
        "ALTER TABLE switch_alarm_reports ADD COLUMN risk_score INTEGER DEFAULT 0",
        "ALTER TABLE switch_alarm_reports ADD COLUMN category_counts TEXT",
        "ALTER TABLE switch_alarm_reports ADD COLUMN top_ports TEXT",
    ]:
        try:
            cur.execute(column_sql)
        except sqlite3.OperationalError:
            pass
    cur.execute(
        '''
        INSERT OR IGNORE INTO system_settings (key, value)
        VALUES ('auto_save_after_backup', '1')
        '''
    )
    default_settings = {
        'mac_sync_timeout': '90',
        'mac_sync_max_workers': '4',
        'protected_keywords': 'Uplink,Trunk,Core,Connect,To,hexin,huiju,link',
        'auto_backup_hour': '2',
        'auto_backup_minute': '37',
        'auto_sync_hour': '3',
        'auto_sync_minute': '20',
        'auto_data_export_enabled': '1',
        'auto_data_export_hour': '4',
        'auto_data_export_minute': '10',
        'auto_data_export_dir': str(DATA_PACKAGE_DIR),
        'auto_alarm_collect_enabled': '1',
        'auto_alarm_collect_hour': '4',
        'auto_alarm_collect_minute': '40',
        'snmp_read_community': 'suyuga0527',
        'snmp_timeout': '2.5',
        'snmp_retries': '2',
    }
    for key, value in default_settings.items():
        cur.execute(
            "INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    cur.execute("UPDATE system_settings SET value = '2.5' WHERE key = 'snmp_timeout' AND value = '1.5'")
    cur.execute("UPDATE system_settings SET value = '2' WHERE key = 'snmp_retries' AND value = '1'")

    cur.execute("SELECT id, password FROM switches")
    for row in cur.fetchall():
        password = row['password'] or ''
        encrypted = encrypt_secret(password)
        if encrypted != password:
            cur.execute("UPDATE switches SET password = ? WHERE id = ?", (encrypted, row['id']))

    conn.commit()
    conn.close()


def log_operation(username, client_ip, device_ip, action, details, status):
    try:
        conn = get_db()
        cur = conn.cursor()
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute(
            '''
            INSERT INTO audit_logs (timestamp, username, client_ip, device_ip, action, details, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (timestamp, username, client_ip, device_ip, action, details, status),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"写入审计日志失败: {exc}")


def _safe_json_dump(value):
    return json.dumps(value if value is not None else None, ensure_ascii=False)


def _safe_json_load(text, default):
    if text in (None, ''):
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _runtime_task_from_row(row):
    if not row:
        return None
    item = dict(row)
    item['progress'] = int(item.get('progress') or 0)
    item['metadata'] = _safe_json_load(item.get('metadata'), {})
    item['result'] = _safe_json_load(item.get('result'), None)
    return item


def save_runtime_task(task):
    public_task = dict(task or {})
    public_task.pop('future', None)
    if not public_task.get('id'):
        return
    conn = get_db()
    cur = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute(
        '''
        INSERT INTO runtime_tasks (
            id, name, category, status, message, progress, actor, target,
            metadata, result, error, traceback, created_at, started_at,
            finished_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            category = excluded.category,
            status = excluded.status,
            message = excluded.message,
            progress = excluded.progress,
            actor = excluded.actor,
            target = excluded.target,
            metadata = excluded.metadata,
            result = excluded.result,
            error = excluded.error,
            traceback = excluded.traceback,
            started_at = excluded.started_at,
            finished_at = excluded.finished_at,
            updated_at = excluded.updated_at
        ''',
        (
            public_task.get('id'),
            public_task.get('name') or '',
            public_task.get('category') or '',
            public_task.get('status') or 'queued',
            public_task.get('message') or '',
            int(public_task.get('progress') or 0),
            public_task.get('actor') or '',
            public_task.get('target') or '',
            _safe_json_dump(public_task.get('metadata') or {}),
            _safe_json_dump(public_task.get('result')),
            public_task.get('error') or '',
            public_task.get('traceback') or '',
            public_task.get('created_at') or now,
            public_task.get('started_at') or '',
            public_task.get('finished_at') or '',
            now,
        ),
    )
    conn.commit()
    conn.close()


def get_runtime_task(task_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM runtime_tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()
    return _runtime_task_from_row(row)


def list_runtime_tasks(limit=50, category=''):
    limit = max(1, min(int(limit or 50), 300))
    conn = get_db()
    cur = conn.cursor()
    if category:
        cur.execute(
            '''
            SELECT *
            FROM runtime_tasks
            WHERE category = ?
            ORDER BY created_at DESC, updated_at DESC
            LIMIT ?
            ''',
            (category, limit),
        )
    else:
        cur.execute(
            '''
            SELECT *
            FROM runtime_tasks
            ORDER BY created_at DESC, updated_at DESC
            LIMIT ?
            ''',
            (limit,),
        )
    rows = cur.fetchall()
    conn.close()
    return [_runtime_task_from_row(row) for row in rows]


def trim_runtime_tasks(max_rows=300):
    max_rows = max(50, int(max_rows or 300))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        DELETE FROM runtime_tasks
        WHERE id IN (
            SELECT id
            FROM runtime_tasks
            WHERE status IN ('success', 'failed', 'cancelled')
            ORDER BY created_at DESC, updated_at DESC
            LIMIT -1 OFFSET ?
        )
        ''',
        (max_rows,),
    )
    conn.commit()
    conn.close()


def add_switch_alarm_report(switch_ip, switch_name='', vendor='', status='成功', analysis=None, error=''):
    analysis = analysis or {}
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO switch_alarm_reports (
            timestamp, switch_ip, switch_name, vendor, status,
            total_lines, critical_count, warning_count,
            risk_level, risk_score, category_counts, top_ports,
            suggestions, matched_lines, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            switch_ip,
            switch_name or '',
            vendor or '',
            status,
            int(analysis.get('total_lines') or 0),
            int(analysis.get('critical') or 0),
            int(analysis.get('warning') or 0),
            analysis.get('risk_level') or 'normal',
            int(analysis.get('risk_score') or 0),
            json.dumps(analysis.get('category_counts') or {}, ensure_ascii=False),
            json.dumps(analysis.get('top_ports') or [], ensure_ascii=False),
            json.dumps(analysis.get('suggestions') or [], ensure_ascii=False),
            json.dumps((analysis.get('matched') or [])[-50:], ensure_ascii=False),
            str(error or ''),
        ),
    )
    conn.commit()
    conn.close()


def get_switch_alarm_reports(limit=200):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT *
        FROM switch_alarm_reports
        ORDER BY id DESC
        LIMIT ?
        ''',
        (int(limit),),
    )
    rows = cur.fetchall()
    conn.close()
    reports = []
    for row in rows:
        item = dict(row)
        for key in ['suggestions', 'matched_lines', 'top_ports']:
            try:
                item[key] = json.loads(item.get(key) or '[]')
            except Exception:
                item[key] = []
        try:
            item['category_counts'] = json.loads(item.get('category_counts') or '{}')
        except Exception:
            item['category_counts'] = {}
        reports.append(item)
    return reports


def get_latest_switch_alarm_reports():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT sar.*
        FROM switch_alarm_reports sar
        INNER JOIN (
            SELECT switch_ip, MAX(id) AS max_id
            FROM switch_alarm_reports
            GROUP BY switch_ip
        ) latest ON latest.max_id = sar.id
        ORDER BY sar.id DESC
        '''
    )
    rows = cur.fetchall()
    conn.close()
    reports = []
    for row in rows:
        item = dict(row)
        for key in ['suggestions', 'matched_lines', 'top_ports']:
            try:
                item[key] = json.loads(item.get(key) or '[]')
            except Exception:
                item[key] = []
        try:
            item['category_counts'] = json.loads(item.get('category_counts') or '{}')
        except Exception:
            item['category_counts'] = {}
        reports.append(item)
    return reports


def get_alarm_states():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM switch_alarm_states")
    rows = cur.fetchall()
    conn.close()
    return {row['switch_ip']: dict(row) for row in rows}


def update_alarm_state(switch_ip, state='open', note='', ignore_until='', updated_by=''):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO switch_alarm_states (switch_ip, state, note, ignore_until, updated_by, update_time)
        VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(switch_ip) DO UPDATE SET
            state = excluded.state,
            note = excluded.note,
            ignore_until = excluded.ignore_until,
            updated_by = excluded.updated_by,
            update_time = datetime('now', 'localtime')
        ''',
        (switch_ip, state, note or '', ignore_until or '', updated_by or ''),
    )
    conn.commit()
    conn.close()


def get_alarm_trends(days=7):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT
            substr(timestamp, 1, 10) AS day,
            SUM(CASE WHEN status != '成功' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN status = '成功' AND risk_level = 'high' THEN 1 ELSE 0 END) AS high,
            SUM(CASE WHEN status = '成功' AND risk_level = 'medium' THEN 1 ELSE 0 END) AS medium,
            SUM(CASE WHEN status = '成功' AND risk_level = 'low' THEN 1 ELSE 0 END) AS low,
            SUM(CASE WHEN status = '成功' AND COALESCE(risk_level, 'normal') = 'normal' THEN 1 ELSE 0 END) AS normal
        FROM switch_alarm_reports
        WHERE date(timestamp) >= date('now', ?)
        GROUP BY substr(timestamp, 1, 10)
        ORDER BY day DESC
        ''',
        (f'-{int(days) - 1} day',),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_user_by_id(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    conn.close()
    return user


def normalize_user_role(role):
    text = str(role or 'operator').strip().lower()
    if text not in {'admin', 'operator'}:
        raise ValueError('用户角色仅支持 admin 或 operator')
    return text


def normalize_user_status(status):
    text = str(status or 'active').strip().lower()
    if text not in {'active', 'disabled'}:
        raise ValueError('用户状态仅支持 active 或 disabled')
    return text


def verify_user(username, password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return None

    now = datetime.datetime.now()
    locked_until = user['locked_until'] if 'locked_until' in user.keys() else None
    if locked_until:
        try:
            locked_dt = datetime.datetime.strptime(locked_until, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            locked_dt = None
        if locked_dt and locked_dt > now:
            conn.close()
            return None

    if (user['status'] or 'active') != 'active':
        conn.close()
        return None

    if check_password_hash(user['password_hash'], password):
        cur.execute(
            '''
            UPDATE users
            SET last_login_at = datetime('now', 'localtime'),
                failed_login_count = 0,
                locked_until = NULL
            WHERE id = ?
            ''',
            (user['id'],),
        )
        conn.commit()
        cur.execute("SELECT * FROM users WHERE id = ?", (user['id'],))
        user = cur.fetchone()
        conn.close()
        return user
    failed_count = int(user['failed_login_count'] if 'failed_login_count' in user.keys() and user['failed_login_count'] is not None else 0) + 1
    locked_value = None
    if failed_count >= 5:
        locked_value = (now + datetime.timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
        failed_count = 0
    cur.execute(
        "UPDATE users SET failed_login_count = ?, locked_until = ? WHERE id = ?",
        (failed_count, locked_value, user['id']),
    )
    conn.commit()
    conn.close()
    return None


def change_password(username, new_password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password_hash = ?, password_changed_at = datetime('now', 'localtime') WHERE username = ?",
        (generate_password_hash(new_password), username),
    )
    conn.commit()
    conn.close()


def list_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT id, username, role, status, display_name, create_time, last_login_at,
               password_changed_at, failed_login_count, locked_until
        FROM users
        ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, username
        '''
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def count_active_admins(exclude_user_id=None):
    conn = get_db()
    cur = conn.cursor()
    if exclude_user_id is None:
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'")
    else:
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active' AND id != ?",
            (int(exclude_user_id),),
        )
    count = cur.fetchone()[0]
    conn.close()
    return int(count or 0)


def add_user(username, password, role='operator', display_name=''):
    username = str(username or '').strip()
    if not username:
        raise ValueError('用户名不能为空')
    role = normalize_user_role(role)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO users (username, password_hash, role, status, display_name, password_changed_at)
        VALUES (?, ?, ?, 'active', ?, datetime('now', 'localtime'))
        ''',
        (username, generate_password_hash(str(password or '')), role, str(display_name or '').strip()),
    )
    conn.commit()
    conn.close()


def update_user(user_id, role=None, status=None, display_name=None):
    fields = []
    values = []
    if role is not None:
        fields.append('role = ?')
        values.append(normalize_user_role(role))
    if status is not None:
        fields.append('status = ?')
        values.append(normalize_user_status(status))
    if display_name is not None:
        fields.append('display_name = ?')
        values.append(str(display_name or '').strip())
    if not fields:
        return
    values.append(int(user_id))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def reset_user_password(user_id, new_password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password_hash = ?, password_changed_at = datetime('now', 'localtime') WHERE id = ?",
        (generate_password_hash(str(new_password or '')), int(user_id)),
    )
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM system_settings WHERE key = ? LIMIT 1", (key,))
    row = cur.fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO system_settings (key, value, update_time)
        VALUES (?, ?, datetime('now', 'localtime'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            update_time = datetime('now', 'localtime')
        ''',
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_system_settings():
    timeout = int(get_setting('mac_sync_timeout', '90') or 90)
    max_workers = int(get_setting('mac_sync_max_workers', '4') or 4)
    keywords = get_setting('protected_keywords', 'Uplink,Trunk,Core,Connect,To,hexin,huiju,link') or ''
    return {
        'auto_save_after_backup': get_setting('auto_save_after_backup', '1') == '1',
        'mac_sync_timeout': max(10, min(timeout, 600)),
        'mac_sync_max_workers': max(1, min(max_workers, 16)),
        'protected_keywords': keywords,
        'auto_backup_hour': max(0, min(int(get_setting('auto_backup_hour', '2') or 2), 23)),
        'auto_backup_minute': max(0, min(int(get_setting('auto_backup_minute', '37') or 37), 59)),
        'auto_sync_hour': max(0, min(int(get_setting('auto_sync_hour', '3') or 3), 23)),
        'auto_sync_minute': max(0, min(int(get_setting('auto_sync_minute', '20') or 20), 59)),
        'auto_data_export_enabled': get_setting('auto_data_export_enabled', '1') == '1',
        'auto_data_export_hour': max(0, min(int(get_setting('auto_data_export_hour', '4') or 4), 23)),
        'auto_data_export_minute': max(0, min(int(get_setting('auto_data_export_minute', '10') or 10), 59)),
        'auto_data_export_dir': get_setting('auto_data_export_dir', str(DATA_PACKAGE_DIR)) or str(DATA_PACKAGE_DIR),
        'auto_alarm_collect_enabled': get_setting('auto_alarm_collect_enabled', '1') == '1',
        'auto_alarm_collect_hour': max(0, min(int(get_setting('auto_alarm_collect_hour', '4') or 4), 23)),
        'auto_alarm_collect_minute': max(0, min(int(get_setting('auto_alarm_collect_minute', '40') or 40), 59)),
        'snmp_read_community': get_setting('snmp_read_community', 'suyuga0527') or 'suyuga0527',
        'snmp_timeout': max(0.5, min(float(get_setting('snmp_timeout', '2.5') or 2.5), 10)),
        'snmp_retries': max(0, min(int(get_setting('snmp_retries', '2') or 2), 3)),
    }


def get_all_switches():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM switches ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [decrypt_switch_row(row) for row in rows]


def get_terminal_sync_switches():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT *
        FROM switches
        WHERE COALESCE(role, 'access') = 'access'
        ORDER BY id DESC
        '''
    )
    rows = cur.fetchall()
    conn.close()
    return [decrypt_switch_row(row) for row in rows]


def get_switch_by_ip(ip):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM switches WHERE ip = ? LIMIT 1", (ip,))
    row = cur.fetchone()
    conn.close()
    return decrypt_switch_row(row) if row else None


def get_switch_by_id(switch_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM switches WHERE id = ? LIMIT 1", (switch_id,))
    row = cur.fetchone()
    conn.close()
    return decrypt_switch_row(row) if row else None


def add_switch(name, ip, port, username, password, vendor='h3c', role='access', terminal_sync_enabled=1):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO switches (name, ip, port, username, password, vendor, role, terminal_sync_enabled)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (name, ip, port, username, encrypt_secret(password), vendor, role, int(terminal_sync_enabled)),
    )
    conn.commit()
    conn.close()


def update_switch(switch_id, name, ip, port, username, password=None, vendor='h3c', role='access'):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT ip, password FROM switches WHERE id = ? LIMIT 1", (switch_id,))
    existing = cur.fetchone()
    if not existing:
        conn.close()
        return False

    old_ip = existing['ip']
    stored_password = existing['password']
    next_password = encrypt_secret(password) if password is not None else stored_password
    cur.execute(
        '''
        UPDATE switches
        SET name = ?, ip = ?, port = ?, username = ?, password = ?, vendor = ?, role = ?
        WHERE id = ?
        ''',
        (name, ip, port, username, next_password, vendor, role, switch_id),
    )
    if old_ip != ip:
        cur.execute(
            "UPDATE mac_bindings SET switch_ip = ? WHERE switch_ip = ?",
            (ip, old_ip),
        )
    conn.commit()
    conn.close()
    return True


def update_switch_metadata(switch_id, role=None, terminal_sync_enabled=None):
    fields = []
    values = []
    if role is not None:
        fields.append("role = ?")
        values.append(role)
    if not fields:
        return
    values.append(switch_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE switches SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_switch(switch_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM switches WHERE id = ?", (switch_id,))
    conn.commit()
    conn.close()


def upsert_mac_binding(mac_address, ip_address, switch_ip, port, vlan=None, mode='access'):
    conn = get_db()
    cur = conn.cursor()
    normalized = (
        mac_address,
        ip_address,
        switch_ip,
        port,
        str(vlan or ''),
        mode,
    )
    cur.execute(
        '''
        SELECT mac_address, ip_address, switch_ip, port, vlan, mode
        FROM mac_bindings
        WHERE mac_address = ?
        LIMIT 1
        ''',
        (mac_address,),
    )
    existing = cur.fetchone()
    if existing:
        old = (
            existing['mac_address'],
            existing['ip_address'],
            existing['switch_ip'],
            existing['port'],
            str(existing['vlan'] or ''),
            existing['mode'],
        )
        if old == normalized:
            cur.execute(
                '''
                UPDATE mac_bindings
                SET update_time = datetime('now', 'localtime')
                WHERE mac_address = ?
                ''',
                (mac_address,),
            )
            conn.commit()
            conn.close()
            return 'unchanged'
        action = 'updated'
    else:
        action = 'created'

    cur.execute(
        '''
        INSERT INTO mac_bindings (mac_address, ip_address, switch_ip, port, vlan, mode, update_time)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(mac_address) DO UPDATE SET
            ip_address = excluded.ip_address,
            switch_ip = excluded.switch_ip,
            port = excluded.port,
            vlan = excluded.vlan,
            mode = excluded.mode,
            update_time = datetime('now', 'localtime')
        ''',
        (mac_address, ip_address, switch_ip, port, str(vlan or ''), mode),
    )
    conn.commit()
    conn.close()
    return action


def delete_mac_binding(mac_address):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM mac_bindings WHERE mac_address = ?", (mac_address,))
    conn.commit()
    conn.close()


def get_mac_binding(mac_address):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM mac_bindings WHERE mac_address = ? LIMIT 1",
        (mac_address,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_mac_binding_on_switch(mac_address, switch_ip):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT *
        FROM mac_bindings
        WHERE mac_address = ? AND switch_ip = ?
        LIMIT 1
        ''',
        (mac_address, switch_ip),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_binding_by_ip(ip_address):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT *
        FROM mac_bindings
        WHERE ip_address = ?
        ORDER BY update_time DESC
        LIMIT 1
        ''',
        (ip_address,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_binding_by_ip_on_switch(ip_address, switch_ip):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT *
        FROM mac_bindings
        WHERE ip_address = ? AND switch_ip = ?
        ORDER BY update_time DESC
        LIMIT 1
        ''',
        (ip_address, switch_ip),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_bindings_by_ip(ip_address, switch_ip=None):
    conn = get_db()
    cur = conn.cursor()
    if switch_ip:
        cur.execute(
            '''
            SELECT *
            FROM mac_bindings
            WHERE ip_address = ? AND switch_ip = ?
            ORDER BY update_time DESC
            ''',
            (ip_address, switch_ip),
        )
    else:
        cur.execute(
            '''
            SELECT *
            FROM mac_bindings
            WHERE ip_address = ?
            ORDER BY update_time DESC
            ''',
            (ip_address,),
        )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_mac_bindings(limit=500, switch_ip=None):
    conn = get_db()
    cur = conn.cursor()
    params = []
    where_sql = ''
    if switch_ip:
        where_sql = 'WHERE mb.switch_ip = ?'
        params.append(switch_ip)
    params.append(limit)
    cur.execute(
        f'''
        SELECT
            mb.mac_address,
            mb.ip_address,
            mb.switch_ip,
            COALESCE(sw.name, '') AS switch_name,
            mb.port,
            mb.vlan,
            mb.mode,
            mb.update_time
        FROM mac_bindings mb
        LEFT JOIN switches sw ON sw.ip = mb.switch_ip
        {where_sql}
        ORDER BY mb.update_time DESC
        LIMIT ?
        ''',
        params,
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_mac_bindings_page(limit=50, offset=0, switch_ip=None, keyword='', mode='', state=''):
    conn = get_db()
    cur = conn.cursor()
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    keyword = str(keyword or '').strip()
    mode = str(mode or '').strip().lower()
    state = str(state or '').strip()

    where = []
    params = []
    if switch_ip:
        where.append('mb.switch_ip = ?')
        params.append(switch_ip)
    if mode in ('access', 'trunk'):
        where.append('COALESCE(mb.mode, ?) = ?')
        params.extend(['access', mode])
    if keyword:
        like = f'%{keyword}%'
        where.append(
            '''(
                mb.mac_address LIKE ?
                OR mb.ip_address LIKE ?
                OR mb.switch_ip LIKE ?
                OR COALESCE(sw.name, '') LIKE ?
                OR mb.port LIKE ?
                OR COALESCE(mb.vlan, '') LIKE ?
                OR COALESCE(mb.mode, '') LIKE ?
                OR COALESCE(mb.update_time, '') LIKE ?
            )'''
        )
        params.extend([like] * 8)
    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    stale_expr = "((julianday('now', 'localtime') - julianday(COALESCE(update_time, ''))) > 3)"

    cte = f'''
        WITH base AS (
            SELECT
                mb.mac_address,
                mb.ip_address,
                mb.switch_ip,
                COALESCE(sw.name, '') AS switch_name,
                mb.port,
                mb.vlan,
                COALESCE(mb.mode, 'access') AS mode,
                mb.update_time
            FROM mac_bindings mb
            LEFT JOIN switches sw ON sw.ip = mb.switch_ip
            {where_sql}
        ),
        ip_conflicts AS (
            SELECT ip_address
            FROM base
            WHERE COALESCE(ip_address, '') <> ''
            GROUP BY ip_address
            HAVING COUNT(DISTINCT mac_address) > 1
        ),
        mac_conflicts AS (
            SELECT mac_address
            FROM base
            WHERE COALESCE(mac_address, '') <> ''
            GROUP BY mac_address
            HAVING COUNT(DISTINCT switch_ip || '|' || port || '|' || COALESCE(ip_address, '')) > 1
        ),
        marked AS (
            SELECT
                base.*,
                CASE WHEN ip_conflicts.ip_address IS NULL THEN 0 ELSE 1 END AS ip_conflict,
                CASE WHEN mac_conflicts.mac_address IS NULL THEN 0 ELSE 1 END AS mac_conflict,
                CASE WHEN {stale_expr} THEN 1 ELSE 0 END AS stale
            FROM base
            LEFT JOIN ip_conflicts ON ip_conflicts.ip_address = base.ip_address
            LEFT JOIN mac_conflicts ON mac_conflicts.mac_address = base.mac_address
        )
    '''
    state_sql = ''
    if state == 'ip_conflict':
        state_sql = 'WHERE ip_conflict = 1'
    elif state == 'mac_conflict':
        state_sql = 'WHERE mac_conflict = 1'
    elif state == 'stale':
        state_sql = 'WHERE stale = 1'

    cur.execute(
        cte + f'''
        SELECT COUNT(*) AS total,
               SUM(ip_conflict) AS ip_conflict_rows,
               COUNT(DISTINCT CASE WHEN ip_conflict = 1 THEN ip_address END) AS ip_conflict_count,
               SUM(mac_conflict) AS mac_conflict_rows,
               COUNT(DISTINCT CASE WHEN mac_conflict = 1 THEN mac_address END) AS mac_conflict_count,
               SUM(stale) AS stale_count
        FROM marked
        {state_sql}
        ''',
        params,
    )
    summary = dict(cur.fetchone() or {})
    cur.execute(
        cte + f'''
        SELECT *
        FROM marked
        {state_sql}
        ORDER BY update_time DESC, switch_ip, port, mac_address
        LIMIT ? OFFSET ?
        ''',
        params + [limit, offset],
    )
    rows = [dict(row) for row in cur.fetchall()]
    total = int(summary.get('total') or 0)
    conn.close()
    return {
        'rows': rows,
        'total': total,
        'limit': limit,
        'offset': offset,
        'next_offset': offset + len(rows),
        'has_more': offset + len(rows) < total,
        'summary': {
            'ip_conflict_count': int(summary.get('ip_conflict_count') or 0),
            'ip_conflict_rows': int(summary.get('ip_conflict_rows') or 0),
            'mac_conflict_count': int(summary.get('mac_conflict_count') or 0),
            'mac_conflict_rows': int(summary.get('mac_conflict_rows') or 0),
            'stale_count': int(summary.get('stale_count') or 0),
        },
    }


def get_port_profiles():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT
            mb.switch_ip,
            COALESCE(sw.name, '') AS switch_name,
            mb.port,
            COUNT(*) AS terminal_count,
            GROUP_CONCAT(DISTINCT mb.vlan) AS vlans,
            GROUP_CONCAT(DISTINCT mb.mode) AS modes,
            MAX(mb.update_time) AS last_update,
            MAX(ps.link_status) AS snapshot_status,
            MAX(ps.mode) AS snapshot_mode,
            MAX(ps.description) AS snapshot_description,
            MAX(ps.snapshot_time) AS snapshot_time
        FROM mac_bindings mb
        LEFT JOIN switches sw ON sw.ip = mb.switch_ip
        LEFT JOIN port_snapshots ps ON ps.switch_ip = mb.switch_ip AND ps.port = mb.port
        GROUP BY mb.switch_ip, mb.port
        ORDER BY terminal_count DESC, last_update DESC
        '''
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_port_profiles_page(limit=20, offset=0, query=''):
    conn = get_db()
    cur = conn.cursor()
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    query = str(query or '').strip()
    where_sql = ''
    params = []
    if query:
        like = f'%{query}%'
        where_sql = '''
        WHERE (
            mb.switch_ip LIKE ?
            OR COALESCE(sw.name, '') LIKE ?
            OR mb.port LIKE ?
            OR COALESCE(mb.vlan, '') LIKE ?
            OR COALESCE(mb.mode, '') LIKE ?
            OR COALESCE(ps.description, '') LIKE ?
        )
        '''
        params.extend([like, like, like, like, like, like])

    base_sql = f'''
        SELECT
            mb.switch_ip,
            COALESCE(sw.name, '') AS switch_name,
            mb.port,
            COUNT(*) AS terminal_count,
            GROUP_CONCAT(DISTINCT mb.vlan) AS vlans,
            GROUP_CONCAT(DISTINCT mb.mode) AS modes,
            MAX(mb.update_time) AS last_update,
            MAX(ps.link_status) AS snapshot_status,
            MAX(ps.mode) AS snapshot_mode,
            MAX(ps.description) AS snapshot_description,
            MAX(ps.snapshot_time) AS snapshot_time
        FROM mac_bindings mb
        LEFT JOIN switches sw ON sw.ip = mb.switch_ip
        LEFT JOIN port_snapshots ps ON ps.switch_ip = mb.switch_ip AND ps.port = mb.port
        {where_sql}
        GROUP BY mb.switch_ip, mb.port
    '''
    cur.execute(f'SELECT COUNT(*) AS total FROM ({base_sql}) t', params)
    total = int(cur.fetchone()['total'] or 0)
    cur.execute(
        f'''
        {base_sql}
        ORDER BY terminal_count DESC, last_update DESC
        LIMIT ? OFFSET ?
        ''',
        params + [limit, offset],
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {
        'rows': rows,
        'total': total,
        'limit': limit,
        'offset': offset,
        'has_more': offset + len(rows) < total,
    }


def confirm_port_profiles(items):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total = 0
    for item in items or []:
        switch_ip = str(item.get('switch_ip') or '').strip()
        port = str(item.get('port') or '').strip()
        if not switch_ip or not port:
            continue
        cur.execute(
            '''
            UPDATE mac_bindings
            SET update_time = ?
            WHERE switch_ip = ? AND port = ?
            ''',
            (now, switch_ip, port),
        )
        total += cur.rowcount
    conn.commit()
    conn.close()
    return {'confirmed': total, 'update_time': now}


def save_port_snapshots(switch_ip, ports):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    count = 0
    for port in ports or []:
        name = str(port.get('port') or port.get('name') or port.get('value') or '').strip()
        if not name:
            continue
        cur.execute(
            '''
            INSERT INTO port_snapshots (
                switch_ip, port, link_status, mode, description, raw_text, snapshot_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(switch_ip, port) DO UPDATE SET
                link_status = excluded.link_status,
                mode = excluded.mode,
                description = excluded.description,
                raw_text = excluded.raw_text,
                snapshot_time = excluded.snapshot_time
            ''',
            (
                switch_ip,
                name,
                str(port.get('link_status') or port.get('link') or '').strip(),
                str(port.get('mode') or port.get('type') or '').strip(),
                str(port.get('description') or port.get('desc') or '').strip(),
                str(port.get('raw_text') or port.get('text') or '').strip(),
                now,
            ),
        )
        count += 1
    conn.commit()
    conn.close()
    return {'saved': count, 'snapshot_time': now}


def get_port_snapshots(switch_ip=None, limit=1000):
    conn = get_db()
    cur = conn.cursor()
    params = []
    where_sql = ''
    if switch_ip:
        where_sql = 'WHERE ps.switch_ip = ?'
        params.append(switch_ip)
    params.append(max(1, min(int(limit or 1000), 5000)))
    cur.execute(
        f'''
        SELECT
            ps.switch_ip,
            COALESCE(sw.name, '') AS switch_name,
            ps.port,
            ps.link_status,
            ps.mode,
            ps.description,
            ps.raw_text,
            ps.snapshot_time
        FROM port_snapshots ps
        LEFT JOIN switches sw ON sw.ip = ps.switch_ip
        {where_sql}
        ORDER BY ps.snapshot_time DESC, ps.switch_ip, ps.port
        LIMIT ?
        ''',
        params,
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_audit_logs(limit=100, offset=0, filters=None):
    conn = get_db()
    cur = conn.cursor()
    filters = filters or {}
    where = []
    params = []
    for column, key in [('action', 'action'), ('username', 'username'), ('device_ip', 'device_ip'), ('status', 'status')]:
        value = str(filters.get(key) or '').strip()
        if value:
            where.append(f"{column} LIKE ?")
            params.append(f"%{value}%")
    start_time = str(filters.get('start_time') or '').strip()
    end_time = str(filters.get('end_time') or '').strip()
    if start_time:
        where.append("timestamp >= ?")
        params.append(start_time)
    if end_time:
        where.append("timestamp <= ?")
        params.append(end_time)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    cur.execute(f"SELECT * FROM audit_logs {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_audit_filter_options(limit=3000):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, device_ip, action FROM audit_logs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()

    def unique_values(key):
        values = []
        seen = set()
        for row in rows:
            value = str(row[key] or '').strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
        return values[:300]

    return {
        'usernames': unique_values('username'),
        'actions': unique_values('action'),
        'device_ips': unique_values('device_ip'),
    }


def get_task_logs(limit=300, offset=0):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT *
        FROM audit_logs
        WHERE action IN (
            '定时自动备份',
            '定时单台备份',
            '定时备份后保存配置',
            '同步终端绑定状态库',
            '同步终端绑定状态库-单台',
            '同步终端绑定信息',
            '同步终端绑定信息-单台',
            '终端更新（汇总）',
            '终端更新（单台设备）',
            '手动批量备份',
            'Excel批量聚合下发',
            'Excel批量下发',
            '终端迁移',
            '终端迁移试运行'
        )
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        ''',
        (limit, offset),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_dashboard_stats():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM switches")
    switch_count = cur.fetchone()[0]

    today = datetime.datetime.now().strftime('%Y-%m-%d')
    cur.execute("SELECT COUNT(*) FROM audit_logs WHERE timestamp LIKE ?", (today + '%',))
    today_ops = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM mac_bindings")
    mac_binding_count = cur.fetchone()[0]

    month_prefix = datetime.datetime.now().strftime('%Y-%m')
    binding_actions = ('终端迁移', '端口绑定', '解除绑定', '批量端口绑定')
    cur.execute(
        f'''
        SELECT timestamp, username, device_ip, action, details, status
        FROM audit_logs
        WHERE timestamp LIKE ?
          AND status = '成功'
          AND action IN ({','.join(['?'] * len(binding_actions))})
        ORDER BY id DESC
        ''',
        (month_prefix + '%', *binding_actions),
    )
    monthly_rows = [dict(row) for row in cur.fetchall()]

    cur.execute(
        f'''
        SELECT timestamp, username, device_ip, action, details, status
        FROM audit_logs
        WHERE status = '成功'
          AND action IN ({','.join(['?'] * len(binding_actions))})
        ORDER BY id DESC
        LIMIT 10
        ''',
        binding_actions,
    )
    recent_binding_changes = [dict(row) for row in cur.fetchall()]

    cur.execute("SELECT ip, name FROM switches")
    switch_name_map = {row['ip']: row['name'] for row in cur.fetchall()}

    cur.execute(
        '''
        SELECT status, timestamp, details
        FROM audit_logs
        WHERE action = '定时自动备份'
        ORDER BY id DESC
        LIMIT 1
        '''
    )
    last_backup = cur.fetchone()

    cur.execute(
        '''
        SELECT timestamp, device_ip, details
        FROM audit_logs
        WHERE action IN ('保存配置', '定时备份后保存配置')
          AND status = '成功'
        ORDER BY id DESC
        LIMIT 1
        '''
    )
    last_save_config = cur.fetchone()

    cur.execute(
        '''
        SELECT timestamp, details
        FROM audit_logs
        WHERE action = '定时自动备份'
          AND status = '成功'
          AND details LIKE '%保存成功:%'
          AND details LIKE '%保存失败:%'
        ORDER BY id DESC
        LIMIT 50
        '''
    )
    all_save_config_rows = [dict(row) for row in cur.fetchall()]

    task_actions = (
        '定时自动备份',
        '定时单台备份',
        '定时备份后保存配置',
        '同步终端绑定状态库',
        '同步终端绑定状态库-单台',
        '同步终端绑定信息',
        '同步终端绑定信息-单台',
        '终端更新（汇总）',
        '终端更新（单台设备）',
        '手动批量备份',
        'Excel批量聚合下发',
        'Excel批量下发',
        '批量端口绑定',
        '终端迁移',
        '终端迁移试运行',
        '定时采集交换机日志告警',
        '自动导出数据包',
    )
    since_7 = (datetime.datetime.now() - datetime.timedelta(days=6)).strftime('%Y-%m-%d')
    cur.execute(
        f'''
        SELECT substr(timestamp, 1, 10) AS day, status, COUNT(*) AS count
        FROM audit_logs
        WHERE substr(timestamp, 1, 10) >= ?
          AND action IN ({','.join(['?'] * len(task_actions))})
        GROUP BY day, status
        ORDER BY day
        ''',
        (since_7, *task_actions),
    )
    task_trend_rows = [dict(row) for row in cur.fetchall()]

    cur.execute(
        f'''
        SELECT timestamp, action, device_ip, details, status
        FROM audit_logs
        WHERE action IN ({','.join(['?'] * len(task_actions))})
          AND status != '成功'
        ORDER BY id DESC
        LIMIT 5
        ''',
        task_actions,
    )
    recent_failed_tasks = [dict(row) for row in cur.fetchall()]

    since_30 = (datetime.datetime.now() - datetime.timedelta(days=29)).strftime('%Y-%m-%d')
    cur.execute(
        f'''
        SELECT substr(timestamp, 1, 10) AS day, action, details
        FROM audit_logs
        WHERE substr(timestamp, 1, 10) >= ?
          AND status = '成功'
          AND action IN ({','.join(['?'] * len(binding_actions))})
        ORDER BY day
        ''',
        (since_30, *binding_actions),
    )
    binding_trend_rows = [dict(row) for row in cur.fetchall()]

    cur.execute(
        '''
        SELECT
            mb.switch_ip,
            COALESCE(sw.name, '') AS switch_name,
            mb.port,
            COUNT(*) AS terminal_count,
            COUNT(DISTINCT COALESCE(NULLIF(mb.vlan, ''), '-')) AS vlan_count,
            GROUP_CONCAT(DISTINCT mb.vlan) AS vlans,
            GROUP_CONCAT(DISTINCT mb.mode) AS modes,
            MAX(mb.update_time) AS last_update
        FROM mac_bindings mb
        LEFT JOIN switches sw ON sw.ip = mb.switch_ip
        GROUP BY mb.switch_ip, mb.port
        ORDER BY terminal_count DESC, vlan_count DESC, last_update DESC
        '''
    )
    port_profile_rows = [dict(row) for row in cur.fetchall()]

    conn.close()

    def binding_change_count(row):
        details = row.get('details') or ''
        if row.get('action') == '批量端口绑定':
            match = re.search(r'条数:(\d+)', details)
            return int(match.group(1)) if match else 1
        return 1

    def switch_label(ip):
        if not ip:
            return ''
        name = switch_name_map.get(ip) or ''
        return name or ip

    def parse_count(pattern, text):
        match = re.search(pattern, text or '')
        return int(match.group(1)) if match else 0

    last_all_save_config = None
    for row in all_save_config_rows:
        details = row.get('details') or ''
        total = parse_count(r'共\s*(\d+)\s*台', details)
        save_success = parse_count(r'保存成功[:：]\s*(\d+)', details)
        save_failed = parse_count(r'保存失败[:：]\s*(\d+)', details)
        expected_total = total or switch_count
        if expected_total > 0 and save_failed == 0 and save_success >= expected_total:
            last_all_save_config = {
                'timestamp': row.get('timestamp'),
                'details': details,
                'save_success': save_success,
                'expected_total': expected_total,
            }
            break

    def parse_binding_change(row):
        details = row.get('details') or ''
        action = row.get('action') or ''
        mac = (re.search(r'MAC:([^| ]+)', details) or [None, ''])[1].strip()
        ip_addr = (re.search(r'IP:([^| ]+)', details) or [None, ''])[1].strip()
        source_ip = ''
        source_port = ''
        target_ip = ''
        target_port = ''
        if action == '终端迁移':
            source_match = re.search(r'源:([0-9.]+)\s+([^|\s]+)', details)
            target_match = re.search(r'目标:([0-9.]+)\s+([^|\s]+)', details)
            if source_match:
                source_ip = source_match.group(1)
                source_port = source_match.group(2)
            if target_match:
                target_ip = target_match.group(1)
                target_port = target_match.group(2)
        else:
            port = (re.search(r'端口:([^| ]+)', details) or [None, ''])[1].strip()
            if action == '解除绑定':
                source_ip = row.get('device_ip') or ''
                source_port = port
            else:
                target_ip = row.get('device_ip') or ''
                target_port = port
        action_label = '迁移' if action == '终端迁移' else ('删除' if action == '解除绑定' else '新增')
        return {
            **row,
            'action_label': action_label,
            'mac': mac,
            'ip_address': ip_addr,
            'source_switch_ip': source_ip,
            'source_switch_name': switch_label(source_ip),
            'source_port': source_port,
            'target_switch_ip': target_ip,
            'target_switch_name': switch_label(target_ip),
            'target_port': target_port,
        }

    monthly_binding_changes = {'migrated': 0, 'created': 0, 'deleted': 0}
    for row in monthly_rows:
        action = row.get('action')
        count = binding_change_count(row)
        if action == '终端迁移':
            monthly_binding_changes['migrated'] += count
        elif action == '解除绑定':
            monthly_binding_changes['deleted'] += count
        else:
            monthly_binding_changes['created'] += count

    days_30 = [
        (datetime.datetime.now() - datetime.timedelta(days=offset)).strftime('%Y-%m-%d')
        for offset in range(29, -1, -1)
    ]
    binding_trends = {
        day: {'day': day, 'migrated': 0, 'created': 0, 'deleted': 0}
        for day in days_30
    }
    for row in binding_trend_rows:
        day = row.get('day')
        if day not in binding_trends:
            continue
        count = binding_change_count(row)
        action = row.get('action')
        if action == '终端迁移':
            binding_trends[day]['migrated'] += count
        elif action == '解除绑定':
            binding_trends[day]['deleted'] += count
        else:
            binding_trends[day]['created'] += count

    days_7 = [
        (datetime.datetime.now() - datetime.timedelta(days=offset)).strftime('%Y-%m-%d')
        for offset in range(6, -1, -1)
    ]
    task_trends = {
        day: {'day': day, 'success': 0, 'failed': 0, 'other': 0}
        for day in days_7
    }
    for row in task_trend_rows:
        day = row.get('day')
        if day not in task_trends:
            continue
        status = row.get('status') or ''
        count = int(row.get('count') or 0)
        if status == '成功':
            task_trends[day]['success'] += count
        elif '失败' in status or status == 'error':
            task_trends[day]['failed'] += count
        else:
            task_trends[day]['other'] += count

    high_density_ports = [row for row in port_profile_rows if int(row.get('terminal_count') or 0) >= 3]
    multi_vlan_ports = [row for row in port_profile_rows if int(row.get('vlan_count') or 0) >= 2]
    trunk_ports = [row for row in port_profile_rows if 'trunk' in str(row.get('modes') or '').lower()]
    stale_cutoff = (datetime.datetime.now() - datetime.timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
    stale_ports = [
        row for row in port_profile_rows
        if row.get('last_update') and str(row.get('last_update')) < stale_cutoff
    ]
    top_dense_ports = high_density_ports[:5]

    return {
        'switch_count': switch_count,
        'today_ops': today_ops,
        'mac_binding_count': mac_binding_count,
        'monthly_binding_changes': monthly_binding_changes,
        'recent_binding_changes': [parse_binding_change(row) for row in recent_binding_changes],
        'binding_trends': list(binding_trends.values()),
        'task_health': {
            'trends': list(task_trends.values()),
            'recent_failed': recent_failed_tasks,
        },
        'port_summary': {
            'total_ports': len(port_profile_rows),
            'high_density_count': len(high_density_ports),
            'multi_vlan_count': len(multi_vlan_ports),
            'trunk_count': len(trunk_ports),
            'stale_count': len(stale_ports),
            'top_dense_ports': top_dense_ports,
        },
        'last_backup_status': last_backup['status'] if last_backup else '无记录',
        'last_backup_time': last_backup['timestamp'] if last_backup else '等待今晚执行',
        'last_backup_details': last_backup['details'] if last_backup else '系统尚未执行过自动备份',
        'last_save_config_time': last_save_config['timestamp'] if last_save_config else '暂无保存记录',
        'last_save_config_device': switch_label(last_save_config['device_ip']) if last_save_config else '',
        'last_save_config_details': last_save_config['details'] if last_save_config else '',
        'last_all_save_config_time': last_all_save_config['timestamp'] if last_all_save_config else '暂无全量保存记录',
        'last_all_save_config_details': last_all_save_config['details'] if last_all_save_config else '',
        'last_all_save_config_count': last_all_save_config['save_success'] if last_all_save_config else 0,
    }


def save_compliance_analysis_run(username, filenames, summary, risks):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute(
        '''
        INSERT INTO compliance_analysis_runs (
            created_at, username, ipam_filename, agent_filename, registry_filename, summary, risks
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            now,
            username or '',
            (filenames or {}).get('ipam') or '',
            (filenames or {}).get('agent') or '',
            (filenames or {}).get('registry') or '',
            json.dumps(summary or {}, ensure_ascii=False),
            json.dumps(risks or [], ensure_ascii=False),
        ),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def list_compliance_analysis_runs(limit=20):
    limit = max(1, min(int(limit or 20), 100))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT id, created_at, username, ipam_filename, agent_filename, registry_filename, summary
        FROM compliance_analysis_runs
        ORDER BY id DESC
        LIMIT ?
        ''',
        (limit,),
    )
    rows = []
    for row in cur.fetchall():
        item = dict(row)
        try:
            item['summary'] = json.loads(item.get('summary') or '{}')
        except Exception:
            item['summary'] = {}
        rows.append(item)
    conn.close()
    return rows


def get_compliance_analysis_run(run_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM compliance_analysis_runs WHERE id = ?", (int(run_id),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    try:
        item['summary'] = json.loads(item.get('summary') or '{}')
    except Exception:
        item['summary'] = {}
    try:
        item['risks'] = json.loads(item.get('risks') or '[]')
    except Exception:
        item['risks'] = []
    return item


init_db()
upgrade_db()
