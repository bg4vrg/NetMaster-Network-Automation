import sqlite3
import os
import datetime  # 新增这一行，用于获取当前时间
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = 'net_assets.db'

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # 让结果像字典一样访问
    return conn

def init_db():
    """初始化数据库：创建表和默认管理员"""
    conn = get_db()
    c = conn.cursor()
    
    # 1. 创建用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL)''')
    
    # 2. 创建交换机资产表
    c.execute('''CREATE TABLE IF NOT EXISTS switches
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  ip TEXT NOT NULL,
                  port INTEGER DEFAULT 22,
                  username TEXT,
                  password TEXT,
                  model TEXT,
                  note TEXT)''')

    # 🔥 3. 新增：创建操作审计日志表 (加入了 username 字段)
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT NOT NULL,
                  username TEXT NOT NULL,
                  client_ip TEXT NOT NULL,
                  device_ip TEXT NOT NULL,
                  action TEXT NOT NULL,
                  details TEXT,
                  status TEXT NOT NULL)''')
    
    # 4. 创建默认管理员账号: admin / admin888
    default_user = 'admin'
    default_pass = 'admin888'
    
    c.execute("SELECT * FROM users WHERE username = ?", (default_user,))
    if not c.fetchone():
        print(f"⚙️ 正在初始化默认管理员账号: {default_user}")
        p_hash = generate_password_hash(default_pass)
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                  (default_user, p_hash))
    
    conn.commit()
    conn.close()


# === 🚀 数据库平滑热升级 ===
def upgrade_db():
    conn = get_db()
    cur = conn.cursor()
    try:
        # 尝试给现有的 switches 表增加 vendor 字段，默认值为 'h3c'
        cur.execute("ALTER TABLE switches ADD COLUMN vendor TEXT DEFAULT 'h3c'")
        conn.commit()
        print("🚀 数据库升级成功：已成功添加 vendor(厂商) 字段！")
    except Exception as e:
        # 如果字段已经存在，会抛出异常，直接忽略即可
        pass
    conn.close()

# 确保在文件最末尾依次调用它们
init_db()
upgrade_db()

# === 🔥 新增：写入审计日志的通用函数 ===
def log_operation(username, client_ip, device_ip, action, details, status):
    try:
        conn = get_db()
        cur = conn.cursor()
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute('''
            INSERT INTO audit_logs (timestamp, username, client_ip, device_ip, action, details, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp, username, client_ip, device_ip, action, details, status))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"写入审计日志失败: {e}")

# === 用户管理 ===
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
    p_hash = generate_password_hash(new_password)
    cur.execute("UPDATE users SET password_hash = ? WHERE username = ?", (p_hash, username))
    conn.commit()
    conn.close()

# === 资产管理 ===
def get_all_switches():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM switches ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_switch(name, ip, port, username, password, vendor='h3c'):
    conn = get_db()
    cur = conn.cursor()
    # 插入时带上 vendor
    cur.execute("INSERT INTO switches (name, ip, port, username, password, vendor) VALUES (?, ?, ?, ?, ?, ?)",
                (name, ip, port, username, password, vendor))
    conn.commit()
    conn.close()

def delete_switch(switch_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM switches WHERE id=?", (switch_id,))
    conn.commit()
    conn.close()

# 每次被引用时尝试初始化，确保表存在
init_db()

# === 操作审计日志管理 ===
def get_audit_logs(limit=100):
    conn = get_db()
    cur = conn.cursor()
    # 按 ID 倒序排列，最新的操作显示在最前面
    cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]
	      
# === 📊 数据看板统计 ===
def get_dashboard_stats():
    conn = get_db()
    cur = conn.cursor()
    
    # 1. 设备总数
    cur.execute("SELECT COUNT(*) FROM switches")
    switch_count = cur.fetchone()[0]
    
    # 2. 今日操作次数
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    cur.execute("SELECT COUNT(*) FROM audit_logs WHERE timestamp LIKE ?", (today + '%',))
    today_ops = cur.fetchone()[0]
    
    # 3. 最近一次定时自动备份的状态
    cur.execute("SELECT status, timestamp, details FROM audit_logs WHERE action = '定时自动备份' ORDER BY id DESC LIMIT 1")
    last_backup = cur.fetchone()
    
    conn.close()
    
    return {
        'switch_count': switch_count,
        'today_ops': today_ops,
        'last_backup_status': last_backup['status'] if last_backup else '无记录',
        'last_backup_time': last_backup['timestamp'] if last_backup else '等待今晚执行',
        'last_backup_details': last_backup['details'] if last_backup else '系统尚未执行过自动备份'
    }