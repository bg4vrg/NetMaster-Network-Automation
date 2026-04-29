import openpyxl
from apscheduler.schedulers.background import BackgroundScheduler
import os
import datetime
import ipaddress
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from switch_driver import H3CManager, HuaweiManager
import database as db
import traceback

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_h3c_admin_tool_2026'

# 馃毇 鍏抽敭绔彛淇濇姢鍏抽敭璇?(涓嶅尯鍒嗗ぇ灏忓啓)
# 鍙绔彛鎻忚堪鍖呭惈杩欎簺璇嶏紝绯荤粺灏嗘嫆缁濅慨鏀?
PROTECTED_KEYWORDS = ['Uplink', 'Trunk', 'Core', 'Connect', 'To', 'hexin', 'huiju', 'link']

# 澶囦唤鏂囦欢瀛樻斁鐩綍
BACKUP_ROOT = 'backups'
if not os.path.exists(BACKUP_ROOT):
    os.makedirs(BACKUP_ROOT)

# === 鐧诲綍绠＄悊鍣ㄩ厤缃?===
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

# === 杈呭姪鍑芥暟锛氭櫤鑳借皟搴﹀簳灞傞┍鍔?===
def get_manager(data):
    port = int(data.get('port', 22)) 
    # 灏濊瘯浠庤姹備腑鑾峰彇鍘傚晢锛屽鏋滄病鏈夛紝灏卞幓鏁版嵁搴撻噷鏍规嵁 IP 鏌ュ嚭鏉?
    vendor = data.get('vendor')
    if not vendor:
        target_sw = db.get_switch_by_ip(data['ip'])
        vendor = target_sw.get('vendor', 'h3c') if target_sw else 'h3c'
        
    # 馃挕 鏍规嵁鍘傚晢鏅鸿兘璋冨害椹卞姩
    if vendor.lower() == 'huawei':
        return HuaweiManager(data['ip'], data['user'], data['pass'], port)
    return H3CManager(data['ip'], data['user'], data['pass'], port)


def json_error(message, status_code=400):
    return jsonify({'status': 'error', 'msg': message}), status_code


def get_json_data():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('请求体必须为 JSON 对象')
    return data


def require_fields(data, fields):
    missing = []
    for field in fields:
        value = data.get(field)
        if value is None or str(value).strip() == '':
            missing.append(field)
    if missing:
        raise ValueError(f"缺少必填参数：{', '.join(missing)}")


def normalize_ip(value, field_name='IP'):
    text = str(value).strip()
    try:
        ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError(f'{field_name} 格式不正确') from exc
    return text


def normalize_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('端口必须是数字') from exc
    if not 1 <= port <= 65535:
        raise ValueError('端口范围必须在 1-65535 之间')
    return port


def normalize_vendor(value):
    vendor = str(value or 'h3c').strip().lower()
    if vendor not in {'h3c', 'huawei'}:
        raise ValueError('厂商仅支持 h3c 或 huawei')
    return vendor


def normalize_mac(value, field_name='MAC'):
    text = str(value).strip()
    clean = text.replace(':', '').replace('-', '').replace('.', '')
    if len(clean) != 12 or any(ch not in '0123456789abcdefABCDEF' for ch in clean):
        raise ValueError(f'{field_name} 格式不正确')
    return text


def internal_error(message, exc):
    traceback.print_exc()
    return jsonify({'status': 'error', 'msg': message})

# === 椤甸潰璺敱 ===

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
            return render_template('login.html', error="用户名或密码错误")
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

# === 璧勪骇绠＄悊 API ===

@app.route('/api/switches', methods=['GET'])
@login_required
def list_switches():
    switches = db.get_all_switches()
    return jsonify({'status': 'success', 'data': switches})

# === 馃摗 璧勪骇绠＄悊锛氬崟鍙版坊鍔犺澶?(甯﹂噸澶岻P鏍￠獙) ===
@app.route('/api/switches/add', methods=['POST'])
@login_required
def api_add_switch():
    try:
        data = get_json_data()
        require_fields(data, ['name', 'ip', 'port', 'user'])
        data['ip'] = normalize_ip(data['ip'])
        data['port'] = normalize_port(data['port'])
        vendor = normalize_vendor(data.get('vendor'))
        if db.get_switch_by_ip(data['ip']):
            return jsonify({'status': 'error', 'msg': f"添加失败：IP 地址 {data['ip']} 已存在，请勿重复录入！"})

        db.add_switch(data['name'], data['ip'], data['port'], data['user'], data['pass'], vendor)
        return jsonify({'status': 'success'})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('添加设备失败，请检查输入或稍后重试', e)

