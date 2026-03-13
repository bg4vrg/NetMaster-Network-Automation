import openpyxl
from apscheduler.schedulers.background import BackgroundScheduler
import os
import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from switch_driver import H3CManager, HuaweiManager
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

# === 辅助函数：智能调度底层驱动 ===
def get_manager(data):
    port = int(data.get('port', 22)) 
    # 尝试从请求中获取厂商，如果没有，就去数据库里根据 IP 查出来
    vendor = data.get('vendor')
    if not vendor:
        switches = db.get_all_switches()
        target_sw = next((s for s in switches if s['ip'] == data['ip']), None)
        vendor = target_sw.get('vendor', 'h3c') if target_sw else 'h3c'
        
    # 💡 根据厂商智能调度驱动
    if vendor.lower() == 'huawei':
        return HuaweiManager(data['ip'], data['user'], data['pass'], port)
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

# === 📡 资产管理：单台添加设备 (带重复IP校验) ===
@app.route('/api/switches/add', methods=['POST'])
@login_required
def api_add_switch():
    try:
        data = request.json
        # 🛡️ 校验重复 IP
        existing = db.get_all_switches()
        if any(s['ip'] == data['ip'] for s in existing):
            return jsonify({'status': 'error', 'msg': f"添加失败：IP 地址 {data['ip']} 已存在，请勿重复录入！"})
        
        vendor = data.get('vendor', 'h3c').lower()
        db.add_switch(data['name'], data['ip'], data['port'], data['user'], data['pass'], vendor)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# === 📂 资产管理：Excel 批量导入设备接口 (带重复IP跳过机制) ===
@app.route('/api/switches/batch_import', methods=['POST'])
@login_required
def batch_import_switches():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'msg': '未找到文件'})
    file = request.files['file']
    
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file, data_only=True)
        sheet = wb.active
        headers = [str(cell.value).strip() if cell.value is not None else "" for cell in sheet[1]]
        
        required_cols = ['设备名称', 'IP地址', '端口', '用户名', '密码', '厂商']
        col_indices = {}
        for req in required_cols:
            if req in headers:
                col_indices[req] = headers.index(req)
            else:
                return jsonify({'status': 'error', 'msg': f"资产表格缺少必填列头：【{req}】"})

        # 🛡️ 获取当前数据库里所有的 IP 集合，用于排重
        existing_switches = db.get_all_switches()
        existing_ips = {s['ip'] for s in existing_switches}

        success_count = 0
        skip_count = 0 # 记录跳过的重复设备数

        for row in sheet.iter_rows(min_row=2, values_only=True):
            ip = row[col_indices['IP地址']]
            if not ip: continue
            ip = str(ip).strip()
            
            # 🛡️ 如果 IP 已经存在，直接跳过这一行，不报错打断进程
            if ip in existing_ips:
                skip_count += 1
                continue

            name = str(row[col_indices['设备名称']] or f"Switch_{ip}").strip()
            port = int(row[col_indices['端口']] or 22)
            user = str(row[col_indices['用户名']]).strip()
            pwd = str(row[col_indices['密码']]).strip()
            vendor = str(row[col_indices['厂商']] or 'h3c').strip().lower()

            db.add_switch(name, ip, port, user, pwd, vendor)
            
            # 🛡️ 将新加入的 IP 录入集合，防止 Excel 内部有两行一模一样的重复 IP
            existing_ips.add(ip) 
            success_count += 1
            
        msg = f"成功导入 {success_count} 台设备！"
        if skip_count > 0:
            msg += f" (自动拦截并跳过了 {skip_count} 条重复的 IP)"
            
        return jsonify({'status': 'success', 'msg': msg})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': f"导入失败: {str(e)}"})

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
# 开放api接口给数据库做前面板数据
@app.route('/api/dashboard_stats', methods=['GET'])
@login_required
def api_dashboard_stats():
    try:
        stats = db.get_dashboard_stats()
        return jsonify({'status': 'success', 'data': stats})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})


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


