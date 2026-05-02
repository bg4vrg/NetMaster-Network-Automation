import datetime
import sqlite3
import base64
import hashlib
import os
import json
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash
from cryptography.fernet import Fernet


BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / 'net_assets.db'
KEY_FILE = BASE_DIR / 'net_assets.key'
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
            password_hash TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            update_time DATETIME DEFAULT (datetime('now', 'localtime'))
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
        'auto_data_export_dir': 'data_packages',
        'auto_alarm_collect_enabled': '1',
        'auto_alarm_collect_hour': '4',
        'auto_alarm_collect_minute': '40',
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
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (default_user, generate_password_hash(default_pass)),
        )

    conn.commit()
    conn.close()


def upgrade_db():
    """为旧库补齐字段和索引。"""
    conn = get_db()
    cur = conn.cursor()

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
        'auto_data_export_dir': 'data_packages',
        'auto_alarm_collect_enabled': '1',
        'auto_alarm_collect_hour': '4',
        'auto_alarm_collect_minute': '40',
    }
    for key, value in default_settings.items():
        cur.execute(
            "INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)",
            (key, value),
        )

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


def verify_user(username, password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None


def change_password(username, new_password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (generate_password_hash(new_password), username),
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
        'auto_data_export_dir': get_setting('auto_data_export_dir', 'data_packages') or 'data_packages',
        'auto_alarm_collect_enabled': get_setting('auto_alarm_collect_enabled', '1') == '1',
        'auto_alarm_collect_hour': max(0, min(int(get_setting('auto_alarm_collect_hour', '4') or 4), 23)),
        'auto_alarm_collect_minute': max(0, min(int(get_setting('auto_alarm_collect_minute', '40') or 40), 59)),
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


def update_switch(switch_id, name, ip, port, username, password, vendor='h3c', role='access'):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT ip FROM switches WHERE id = ? LIMIT 1", (switch_id,))
    existing = cur.fetchone()
    if not existing:
        conn.close()
        return False

    old_ip = existing['ip']
    cur.execute(
        '''
        UPDATE switches
        SET name = ?, ip = ?, port = ?, username = ?, password = ?, vendor = ?, role = ?
        WHERE id = ?
        ''',
        (name, ip, port, username, encrypt_secret(password), vendor, role, switch_id),
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


def get_mac_bindings(limit=500):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
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
        ORDER BY mb.update_time DESC
        LIMIT ?
        ''',
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


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
            MAX(mb.update_time) AS last_update
        FROM mac_bindings mb
        LEFT JOIN switches sw ON sw.ip = mb.switch_ip
        GROUP BY mb.switch_ip, mb.port
        ORDER BY terminal_count DESC, last_update DESC
        '''
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_audit_logs(limit=100):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_task_logs(limit=300):
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
        LIMIT ?
        ''',
        (limit,),
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

    conn.close()

    return {
        'switch_count': switch_count,
        'today_ops': today_ops,
        'last_backup_status': last_backup['status'] if last_backup else '无记录',
        'last_backup_time': last_backup['timestamp'] if last_backup else '等待今晚执行',
        'last_backup_details': last_backup['details'] if last_backup else '系统尚未执行过自动备份',
    }


init_db()
upgrade_db()
