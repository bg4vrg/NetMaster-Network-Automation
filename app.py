from apscheduler.schedulers.background import BackgroundScheduler
import os
import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from switch_driver import H3CManager
import database as db
import traceback

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_h3c_admin_tool_2026'

# 🚫 关键端口保护关键词 (不区分大小写)
# 只要端口描述包含这些词，系统将拒绝修改
PROTECTED_KEYWORDS = ['Uplink', 'Trunk', 'Core', 'Connect', 'To', 'hexin', 'huiju', 'link']

# 备份文件存放目录
BACKUP_ROOT = 'backups'
if not os.path.exists(BACKUP_ROOT):
    os.makedirs(BACKUP_ROOT)

# === 登录管理器配置 ===
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    user_data = db.get_user_by_id(user_id)
    if user_data:
        return User(id=user_data['id'], username=user_data['username'])
    return None

# === 辅助函数 ===
def get_manager(data):
    port = int(data.get('port', 22)) 
    return H3CManager(data['ip'], data['user'], data['pass'], port)

# === 页面路由 ===

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = db.verify_user(username, password)
        if user_data:
            user = User(id=user_data['id'], username=user_data['username'])
            login_user(user)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="❌ 用户名或密码错误")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required 
def index():
    return render_template('index.html', username=current_user.username)

# === 资产管理 API ===

@app.route('/api/switches', methods=['GET'])
@login_required
def list_switches():
    switches = db.get_all_switches()
    return jsonify({'status': 'success', 'data': switches})

@app.route('/api/switches/add', methods=['POST'])
@login_required
def add_switch_api():
    d = request.json
    try:
        db.add_switch(d['name'], d['ip'], int(d.get('port',22)), d['user'], d['pass'], d.get('note',''))
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/api/switches/delete', methods=['POST'])
@login_required
def del_switch_api():
    try:
        db.delete_switch(request.json['id'])
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/api/change_password', methods=['POST'])
@login_required
def change_pass_api():
    try:
        new_pass = request.json.get('new_password')
        if not new_pass: return jsonify({'status': 'error', 'msg': '密码不能为空'})
        db.change_password(current_user.username, new_pass)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# ===开放数据接口提供给前端网页调用===
@app.route('/api/audit_logs', methods=['GET'])
@login_required
def api_audit_logs():
    try:
        # 默认拉取最新的 100 条记录
        logs = db.get_audit_logs(limit=100)
        return jsonify({'status': 'success', 'data': logs})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# === 批量备份功能 ===