# === 📊 Excel 批量导入解析接口 ===
@app.route('/api/parse_excel', methods=['POST'])
@login_required
def parse_excel():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'msg': '未找到上传的文件'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'msg': '文件名为空'})

    try:
        # 读取 Excel (data_only=True 确保读取的是值而不是公式)
        wb = openpyxl.load_workbook(file, data_only=True)
        sheet = wb.active
        
        # 1. 获取表头并校验
        headers = [str(cell.value).strip() if cell.value else "" for cell in sheet[1]]
        required_cols = ['交换机IP', '端口', 'VLAN', '绑定IP', '绑定MAC', '模式']
        
        col_indices = {}
        for req in required_cols:
            if req in headers:
                col_indices[req] = headers.index(req)
            else:
                return jsonify({'status': 'error', 'msg': f"Excel 缺少必填的列头：【{req}】"})

        # 2. 逐行提取数据
        data = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            switch_ip = row[col_indices['交换机IP']]
            if not switch_ip: continue # 如果交换机IP为空，视为结束或空行，直接跳过
            
            data.append({
                'switch_ip': str(switch_ip).strip(),
                'interface': str(row[col_indices['端口']]).strip(),
                'vlan': str(row[col_indices['VLAN']]).strip(),
                'bind_ip': str(row[col_indices['绑定IP']]).strip(),
                'mac': str(row[col_indices['绑定MAC']]).strip(),
                'mode': str(row[col_indices['模式']]).strip().lower()
            })
            
        return jsonify({'status': 'success', 'data': data})
        
    except Exception as e:
        return jsonify({'status': 'error', 'msg': f"读取 Excel 异常: {str(e)}"})

# === 📊 Excel 批量自动化引擎专用接口 ===
@app.route('/api/execute_excel_row', methods=['POST'])
@login_required
def execute_excel_row():
    try:
        d = request.json
        client_ip = request.remote_addr
        switch_ip = d.get('switch_ip')
        interface = d.get('interface')
        vlan = d.get('vlan')
        bind_ip = d.get('bind_ip')
        mac = d.get('mac')
        mode = d.get('mode', 'access')

        # 1. 自动从数据库获取该交换机的账号密码 (免去手动输入)
        switches = db.get_all_switches()
        target_sw = next((s for s in switches if s['ip'] == switch_ip), None)
        if not target_sw:
            return jsonify({'status': 'error', 'msg': f"资产管理库未登记该IP({switch_ip})，无法获取密码"})

        # 2. 组装连接参数
        d['ip'] = switch_ip
        d['user'] = target_sw['username']
        d['pass'] = target_sw['password']
        d['port'] = target_sw['port']

        mgr = get_manager(d)

        # 3. 执行前安全拦截：保护核心上联口
        info, _ = mgr.get_port_info(interface)
        desc = info.get('description', '')
        for kw in PROTECTED_KEYWORDS:
            if kw.lower() in desc.lower():
                details = f"[Excel批量] 端口:{interface} | IP:{bind_ip} | MAC:{mac} | 模式:{mode}"
                db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", f"{details} | 触发保护端口拦截", "失败")
                return jsonify({'status': 'error', 'msg': f"触发保护端口拦截({kw})"})

# 4. 执行底层下发指令，并捕获回显
        raw_log = mgr.configure_port_binding(interface, vlan, bind_ip, mac, mode)

        # 💡 核心修复：安全处理底层函数的奇葩返回值，防止 jsonify 崩溃
        if isinstance(raw_log, bytes):
            log_output = raw_log.decode('utf-8', errors='ignore')
        elif raw_log is None:
            log_output = "> [System] 配置指令已成功发送 (底层函数未返回详细回显)"
        else:
            log_output = str(raw_log)
            
        # 🛡️ 过滤危险字符：防止交换机的 <H3C> 提示符被网页当成 HTML 标签隐藏掉
        log_output = log_output.replace('<', '&lt;').replace('>', '&gt;')

        # 5. 记录成功的审计日志
        details = f"[Excel批量] 端口:{interface} | IP:{bind_ip} | MAC:{mac} | 模式:{mode} | VLAN:{vlan}"
        db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", details, "成功")

        return jsonify({'status': 'success', 'log': log_output})        
    except Exception as e:
        # 记录失败日志
        details = f"[Excel批量] 端口:{interface} | IP:{bind_ip} | MAC:{mac}"
        db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", f"{details} | 报错: {str(e)}", "失败")
        return jsonify({'status': 'error', 'msg': str(e)})

