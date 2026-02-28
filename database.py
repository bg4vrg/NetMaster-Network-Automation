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

def add_switch(name, ip, port, username, password, note=""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO switches (name, ip, port, username, password, note) VALUES (?, ?, ?, ?, ?, ?)",
                (name, ip, port, username, password, note))
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