# === 馃搨 璧勪骇绠＄悊锛欵xcel 鎵归噺瀵煎叆璁惧鎺ュ彛 (甯﹂噸澶岻P璺宠繃鏈哄埗) ===
@app.route('/api/switches/batch_import', methods=['POST'])
@login_required
def batch_import_switches():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'msg': '未找到上传文件'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'msg': '文件名不能为空'})
    
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
                return jsonify({'status': 'error', 'msg': f"资产表格缺少必填列头：{req}"})

        existing_switches = db.get_all_switches()
        existing_ips = {s['ip'] for s in existing_switches}

        success_count = 0
        skip_count = 0

        for row in sheet.iter_rows(min_row=2, values_only=True):
            ip = row[col_indices['IP地址']]
            if not ip:
                continue
            ip = normalize_ip(ip)
            
            if ip in existing_ips:
                skip_count += 1
                continue

            name = str(row[col_indices['设备名称']] or f"Switch_{ip}").strip()
            port = normalize_port(row[col_indices['端口']] or 22)
            user = str(row[col_indices['用户名']] or '').strip()
            pwd = str(row[col_indices['密码']] or '').strip()
            vendor = normalize_vendor(row[col_indices['厂商']] or 'h3c')

            db.add_switch(name, ip, port, user, pwd, vendor)
            
            existing_ips.add(ip) 
            success_count += 1
            
        msg = f"成功导入 {success_count} 台设备！"
        if skip_count > 0:
            msg += f"（自动跳过 {skip_count} 条重复 IP）"
            
        return jsonify({'status': 'success', 'msg': msg})
    except Exception as e:
        return internal_error('批量导入失败，请检查 Excel 内容后重试', e)

@app.route('/api/switches/delete', methods=['POST'])
@login_required
def del_switch_api():
    try:
        data = get_json_data()
        require_fields(data, ['id'])
        db.delete_switch(int(data['id']))
        return jsonify({'status': 'success'})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('删除设备失败，请稍后重试', e)

@app.route('/api/change_password', methods=['POST'])
@login_required
def change_pass_api():
    try:
        data = get_json_data()
        new_pass = data.get('new_password')
        if not new_pass:
            return json_error('密码不能为空')
        db.change_password(current_user.username, new_pass)
        return jsonify({'status': 'success'})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('修改密码失败，请稍后重试', e)

# ===寮€鏀炬暟鎹帴鍙ｆ彁渚涚粰鍓嶇缃戦〉璋冪敤===
@app.route('/api/audit_logs', methods=['GET'])
@login_required
def api_audit_logs():
    try:
        # 榛樿鎷夊彇鏈€鏂扮殑 100 鏉¤褰?
        logs = db.get_audit_logs(limit=100)
        return jsonify({'status': 'success', 'data': logs})
    except Exception as e:
        return internal_error('获取审计日志失败，请稍后重试', e)
# 寮€鏀綼pi鎺ュ彛缁欐暟鎹簱鍋氬墠闈㈡澘鏁版嵁
@app.route('/api/dashboard_stats', methods=['GET'])
@login_required
def api_dashboard_stats():
    try:
        stats = db.get_dashboard_stats()
        return jsonify({'status': 'success', 'data': stats})
    except Exception as e:
        return internal_error('获取统计数据失败，请稍后重试', e)


# === 涓氬姟璺敱 ===

@app.route('/test_connection', methods=['POST'])
@login_required
def test_connection():
    try:
        data = get_json_data()
        require_fields(data, ['ip', 'user', 'pass'])
        data['ip'] = normalize_ip(data['ip'])
        if 'port' in data:
            data['port'] = normalize_port(data['port'])
        if 'vendor' in data:
            data['vendor'] = normalize_vendor(data['vendor'])
        mgr = get_manager(data)
        info = mgr.get_device_info()
        return jsonify({'status': 'success', 'log': info.replace('\n', '<br>')})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('连接测试失败，请检查设备连通性和凭据', e)