# === 批量备份功能 (完美双引擎 + 时间戳版) ===
@app.route('/batch_backup', methods=['POST'])
@login_required
def batch_backup():
    switches = db.get_all_switches()
    if not switches:
        return jsonify({'status': 'error', 'msg': '数据库中没有设备，请先添加！'})

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_dir = os.path.join(BACKUP_ROOT, today)
    if not os.path.exists(today_dir):
        os.makedirs(today_dir)

    log_messages = [f"🚀 开始执行批量备份，共 {len(switches)} 台设备..."]
    success_count, fail_count = 0, 0

    for sw in switches:
        safe_name = sw['name'].replace('/', '_').replace('\\', '_').replace(' ', '_')
        target_ip = sw['ip']
        vendor = sw.get('vendor', 'h3c').lower()
        
        log_messages.append(f"🔄 正在连接: {sw['name']} ({target_ip}) [{vendor.upper()}]...")
        
        try:
            # 💡 双引擎调度
            if vendor == 'huawei':
                mgr = HuaweiManager(target_ip, sw['username'], sw['password'], sw['port'])
            else:
                mgr = H3CManager(target_ip, sw['username'], sw['password'], sw['port'])
                
            config_text = mgr.get_full_config()
            
            # 💡 文件名加入时分秒后缀，避免一天多次覆盖
            time_suffix = datetime.datetime.now().strftime("%H%M")
            filename = f"{safe_name}_{target_ip}_{time_suffix}.cfg"
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
            log_messages.append(f"<span class='status-deny'>❌ [{target_ip}] 备份失败</span>: {error_msg}")
            try:
                db.log_operation(current_user.username, request.remote_addr, target_ip, "单台配置备份", f"失败原因: {error_msg}", "失败")
            except:
                pass

    final_msg = f"<br>🏁 <b>任务结束</b><br>成功: {success_count} 台<br>失败: {fail_count} 台<br>📁 文件保存在: {today_dir}"
    full_log = "<br>".join(log_messages) + final_msg
    
    try:
        details = f"手动触发批量备份结束。成功: {success_count}, 失败: {fail_count}。存储路径: {today_dir}"
        status = "成功" if fail_count == 0 else ("部分失败" if success_count > 0 else "全部失败")
        client_ip = request.remote_addr
        db.log_operation(current_user.username, client_ip, "ALL_SWITCHES", "手动批量备份", details, status)
    except Exception as e:
        pass

    return jsonify({'status': 'success', 'log': full_log})

# === ⏰ 凌晨幽灵：定时自动备份任务 (完美双引擎 + 时间戳版) ===
def auto_backup_task():
    print(f"\n🌙 [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [系统调度] 开始执行凌晨自动备份...")
    switches = db.get_all_switches()
    if not switches:
        return

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_dir = os.path.join(BACKUP_ROOT, today)
    if not os.path.exists(today_dir):
        os.makedirs(today_dir)

    success_count, fail_count = 0, 0

    for sw in switches:
        safe_name = sw['name'].replace('/', '_').replace('\\', '_').replace(' ', '_')
        target_ip = sw['ip']
        vendor = sw.get('vendor', 'h3c').lower()
        
        try:
            # 💡 双引擎调度
            if vendor == 'huawei':
                mgr = HuaweiManager(target_ip, sw['username'], sw['password'], sw['port'])
            else:
                mgr = H3CManager(target_ip, sw['username'], sw['password'], sw['port'])
                
            config_text = mgr.get_full_config()
            
            # 💡 文件名加入时分秒后缀
            time_suffix = datetime.datetime.now().strftime("%H%M")
            filename = f"{safe_name}_{target_ip}_{time_suffix}.cfg"
            filepath = os.path.join(today_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(config_text)
                
            success_count += 1
            print(f"  ✅ [{vendor.upper()}] {target_ip} 备份成功 -> {filename}")
        except Exception as e:
            fail_count += 1
            error_msg = str(e)
            if "Authentication failed" in error_msg: error_msg = "认证失败(密码错误)"
            elif "timed out" in error_msg: error_msg = "连接超时"
            print(f"  ❌ [{vendor.upper()}] {target_ip} 备份失败: {error_msg}")
            try:
                db.log_operation("System(系统)", "Localhost", target_ip, "定时单台备份", f"失败原因: {error_msg}", "失败")
            except Exception as log_e:
                pass

    details = f"任务结束。共 {len(switches)} 台。成功: {success_count}, 失败: {fail_count}。路径: {today_dir}"
    status = "成功" if fail_count == 0 else ("部分失败" if success_count > 0 else "全部失败")
    
    try:
        db.log_operation("System(系统)", "Localhost", "ALL_SWITCHES", "定时自动备份", details, status)
    except Exception as log_e:
        pass
    print(f"🌙 [系统调度] 备份任务执行完毕！{details}\n")

# 🚀 初始化并启动后台调度器
scheduler = BackgroundScheduler(timezone="Asia/Shanghai") # 强制指定中国时区，防止服务器时间乱套

# 设定每天凌晨 2:00 准时执行备份任务
scheduler.add_job(func=auto_backup_task, trigger="cron", hour=2, minute=37)

scheduler.start()
# ============================================



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)