@app.route('/batch_backup', methods=['POST'])
@login_required
def batch_backup():
    # 1. 获取所有设备
    switches = db.get_all_switches()
    if not switches:
        return jsonify({'status': 'error', 'msg': '数据库中没有设备，请先添加！'})

    # 2. 创建当天的备份文件夹
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_dir = os.path.join(BACKUP_ROOT, today)
    if not os.path.exists(today_dir):
        os.makedirs(today_dir)

    log_messages = [f"🚀 开始执行批量备份，共 {len(switches)} 台设备..."]
    success_count = 0
    fail_count = 0

    # 3. 循环备份
    for sw in switches:
        # 为了防止文件名非法，清理一下名称
        safe_name = sw['name'].replace('/', '_').replace('\\', '_').replace(' ', '_')
        target_ip = sw['ip']
        
        log_messages.append(f"🔄 正在连接: {sw['name']} ({target_ip})...")
        
        try:
            # 连接设备
            mgr = H3CManager(target_ip, sw['username'], sw['password'], sw['port'])
            # 抓取配置
            config_text = mgr.get_full_config()
            
            # 保存文件: backups/2026-02-12/核心交换机_192.168.1.1.cfg
            filename = f"{safe_name}_{target_ip}.cfg"
            filepath = os.path.join(today_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(config_text)
                
            success_count += 1
            log_messages.append(f"<span class='status-permit'>✅ 备份成功</span>: 已保存至 {filename}")
            
        except Exception as e:
            fail_count += 1
            error_msg = str(e)
            if "Authentication failed" in error_msg: error_msg = "认证失败(密码错误)"
            elif "timed out" in error_msg: error_msg = "连接超时"
            log_messages.append(f"<span class='status-deny'>❌ 备份失败</span>: {error_msg}")

    # 4. 总结
    final_msg = f"<br>🏁 <b>任务结束</b><br>成功: {success_count} 台<br>失败: {fail_count} 台<br>📁 文件保存在: {today_dir}"
    full_log = "<br>".join(log_messages) + final_msg
    
    return jsonify({'status': 'success', 'log': full_log})

# === 业务路由 ===

@app.route('/test_connection', methods=['POST'])
@login_required
def test_connection():
    try:
        mgr = get_manager(request.json)
        info = mgr.get_device_info()
        return jsonify({'status': 'success', 'log': info.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/get_interfaces', methods=['POST'])
@login_required
def get_interfaces():
    try:
        mgr = get_manager(request.json)
        interfaces = mgr.get_interface_list()
        return jsonify({'status': 'success', 'data': interfaces})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/get_port_info', methods=['POST'])
@login_required
def get_port_info():
    try:
        mgr = get_manager(request.json)
        info, raw = mgr.get_port_info(request.json['interface'])
        return jsonify({'status': 'success', 'data': info, 'log': f"读取成功。<br>RAW:<br>{raw.replace(chr(10), '<br>')}"})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# === 升级版：绑定接口 (带审计日志) ===
@app.route('/bind_port', methods=['POST'])
@login_required
def bind_port():
    d = request.json
    client_ip = request.remote_addr
    device_ip = d.get('ip', 'Unknown')
    mode = d.get('mode', 'access')
    details = f"端口:{d.get('interface')} | IP:{d.get('bind_ip')} | MAC:{d.get('mac')} | 模式:{mode} | VLAN:{d.get('vlan')}"

    try:
        mgr = get_manager(d)
        
        info, _ = mgr.get_port_info(d['interface'])
        desc = info.get('description', '')
        for kw in PROTECTED_KEYWORDS:
            if kw.lower() in desc.lower():
                # 记录越权操作失败
                db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", f"{details} | 触发保护端口拦截", "失败")
                return jsonify({'status': 'error', 'msg': f"⛔ 拒绝操作！<br>该端口描述包含保护关键词 '{kw}'。"})
        
        log = mgr.configure_port_binding(d['interface'], d['vlan'], d['bind_ip'], d['mac'], mode)
        
        # 🔥 记录成功日志
        db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", details, "成功")
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        # 🔥 记录失败日志
        db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", f"{details} | 报错: {str(e)}", "失败")
        return jsonify({'status': 'error', 'msg': str(e)})

# === 升级版：解绑接口 (带审计日志) ===
@app.route('/del_port_binding', methods=['POST'])
@login_required
def del_port_binding():
    d = request.json
    client_ip = request.remote_addr
    device_ip = d.get('ip', 'Unknown')
    mode = d.get('mode', 'access')
    vlan = d.get('vlan', '')
    details = f"端口:{d.get('interface')} | IP:{d.get('del_ip')} | MAC:{d.get('del_mac')} | 模式:{mode} | VLAN:{vlan}"

    try:
        mgr = get_manager(d)

        info, _ = mgr.get_port_info(d['interface'])
        desc = info.get('description', '')
        for kw in PROTECTED_KEYWORDS:
            if kw.lower() in desc.lower():
                db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", f"{details} | 触发保护端口拦截", "失败")
                return jsonify({'status': 'error', 'msg': f"⛔ 拒绝操作！<br>该端口描述包含保护关键词 '{kw}'。"})

        log = mgr.delete_port_binding(d['interface'], d['del_ip'], d['del_mac'], mode, vlan)
        
        # 🔥 记录成功日志
        db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", details, "成功")
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        # 🔥 记录失败日志
        db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", f"{details} | 报错: {str(e)}", "失败")
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/get_acl', methods=['POST'])
@login_required
def get_acl():
    try:
        mgr = get_manager(request.json)
        rules = mgr.get_acl_rules()
        return jsonify({'status': 'success', 'data': rules})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/add_acl', methods=['POST'])
@login_required
def add_acl():
    try:
        d = request.json
        mgr = get_manager(d)
        rid = d.get('rule_id')
        if rid == "": rid = None
        log = mgr.add_acl_mac(d['mac'], rid)
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/del_acl', methods=['POST'])
@login_required
def del_acl():
    try:
        d = request.json
        mgr = get_manager(d)
        log = mgr.delete_acl_rule(d['rule_id'])
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/save_config', methods=['POST'])
@login_required
def save_config():
    client_ip = request.remote_addr
    device_ip = request.json.get('ip', 'Unknown')
    try:
        mgr = get_manager(request.json)
        log = mgr.save_config_to_device()
        
        db.log_operation(current_user.username, client_ip, device_ip, "保存配置", "执行 save force", "成功")
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        db.log_operation(current_user.username, client_ip, device_ip, "保存配置", f"报错: {str(e)}", "失败")
        return jsonify({'status': 'error', 'msg': str(e)})

# === ⏰ 凌晨幽灵：定时自动备份任务 ===
def auto_backup_task():
    print(f"\n🌙 [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [系统调度] 开始执行凌晨自动备份...")
    switches = db.get_all_switches()
    if not switches:
        print("🌙 [系统调度] 数据库中没有设备，跳过备份。")
        return

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_dir = os.path.join(BACKUP_ROOT, today)
    if not os.path.exists(today_dir):
        os.makedirs(today_dir)

    success_count = 0
    fail_count = 0

    for sw in switches:
        safe_name = sw['name'].replace('/', '_').replace('\\', '_').replace(' ', '_')
        target_ip = sw['ip']
        try:
            mgr = H3CManager(target_ip, sw['username'], sw['password'], sw['port'])
            config_text = mgr.get_full_config()
            filename = f"{safe_name}_{target_ip}.cfg"
            filepath = os.path.join(today_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(config_text)
            success_count += 1
            print(f"  ✅ {target_ip} 备份成功")
        except Exception as e:
            fail_count += 1
            print(f"  ❌ {target_ip} 备份失败: {e}")

    # 🔥 核心联动：记录到我们刚写好的审计日志中！(操作人写死为 System)
    details = f"任务结束。共 {len(switches)} 台。成功: {success_count}, 失败: {fail_count}。路径: {today_dir}"
    status = "成功" if fail_count == 0 else ("部分失败" if success_count > 0 else "全部失败")
    db.log_operation("System(系统)", "Localhost", "ALL_SWITCHES", "定时自动备份", details, status)
    print(f"🌙 [系统调度] 备份任务执行完毕！{details}\n")


# 🚀 初始化并启动后台调度器
scheduler = BackgroundScheduler(timezone="Asia/Shanghai") # 强制指定中国时区，防止服务器时间乱套

# 设定每天凌晨 2:00 准时执行备份任务
scheduler.add_job(func=auto_backup_task, trigger="cron", hour=2, minute=00)

scheduler.start()
# ============================================



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)