@app.route('/get_interfaces', methods=['POST'])
@login_required
def get_interfaces():
    try:
        data = get_json_data()
        require_fields(data, ['ip', 'user', 'pass'])
        data['ip'] = normalize_ip(data['ip'])
        if 'port' in data:
            data['port'] = normalize_port(data['port'])
        if 'vendor' in data:
            data['vendor'] = normalize_vendor(data['vendor'])
        mgr = get_manager(data)
        interfaces = mgr.get_interface_list()
        return jsonify({'status': 'success', 'data': interfaces})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('获取端口列表失败，请检查设备连通性和凭据', e)

@app.route('/get_port_info', methods=['POST'])
@login_required
def get_port_info():
    try:
        data = get_json_data()
        require_fields(data, ['ip', 'user', 'pass', 'interface'])
        data['ip'] = normalize_ip(data['ip'])
        if 'port' in data:
            data['port'] = normalize_port(data['port'])
        if 'vendor' in data:
            data['vendor'] = normalize_vendor(data['vendor'])
        mgr = get_manager(data)
        info, raw = mgr.get_port_info(data['interface'])
        return jsonify({'status': 'success', 'data': info, 'log': f"读取成功。<br>RAW:<br>{raw.replace(chr(10), '<br>')}"})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('获取端口详情失败，请稍后重试', e)

# === 鍗囩骇鐗堬細缁戝畾鎺ュ彛 (甯﹀璁℃棩蹇? ===
@app.route('/bind_port', methods=['POST'])
@login_required
def bind_port():
    try:
        d = get_json_data()
        require_fields(d, ['ip', 'interface', 'bind_ip', 'mac', 'mode'])
        client_ip = request.remote_addr
        d['ip'] = normalize_ip(d['ip'])
        d['bind_ip'] = normalize_ip(d['bind_ip'], '绑定 IP')
        d['mac'] = normalize_mac(d['mac'])
        mode = str(d.get('mode', 'access')).strip().lower()
        if mode not in {'access', 'trunk'}:
            raise ValueError('模式仅支持 access 或 trunk')
        d['mode'] = mode
        if 'vlan' in d and str(d.get('vlan', '')).strip():
            d['vlan'] = str(int(str(d['vlan']).strip()))
        device_ip = d.get('ip', 'Unknown')
        details = f"端口:{d.get('interface')} | IP:{d.get('bind_ip')} | MAC:{d.get('mac')} | 模式:{mode} | VLAN:{d.get('vlan')}"
        mgr = get_manager(d)
        
        info, _ = mgr.get_port_info(d['interface'])
        desc = info.get('description', '')
        for kw in PROTECTED_KEYWORDS:
            if kw.lower() in desc.lower():
                # 璁板綍瓒婃潈鎿嶄綔澶辫触
                db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", f"{details} | 触发受保护端口拦截", "失败")
                return jsonify({'status': 'error', 'msg': f"拒绝执行：该端口描述包含受保护关键字 '{kw}'"})
        
        log = mgr.configure_port_binding(d['interface'], d['vlan'], d['bind_ip'], d['mac'], mode)
        
        # 馃敟 璁板綍鎴愬姛鏃ュ織
        db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", details, "成功")
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        # 馃敟 璁板綍澶辫触鏃ュ織
        db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", f"{details} | 报错: {str(e)}", "失败")
        return internal_error('端口绑定失败，请检查设备状态和参数', e)

# === 鍗囩骇鐗堬細瑙ｇ粦鎺ュ彛 (甯﹀璁℃棩蹇? ===
@app.route('/del_port_binding', methods=['POST'])
@login_required
def del_port_binding():
    try:
        d = get_json_data()
        require_fields(d, ['ip', 'interface', 'del_ip', 'del_mac', 'mode'])
        client_ip = request.remote_addr
        d['ip'] = normalize_ip(d['ip'])
        d['del_ip'] = normalize_ip(d['del_ip'], '解绑 IP')
        d['del_mac'] = normalize_mac(d['del_mac'], '解绑 MAC')
        mode = str(d.get('mode', 'access')).strip().lower()
        if mode not in {'access', 'trunk'}:
            raise ValueError('模式仅支持 access 或 trunk')
        d['mode'] = mode
        vlan = d.get('vlan', '')
        if str(vlan).strip():
            vlan = str(int(str(vlan).strip()))
            d['vlan'] = vlan
        device_ip = d.get('ip', 'Unknown')
        details = f"端口:{d.get('interface')} | IP:{d.get('del_ip')} | MAC:{d.get('del_mac')} | 模式:{mode} | VLAN:{vlan}"
        mgr = get_manager(d)

        info, _ = mgr.get_port_info(d['interface'])
        desc = info.get('description', '')
        for kw in PROTECTED_KEYWORDS:
            if kw.lower() in desc.lower():
                db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", f"{details} | 触发受保护端口拦截", "失败")
                return jsonify({'status': 'error', 'msg': f"拒绝执行：该端口描述包含受保护关键字 '{kw}'"})

        log = mgr.delete_port_binding(d['interface'], d['del_ip'], d['del_mac'], mode, vlan)
        
        # 馃敟 璁板綍鎴愬姛鏃ュ織
        db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", details, "成功")
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        # 馃敟 璁板綍澶辫触鏃ュ織
        db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", f"{details} | 报错: {str(e)}", "失败")
        return internal_error('解除绑定失败，请检查设备状态和参数', e)

