import datetime
import sqlite3
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / 'net_assets.db'


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


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
            vendor TEXT DEFAULT 'h3c'
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

    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_switches_ip_unique ON switches(ip)"
    )

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


def get_all_switches():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM switches ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_switch_by_ip(ip):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM switches WHERE ip = ? LIMIT 1", (ip,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_switch(name, ip, port, username, password, vendor='h3c'):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO switches (name, ip, port, username, password, vendor)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (name, ip, port, username, password, vendor),
    )
    conn.commit()
    conn.close()


def delete_switch(switch_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM switches WHERE id = ?", (switch_id,))
    conn.commit()
    conn.close()


def get_audit_logs(limit=100):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
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