@app.route('/get_acl', methods=['POST'])
@login_required
def get_acl():
    try:
        data = get_json_data()
        require_fields(data, ['ip', 'user', 'pass'])
        data['ip'] = normalize_ip(data['ip'])
        if 'port' in data:
            data['port'] = normalize_port(data['port'])
        if 'vendor' in data:
            data['vendor'] = normalize_vendor(data['vendor'])
        mgr = get_manager(data)
        rules = mgr.get_acl_rules()
        return jsonify({'status': 'success', 'data': rules})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('获取 ACL 失败，请稍后重试', e)

@app.route('/add_acl', methods=['POST'])
@login_required
def add_acl():
    try:
        d = get_json_data()
        require_fields(d, ['ip', 'user', 'pass', 'mac'])
        d['ip'] = normalize_ip(d['ip'])
        d['mac'] = normalize_mac(d['mac'])
        if 'port' in d:
            d['port'] = normalize_port(d['port'])
        if 'vendor' in d:
            d['vendor'] = normalize_vendor(d['vendor'])
        mgr = get_manager(d)
        rid = d.get('rule_id')
        if rid == "":
            rid = None
        elif rid is not None:
            rid = str(int(str(rid).strip()))
        log = mgr.add_acl_mac(d['mac'], rid)
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('添加 ACL 失败，请检查参数后重试', e)

@app.route('/del_acl', methods=['POST'])
@login_required
def del_acl():
    try:
        d = get_json_data()
        require_fields(d, ['ip', 'user', 'pass', 'rule_id'])
        d['ip'] = normalize_ip(d['ip'])
        d['rule_id'] = str(int(str(d['rule_id']).strip()))
        if 'port' in d:
            d['port'] = normalize_port(d['port'])
        if 'vendor' in d:
            d['vendor'] = normalize_vendor(d['vendor'])
        mgr = get_manager(d)
        log = mgr.delete_acl_rule(d['rule_id'])
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('删除 ACL 失败，请检查参数后重试', e)

@app.route('/save_config', methods=['POST'])
@login_required
def save_config():
    try:
        data = get_json_data()
        require_fields(data, ['ip', 'user', 'pass'])
        client_ip = request.remote_addr
        data['ip'] = normalize_ip(data['ip'])
        if 'port' in data:
            data['port'] = normalize_port(data['port'])
        if 'vendor' in data:
            data['vendor'] = normalize_vendor(data['vendor'])
        device_ip = data.get('ip', 'Unknown')
        mgr = get_manager(data)
        log = mgr.save_config_to_device()
        
        db.log_operation(current_user.username, client_ip, device_ip, "保存配置", "执行 save force", "成功")
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        db.log_operation(current_user.username, client_ip, device_ip, "保存配置", f"报错: {str(e)}", "失败")
        return internal_error('保存配置失败，请检查设备状态后重试', e)


# === 馃搳 Excel 鎵归噺瀵煎叆瑙ｆ瀽鎺ュ彛 ===
@app.route('/api/parse_excel', methods=['POST'])
@login_required
def parse_excel():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'msg': '未找到上传的文件'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'msg': '文件名不能为空'})

    try:
        wb = openpyxl.load_workbook(file, data_only=True)
        sheet = wb.active
        
        headers = [str(cell.value).strip() if cell.value else "" for cell in sheet[1]]
        required_cols = ['交换机IP', '端口', 'VLAN', '绑定IP', '绑定MAC', '模式']
        
        col_indices = {}
        for req in required_cols:
            if req in headers:
                col_indices[req] = headers.index(req)
            else:
                return jsonify({'status': 'error', 'msg': f"Excel 缺少必填列头：{req}"})

        data = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            switch_ip = row[col_indices['交换机IP']]
            if not switch_ip:
                continue
            switch_ip = normalize_ip(switch_ip, '交换机 IP')
            bind_ip = normalize_ip(row[col_indices['绑定IP']], '绑定 IP')
            mac = normalize_mac(row[col_indices['绑定MAC']])
            mode = str(row[col_indices['模式']]).strip().lower()
            if mode not in {'access', 'trunk'}:
                raise ValueError('模式列仅支持 access 或 trunk')
            
            data.append({
                'switch_ip': switch_ip,
                'interface': str(row[col_indices['端口']]).strip(),
                'vlan': str(row[col_indices['VLAN']]).strip(),
                'bind_ip': bind_ip,
                'mac': mac,
                'mode': mode
            })
            
        return jsonify({'status': 'success', 'data': data})
        
    except Exception as e:
        return internal_error('解析 Excel 失败，请检查文件格式和内容', e)

# === 馃搳 Excel 鎵归噺鑷姩鍖栧紩鎿庝笓鐢ㄦ帴鍙?===
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

        # 1. 鑷姩浠庢暟鎹簱鑾峰彇璇ヤ氦鎹㈡満鐨勮处鍙峰瘑鐮?(鍏嶅幓鎵嬪姩杈撳叆)
        target_sw = db.get_switch_by_ip(switch_ip)
        if not target_sw:
            return jsonify({'status': 'error', 'msg': f"资产管理库未登记该 IP（{switch_ip}），无法获取设备凭据！"})

        # 2. 缁勮杩炴帴鍙傛暟
        d['ip'] = switch_ip
        d['user'] = target_sw['username']
        d['pass'] = target_sw['password']
        d['port'] = target_sw['port']

        mgr = get_manager(d)

        # 3. 鎵ц鍓嶅畨鍏ㄦ嫤鎴細淇濇姢鏍稿績涓婅仈鍙?
        info, _ = mgr.get_port_info(interface)
        desc = info.get('description', '')
        for kw in PROTECTED_KEYWORDS:
            if kw.lower() in desc.lower():
                details = f"[Excel批量] 端口:{interface} | IP:{bind_ip} | MAC:{mac} | 模式:{mode}"
                db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", f"{details} | 触发受保护端口拦截", "失败")
                return jsonify({'status': 'error', 'msg': f"触发受保护端口拦截({kw})"})

# 4. 鎵ц搴曞眰涓嬪彂鎸囦护锛屽苟鎹曡幏鍥炴樉
        raw_log = mgr.configure_port_binding(interface, vlan, bind_ip, mac, mode)

        # 馃挕 鏍稿績淇锛氬畨鍏ㄥ鐞嗗簳灞傚嚱鏁扮殑濂囪懇杩斿洖鍊硷紝闃叉 jsonify 宕╂簝
        if isinstance(raw_log, bytes):
            log_output = raw_log.decode('utf-8', errors='ignore')
        elif raw_log is None:
            log_output = "> [System] 配置指令已成功发送（底层函数未返回详细回显）"
        else:
            log_output = str(raw_log)
            
        # 馃洝锔?杩囨护鍗遍櫓瀛楃锛氶槻姝氦鎹㈡満鐨?<H3C> 鎻愮ず绗﹁缃戦〉褰撴垚 HTML 鏍囩闅愯棌鎺?
        log_output = log_output.replace('<', '&lt;').replace('>', '&gt;')

        # 5. 璁板綍鎴愬姛鐨勫璁℃棩蹇?
        details = f"[Excel批量] 端口:{interface} | IP:{bind_ip} | MAC:{mac} | 模式:{mode} | VLAN:{vlan}"
        db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", details, "成功")

        return jsonify({'status': 'success', 'log': log_output})        
    except Exception as e:
        # 璁板綍澶辫触鏃ュ織
        details = f"[Excel批量] 端口:{interface} | IP:{bind_ip} | MAC:{mac}"
        db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", f"{details} | 报错: {str(e)}", "失败")
        return jsonify({'status': 'error', 'msg': str(e)})

# === 鎵归噺澶囦唤鍔熻兘 (瀹岀編鍙屽紩鎿?+ 鏃堕棿鎴崇増) ===
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

    log_messages = [f"开始执行批量备份，共 {len(switches)} 台设备..."]
    success_count, fail_count = 0, 0

    for sw in switches:
        safe_name = sw['name'].replace('/', '_').replace('\\', '_').replace(' ', '_')
        target_ip = sw['ip']
        vendor = sw.get('vendor', 'h3c').lower()
        
        log_messages.append(f"正在连接: {sw['name']} ({target_ip}) [{vendor.upper()}]...")
        
        try:
            # 馃挕 鍙屽紩鎿庤皟搴?
            if vendor == 'huawei':
                mgr = HuaweiManager(target_ip, sw['username'], sw['password'], sw['port'])
            else:
                mgr = H3CManager(target_ip, sw['username'], sw['password'], sw['port'])
                
            config_text = mgr.get_full_config()
            
            # 馃挕 鏂囦欢鍚嶅姞鍏ユ椂鍒嗙鍚庣紑锛岄伩鍏嶄竴澶╁娆¤鐩?
            time_suffix = datetime.datetime.now().strftime("%H%M")
            filename = f"{safe_name}_{target_ip}_{time_suffix}.cfg"
            filepath = os.path.join(today_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(config_text)
                
            success_count += 1
            log_messages.append(f"<span class='status-permit'>备份成功</span>: 已保存至 {filename}")
            
        except Exception as e:
            fail_count += 1
            error_msg = str(e)
            if "Authentication failed" in error_msg: error_msg = "认证失败(密码错误)"
            elif "timed out" in error_msg: error_msg = "连接超时"
            log_messages.append(f"<span class='status-deny'>[{target_ip}] 备份失败</span>: {error_msg}")
            try:
                db.log_operation(current_user.username, request.remote_addr, target_ip, "单台配置备份", f"失败原因: {error_msg}", "失败")
            except:
                pass

    final_msg = f"<br><b>任务结束</b><br>成功: {success_count} 台<br>失败: {fail_count} 台<br>文件保存于: {today_dir}"
    full_log = "<br>".join(log_messages) + final_msg
    
    try:
        details = f"手动触发批量备份结束。成功: {success_count}, 失败: {fail_count}。存储路径: {today_dir}"
        status = "成功" if fail_count == 0 else ("部分失败" if success_count > 0 else "全部失败")
        client_ip = request.remote_addr
        db.log_operation(current_user.username, client_ip, "ALL_SWITCHES", "手动批量备份", details, status)
    except Exception as e:
        pass

    return jsonify({'status': 'success', 'log': full_log})

# === 鈴?鍑屾櫒骞界伒锛氬畾鏃惰嚜鍔ㄥ浠戒换鍔?(瀹岀編鍙屽紩鎿?+ 鏃堕棿鎴崇増) ===
def auto_backup_task():
    print(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [系统调度] 开始执行凌晨自动备份...")
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
            # 馃挕 鍙屽紩鎿庤皟搴?
            if vendor == 'huawei':
                mgr = HuaweiManager(target_ip, sw['username'], sw['password'], sw['port'])
            else:
                mgr = H3CManager(target_ip, sw['username'], sw['password'], sw['port'])
                
            config_text = mgr.get_full_config()
            
            # 馃挕 鏂囦欢鍚嶅姞鍏ユ椂鍒嗙鍚庣紑
            time_suffix = datetime.datetime.now().strftime("%H%M")
            filename = f"{safe_name}_{target_ip}_{time_suffix}.cfg"
            filepath = os.path.join(today_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(config_text)
                
            success_count += 1
            print(f"  [{vendor.upper()}] {target_ip} 备份成功 -> {filename}")
        except Exception as e:
            fail_count += 1
            error_msg = str(e)
            if "Authentication failed" in error_msg: error_msg = "认证失败(密码错误)"
            elif "timed out" in error_msg: error_msg = "连接超时"
            print(f"  [{vendor.upper()}] {target_ip} 备份失败: {error_msg}")
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
    print(f"[系统调度] 备份任务执行完毕：{details}\n")

# 调度器初始化与启动
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
scheduler.add_job(func=auto_backup_task, trigger="cron", hour=2, minute=37, id="auto_backup", replace_existing=True)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()


start_scheduler()
# ============================================



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
