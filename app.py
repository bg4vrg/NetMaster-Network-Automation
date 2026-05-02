import openpyxl
from apscheduler.schedulers.background import BackgroundScheduler
import os
import datetime
import ipaddress
import threading
import json
import subprocess
import sys
import difflib
import csv
import io
import zipfile
import shutil
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from switch_driver import H3CManager, HuaweiManager
import database as db
import traceback

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_h3c_admin_tool_2026'

APP_VERSION = "2.10.0"
APP_RELEASE_DATE = "2026-05-01"
APP_VERSION_INFO = {
    "version": APP_VERSION,
    "release_date": APP_RELEASE_DATE,
    "name": "NetMaster 自动化运维平台",
    "summary": "面向专网环境的多厂商交换机自动化运维工具，重点强化终端绑定、终端漫游、自动备份和审计追踪。",
    "features": [
        "H3C/Huawei 交换机资产管理、连接测试、端口查询和配置保存",
        "ACL 策略组管理、端口 IP/MAC 绑定、解绑和端口描述维护",
        "Excel 批量导入设备与批量绑定，支持同端口多终端聚合下发",
        "终端漫游：定位旧绑定、清理旧端口、部署新端口并更新已绑定终端列表",
        "已绑定终端列表：支持交换机名称展示、CSV 导出、终端更新和冲突保护",
        "配置差异比对：基于本地备份文件对比两次交换机配置变化",
        "任务中心、端口画像、运行健康检查和终端漫游试运行",
        "交换机资产密码本地加密存储，兼容旧明文记录自动迁移",
        "数据备份与恢复：网页导出/导入数据库、密钥和关键清单",
        "离线绑定导入、深度在线健康检查、交换机日志告警采集入库和定时任务可调",
        "每日自动配置备份、备份后保存配置、终端绑定信息定时更新",
        "审计日志和首页看板，支持专网离线运行，无外部 CDN 或远程 API 依赖",
    ],
    "updates": [
        "告警中心新增确认/忽略/备注闭环、近 7 天趋势和状态筛选，顶部重复告警按钮已移除",
        "日志分类修正：SOFTCAR ARP DROP 单独归为 ARP限速/控制平面保护，不再误归 ACL/丢包",
        "首页看板新增当前网络告警卡片，直接展示高危/中风险/采集失败并可打开告警中心",
        "新增告警中心：按设备最新告警聚合、风险排序、Top 优先处理、筛选和折叠原始日志",
        "最近日志分析支持默认折叠查看匹配原始日志，并去除高频端口重复展示",
        "日志告警分析修正：SSH 成功登录/退出不再误判为认证异常，健康检查摘要改为紧凑排版",
        "日志告警分析增强：支持风险评分、风险等级、分类统计、高频端口提取和更细的处置建议",
        "运行健康检查中的任务调度时间改为紧凑时间卡片，任务中心终端更新名称改为汇总/单台设备并优化摘要排序",
        "离线导入预览新增唯一终端和重复记录统计，日志告警支持每日定时采集、分析入库和网页查看",
        "新增离线导入绑定库、深度在线健康检查、交换机日志告警分析、定时任务时间可调和自动数据包导出",
        "新增数据备份/恢复：导出 net_assets.db、net_assets.key、交换机资产清单和已绑定终端清单",
        "新增任务中心、端口画像、运行健康检查、终端漫游试运行、可调系统参数和资产密码本地加密",
        "新增配置差异比对页签，可选择两份本地备份文件查看新增/删除配置行",
        "ACL 管理升级：支持查询交换机全部 ACL 策略组，并可按 ACL 组号维护 MAC 规则",
        "新增系统设置：可控制定时备份成功后是否自动保存设备配置",
        "README 更新为当前离线专网版本说明，并标注后续优化路线",
        "管理设备列表新增按名称、角色、厂商、IP 排序，并支持直接修改设备参数",
        "简化资产角色模型：接入交换机参与终端更新，备份设备只参与配置备份",
        "已绑定终端列表新增搜索、模式筛选、同 IP 多 MAC 和同 MAC 多位置筛选",
        "新增网页可见版本信息入口，集中展示当前版本功能和更新内容",
        "终端列表新增交换机名称列和 CSV 导出功能",
        "终端更新改为发现/新增/更新/未变统计，未变记录刷新确认时间",
        "修正默认 VLAN 1 解析，未显式配置 VLAN 的接入口按 VLAN 1 入库",
        "终端漫游新增 IP 冲突保护、旧端口解绑复核和新端口差异化部署",
        "终端更新采用子进程隔离和并发扫描，减少超时残留并提升速度",
        "定时备份后自动保存配置，并记录每台设备保存结果",
        "首页设备连接区压缩布局，减少快捷连接区域留白",
    ],
    "backup": "project_backup_20260501_114009",
}

# 馃毇 鍏抽敭绔彛淇濇姢鍏抽敭璇?(涓嶅尯鍒嗗ぇ灏忓啓)
# 鍙绔彛鎻忚堪鍖呭惈杩欎簺璇嶏紝绯荤粺灏嗘嫆缁濅慨鏀?
PROTECTED_KEYWORDS = ['Uplink', 'Trunk', 'Core', 'Connect', 'To', 'hexin', 'huiju', 'link']

# 澶囦唤鏂囦欢瀛樻斁鐩綍
BACKUP_ROOT = 'backups'
if not os.path.exists(BACKUP_ROOT):
    os.makedirs(BACKUP_ROOT)

MAC_SYNC_LOCK = threading.Lock()
MAC_SYNC_STATE_LOCK = threading.Lock()
MAC_SYNC_SWITCH_TIMEOUT = 90
MAC_SYNC_MAX_WORKERS = 4
MAC_SYNC_STATE = {
    'running': False,
    'status': 'idle',
    'message': '尚未执行同步',
    'started_at': '',
    'finished_at': '',
    'actor': '',
    'current_switch_index': 0,
    'total_switches': 0,
    'current_switch_ip': '',
    'current_switch_name': '',
    'synced': 0,
    'found': 0,
    'created': 0,
    'updated': 0,
    'unchanged': 0,
    'errors': [],
}

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


def normalize_vlan(value, field_name='VLAN', allow_empty=False):
    text = str(value or '').strip()
    if not text:
        if allow_empty:
            return ''
        raise ValueError(f'{field_name} 不能为空')
    if not text.isdigit():
        raise ValueError(f'{field_name} 必须是数字')
    vlan = int(text)
    if not 1 <= vlan <= 4094:
        raise ValueError(f'{field_name} 范围必须在 1-4094 之间')
    return str(vlan)


def normalize_vendor(value):
    vendor = str(value or 'h3c').strip().lower()
    if vendor not in {'h3c', 'huawei', 'ruijie'}:
        raise ValueError('厂商仅支持 h3c、huawei 或 ruijie')
    return vendor


def normalize_switch_role(value):
    role = str(value or 'access').strip().lower()
    if role not in {'access', 'backup'}:
        raise ValueError('设备角色仅支持 access 或 backup')
    return role


def normalize_bool_flag(value, default=True):
    if value is None:
        return 1 if default else 0
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in {'1', 'true', 'yes', 'on', '启用', '是'}:
        return 1
    if text in {'0', 'false', 'no', 'off', '禁用', '否'}:
        return 0
    raise ValueError('布尔字段只能是启用/禁用或 true/false')


def normalize_mac(value, field_name='MAC'):
    text = str(value).strip()
    clean = text.replace(':', '').replace('-', '').replace('.', '')
    if len(clean) != 12 or any(ch not in '0123456789abcdefABCDEF' for ch in clean):
        raise ValueError(f'{field_name} 格式不正确')
    return text


def normalize_mode(value, field_name='模式'):
    mode = str(value or 'access').strip().lower()
    if mode not in {'access', 'trunk'}:
        raise ValueError(f'{field_name} 仅支持 access 或 trunk')
    return mode


def normalize_acl_number(value, field_name='ACL 组号'):
    number = int(str(value or '4000').strip())
    if number < 2000 or number > 4999:
        raise ValueError(f'{field_name} 必须在 2000-4999 范围内')
    return str(number)


def get_runtime_settings():
    return db.get_system_settings()


def get_mac_sync_timeout():
    return int(get_runtime_settings().get('mac_sync_timeout') or MAC_SYNC_SWITCH_TIMEOUT)


def get_mac_sync_max_workers():
    return int(get_runtime_settings().get('mac_sync_max_workers') or MAC_SYNC_MAX_WORKERS)


def get_protected_keywords():
    text = str(get_runtime_settings().get('protected_keywords') or '').strip()
    if not text:
        return PROTECTED_KEYWORDS
    return [item.strip() for item in text.replace('\n', ',').split(',') if item.strip()]


def format_switch_log(raw_log):
    if isinstance(raw_log, bytes):
        text = raw_log.decode('utf-8', errors='ignore')
    elif raw_log is None:
        text = '> [System] 配置指令已成功发送（底层函数未返回详细回显）'
    else:
        text = str(raw_log)
    return text.replace('<', '&lt;').replace('>', '&gt;')


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


def csv_text(headers, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, '') for key in headers})
    return '\ufeff' + buffer.getvalue()


def create_data_package():
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    memory_file = io.BytesIO()
    db_path = os.path.abspath(db.DB_NAME)
    key_path = os.path.abspath(db.KEY_FILE)
    switch_headers = ['id', 'name', 'ip', 'port', 'username', 'vendor', 'role']
    binding_headers = ['mac_address', 'ip_address', 'switch_ip', 'switch_name', 'port', 'vlan', 'mode', 'update_time']
    manifest = {
        'app': 'NetMaster',
        'version': APP_VERSION,
        'created_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'contains': ['net_assets.db', 'net_assets.key', 'switch_assets.csv', 'mac_bindings.csv'],
        'note': 'net_assets.db 与 net_assets.key 必须成对保存，否则加密后的交换机密码无法解密。',
    }
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as package:
        package.write(db_path, 'net_assets.db')
        if os.path.exists(key_path):
            package.write(key_path, 'net_assets.key')
        package.writestr('switch_assets.csv', csv_text(switch_headers, db.get_all_switches()))
        package.writestr('mac_bindings.csv', csv_text(binding_headers, db.get_mac_bindings(limit=100000)))
        package.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    memory_file.seek(0)
    return memory_file, f'netmaster_data_package_{timestamp}.zip'


def write_data_package_to_dir(target_dir=None):
    settings = db.get_system_settings()
    target_dir = target_dir or settings.get('auto_data_export_dir') or 'data_packages'
    target_dir = os.path.abspath(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    memory_file, filename = create_data_package()
    full_path = os.path.join(target_dir, filename)
    with open(full_path, 'wb') as fh:
        fh.write(memory_file.getvalue())
    return full_path


def restore_data_package(file_storage):
    raw = file_storage.read()
    if not raw:
        raise ValueError('上传文件为空')
    try:
        package = zipfile.ZipFile(io.BytesIO(raw), 'r')
    except zipfile.BadZipFile:
        raise ValueError('导入文件不是有效 zip 数据包')
    names = set(package.namelist())
    if 'net_assets.db' not in names:
        raise ValueError('数据包缺少 net_assets.db')

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    restore_backup_dir = os.path.abspath(os.path.join('data_restore_backups', timestamp))
    os.makedirs(restore_backup_dir, exist_ok=True)
    db_path = os.path.abspath(db.DB_NAME)
    key_path = os.path.abspath(db.KEY_FILE)
    if os.path.exists(db_path):
        shutil.copy2(db_path, os.path.join(restore_backup_dir, 'net_assets.db'))
    if os.path.exists(key_path):
        shutil.copy2(key_path, os.path.join(restore_backup_dir, 'net_assets.key'))

    tmp_db = db_path + f'.import_{timestamp}.tmp'
    tmp_key = key_path + f'.import_{timestamp}.tmp'
    try:
        with open(tmp_db, 'wb') as fh:
            fh.write(package.read('net_assets.db'))
        if 'net_assets.key' in names:
            with open(tmp_key, 'wb') as fh:
                fh.write(package.read('net_assets.key'))
        shutil.move(tmp_db, db_path)
        if os.path.exists(tmp_key):
            shutil.move(tmp_key, key_path)
    finally:
        for path in [tmp_db, tmp_key]:
            if os.path.exists(path):
                os.remove(path)
        package.close()
    return restore_backup_dir


def preview_data_package(file_storage):
    raw = file_storage.read()
    if not raw:
        raise ValueError('上传文件为空')
    try:
        package = zipfile.ZipFile(io.BytesIO(raw), 'r')
    except zipfile.BadZipFile:
        raise ValueError('导入文件不是有效 zip 数据包')
    names = set(package.namelist())
    manifest = {}
    if 'manifest.json' in names:
        try:
            manifest = json.loads(package.read('manifest.json').decode('utf-8', errors='replace'))
        except Exception:
            manifest = {}
    result = {
        'has_db': 'net_assets.db' in names,
        'has_key': 'net_assets.key' in names,
        'has_switch_csv': 'switch_assets.csv' in names,
        'has_binding_csv': 'mac_bindings.csv' in names,
        'manifest': manifest,
        'files': sorted(names),
    }
    if 'switch_assets.csv' in names:
        result['switch_csv_rows'] = max(0, len(package.read('switch_assets.csv').decode('utf-8-sig', errors='replace').splitlines()) - 1)
    if 'mac_bindings.csv' in names:
        result['binding_csv_rows'] = max(0, len(package.read('mac_bindings.csv').decode('utf-8-sig', errors='replace').splitlines()) - 1)
    package.close()
    return result


def parse_bindings_from_config(config_text, switch_ip):
    bindings = []
    current_iface = ''
    current_vlan = '1'
    current_mode = 'trunk'
    for raw_line in str(config_text or '').splitlines():
        line = raw_line.strip()
        if line.startswith('interface '):
            full_name = line.split(' ', 1)[1].strip()
            current_iface = full_name.replace('Ten-GigabitEthernet', 'XGE')\
                                     .replace('XGigabitEthernet', 'XGE')\
                                     .replace('M-GigabitEthernet', 'MGE')\
                                     .replace('GigabitEthernet', 'GE')\
                                     .replace('Bridge-Aggregation', 'BAGG')\
                                     .replace('Ethernet', 'Eth')
            current_vlan = '1'
            current_mode = 'trunk'
            continue
        if not current_iface:
            continue
        if line.startswith(('port access vlan', 'port default vlan')):
            parts = line.split()
            if parts:
                current_vlan = parts[-1]
        elif line.startswith('port trunk pvid vlan'):
            parts = line.split()
            if parts:
                current_vlan = parts[-1]
        elif 'ip verify source' in line or 'source check user-bind enable' in line:
            current_mode = 'access'
        if ('ip source binding' in line or 'user-bind static' in line) and 'ip-address' in line:
            ip_match = re.search(r'ip-address\s+([\d.]+)', line)
            mac_match = re.search(r'mac-address\s+([0-9a-fA-F:.\-]+)', line)
            vlan_match = re.search(r'\bvlan\s+(\d+)', line)
            if ip_match and mac_match:
                bindings.append({
                    'switch_ip': switch_ip,
                    'switch_port': current_iface,
                    'ip': ip_match.group(1),
                    'mac': mac_match.group(1),
                    'vlan': vlan_match.group(1) if vlan_match else current_vlan,
                    'mode': current_mode if not vlan_match else 'trunk',
                })
    return bindings


def import_bindings_from_backup_files(limit=2000, apply=False):
    files = list_backup_config_files(limit=limit)
    found = 0
    unique_map = {}
    duplicate_count = 0
    created = 0
    updated = 0
    unchanged = 0
    errors = []
    preview = []
    for item in files:
        switch_ip = item.get('device_ip') or ''
        try:
            normalize_ip(switch_ip, '备份文件交换机 IP')
        except ValueError:
            continue
        try:
            lines = read_backup_text(item['path'])
            bindings = parse_bindings_from_config('\n'.join(lines), switch_ip)
            found += len(bindings)
            for binding in bindings:
                key = (normalize_mac(binding['mac']).lower(), binding['ip'])
                if key in unique_map:
                    duplicate_count += 1
                    old = unique_map[key]
                    if item.get('date', '') >= old.get('backup_date', ''):
                        unique_map[key] = {**binding, 'backup_file': item['path'], 'backup_date': item.get('date', '')}
                else:
                    unique_map[key] = {**binding, 'backup_file': item['path'], 'backup_date': item.get('date', '')}
        except Exception as exc:
            errors.append(f"{item.get('path')}: {exc}")
    if apply:
        for binding in unique_map.values():
            action = save_binding_state(
                binding['switch_ip'],
                binding['switch_port'],
                binding['vlan'],
                binding['ip'],
                binding['mac'],
                binding['mode'],
            )
            if action == 'created':
                created += 1
            elif action == 'updated':
                updated += 1
            else:
                unchanged += 1
    preview = list(unique_map.values())[:200]
    return {
        'files': len(files),
        'found': found,
        'unique_terminals': len(unique_map),
        'duplicates': duplicate_count,
        'created': created,
        'updated': updated,
        'unchanged': unchanged,
        'errors': errors[:20],
        'preview': preview,
    }


def analyze_alarm_log_text(text):
    rules = [
        {'level': 'critical', 'category': '环路/风暴', 'score': 35, 'words': ['loop', 'storm', 'broadcast storm', 'mac-flapping', 'mac address flapping'], 'suggestion': '疑似环路、广播风暴或 MAC 漂移，建议立即检查 STP、下联小交换机、近期新增网线和异常端口。'},
        {'level': 'critical', 'category': '硬件/环境', 'score': 30, 'words': ['fan failed', 'power failed', 'temperature', 'overheat', 'over-temperature', 'voltage', 'psu', 'fatal', 'panic'], 'suggestion': '存在硬件或环境异常，建议检查风扇、电源、温度、机柜散热和设备面板告警。'},
        {'level': 'critical', 'category': '链路/端口中断', 'score': 18, 'words': ['link down', 'line protocol is down', 'interface down', 'changed state to down', 'unreachable'], 'suggestion': '存在链路或端口中断记录，建议核对高频端口的光模块、网线、对端设备和上联链路。'},
        {'level': 'warning', 'category': '链路抖动', 'score': 10, 'words': ['flap', 'updown', 'link up', 'changed state to up', 'port up'], 'suggestion': '存在端口抖动记录，建议按高频端口检查终端、网线、水晶头、光模块和速率双工协商。'},
        {'level': 'warning', 'category': 'STP 变化', 'score': 12, 'words': ['stp', 'spanning tree', 'topology change', 'tc event'], 'suggestion': '存在 STP 拓扑变化，建议确认是否有非法接入、小交换机、环路恢复或上联切换。'},
        {'level': 'warning', 'category': '认证/登录', 'score': 8, 'words': ['login failed', 'authentication failed', 'auth fail', 'password failed', 'invalid user', 'illegal user', 'failed password', 'sshs_auth_fail', 'telnet login failed'], 'suggestion': '存在认证或登录失败，建议核对来源地址、账号权限、弱口令尝试和堡垒机登录记录。'},
        {'level': 'warning', 'category': 'ARP限速/控制平面保护', 'score': 14, 'words': ['softcar drop', 'pkttype=arp'], 'require_all': True, 'suggestion': '发现 ARP 报文触发 SOFTCAR 控制平面保护丢弃，建议优先检查高频端口、源 MAC、ARP 异常、环路或下挂设备广播异常。'},
        {'level': 'warning', 'category': 'ACL/策略丢弃', 'score': 6, 'words': ['acl', 'deny', 'packet filter'], 'suggestion': '存在 ACL 或策略丢弃关键字，建议核对安全策略、命中方向和业务访问是否符合预期。'},
        {'level': 'warning', 'category': '资源/性能', 'score': 10, 'words': ['cpu', 'memory', 'high utilization', 'threshold', 'busy'], 'suggestion': '存在资源或性能告警，建议检查 CPU、内存、广播流量、日志风暴和管理进程状态。'},
        {'level': 'warning', 'category': '超时/管理链路', 'score': 6, 'words': ['timeout', 'timed out', 'ntp', 'snmp', 'radius', 'tacacs'], 'suggestion': '存在超时或管理链路关键字，建议检查管理网络、NTP/SNMP/RADIUS/TACACS 可达性和设备负载。'},
    ]
    lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
    scan_lines = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if 'softcar drop' in line.lower() and index + 1 < len(lines) and 'pkttype=' in lines[index + 1].lower():
            scan_lines.append(f"{line} {lines[index + 1]}")
            index += 2
            continue
        scan_lines.append(line)
        index += 1
    matched = []
    critical = 0
    warning = 0
    risk_score = 0
    suggestion_map = {}
    category_counts = {}
    port_counts = {}
    port_pattern = re.compile(r'\b(?:GE|XGE|GigabitEthernet|Ten-GigabitEthernet|FortyGigE|Eth|Ethernet|Bridge-Aggregation|Vlan-interface)\s*\d+(?:/\d+){0,3}\b', re.I)
    def normalize_log_port(port):
        text = re.sub(r'\s+', '', str(port or '')).upper()
        replacements = [
            ('TEN-GIGABITETHERNET', 'XGE'),
            ('GIGABITETHERNET', 'GE'),
            ('FORTYGIGE', 'FGE'),
            ('ETHERNET', 'ETH'),
            ('BRIDGE-AGGREGATION', 'BAGG'),
            ('VLAN-INTERFACE', 'VLANIF'),
        ]
        for old, new in replacements:
            if text.startswith(old):
                return new + text[len(old):]
        return text
    for line in scan_lines[-500:]:
        lower = line.lower()
        benign_auth = any(
            word in lower
            for word in [
                'auth_success',
                'authentication succeeded',
                'passed password authentication',
                'logged out',
                'disconnect',
                'connected to the server successfully',
                'sshs_connect',
                'sshs_log',
            ]
        )
        if benign_auth:
            continue
        for rule in rules:
            matched_rule = all(word in lower for word in rule['words']) if rule.get('require_all') else any(word in lower for word in rule['words'])
            if matched_rule:
                level = rule['level']
                category = rule['category']
                if level == 'critical':
                    critical += 1
                else:
                    warning += 1
                risk_score += rule['score']
                category_counts[category] = category_counts.get(category, 0) + 1
                suggestion_map[category] = rule['suggestion']
                ports = [normalize_log_port(port) for port in port_pattern.findall(line)]
                for port in ports:
                    port_counts[port] = port_counts.get(port, 0) + 1
                matched.append({'level': level, 'category': category, 'ports': ports, 'line': line})
                break
    if critical >= 5 or risk_score >= 80:
        risk_level = 'high'
        headline = '高风险：发现多条严重告警，建议优先排查环路、硬件环境和关键链路。'
    elif critical or warning >= 5 or risk_score >= 30:
        risk_level = 'medium'
        headline = '中风险：存在需要关注的告警，建议按分类和高频端口逐项核对。'
    elif warning:
        risk_level = 'low'
        headline = '低风险：发现少量告警关键字，建议观察趋势并核对相关端口。'
    else:
        risk_level = 'normal'
        headline = '正常：未发现明显严重告警关键字，可继续观察。'
    top_ports = [{'port': port, 'count': count} for port, count in sorted(port_counts.items(), key=lambda item: item[1], reverse=True)[:10]]
    suggestions = list(suggestion_map.values())
    if top_ports:
        suggestions.insert(0, f"高频端口：{', '.join([item['port'] + ' x' + str(item['count']) for item in top_ports[:5]])}。建议优先核对这些端口。")
    if not suggestions:
        suggestions.append('未发现明显严重告警关键字，可继续观察。')
    return {
        'total_lines': len(lines),
        'critical': critical,
        'warning': warning,
        'risk_score': min(risk_score, 100),
        'risk_level': risk_level,
        'headline': headline,
        'category_counts': category_counts,
        'top_ports': top_ports,
        'matched': matched[-100:],
        'suggestions': suggestions,
    }


def collect_switch_alarm_report(switch_ip):
    runtime = get_switch_runtime_data(switch_ip)
    switch_row = db.get_switch_by_ip(switch_ip) or {}
    mgr = get_manager(runtime)
    raw = mgr.get_alarm_logs()
    analysis = analyze_alarm_log_text(raw)
    db.add_switch_alarm_report(
        switch_ip=switch_ip,
        switch_name=switch_row.get('name', ''),
        vendor=runtime.get('vendor', ''),
        status='成功',
        analysis=analysis,
    )
    return {'raw': raw, 'analysis': analysis, 'switch': switch_row}


ALARM_COMMAND_GUIDE = {
    '环路/风暴': [
        {'cmd': 'display stp brief', 'desc': '查看 STP 根桥、端口角色和阻塞状态，确认是否存在异常拓扑变化。'},
        {'cmd': 'display mac-address flapping', 'desc': '查看 MAC 漂移记录，定位疑似环路或来回漂移的端口。'},
        {'cmd': 'display interface brief', 'desc': '快速查看端口 up/down 和流量异常端口。'},
    ],
    '链路/端口中断': [
        {'cmd': 'display interface <端口>', 'desc': '查看端口物理状态、错误包、速率双工、收发光功率等详细信息。'},
        {'cmd': 'display transceiver diagnosis interface <端口>', 'desc': '查看光模块诊断信息，排查光功率、温度、电压异常。'},
    ],
    '链路抖动': [
        {'cmd': 'display logbuffer | include <端口>', 'desc': '按端口过滤日志，确认抖动时间和频率。'},
        {'cmd': 'display interface <端口>', 'desc': '检查 CRC、input error、协商状态和端口重启计数。'},
    ],
    'STP 变化': [
        {'cmd': 'display stp brief', 'desc': '查看 STP 端口角色和状态，确认是否频繁变化。'},
        {'cmd': 'display stp history', 'desc': '查看 STP 历史变化记录，定位触发拓扑变化的端口。'},
    ],
    'ARP限速/控制平面保护': [
        {'cmd': 'display interface <高频端口>', 'desc': '检查高频端口广播/错误包/流量状态，确认 ARP 来源方向。'},
        {'cmd': 'display mac-address <源MAC>', 'desc': '定位日志中的源 MAC 当前学习在哪个端口或下游链路。'},
        {'cmd': 'display arp | include <源MAC或IP>', 'desc': '关联源 MAC 与 IP，判断是否为异常终端、网关或下挂设备。'},
        {'cmd': 'display stp brief', 'desc': '确认是否存在环路或 STP 拓扑异常导致 ARP 广播异常。'},
        {'cmd': 'display logbuffer | include SOFTCAR|ARP|<端口>', 'desc': '查看 SOFTCAR ARP DROP 的频率、端口和上下文。'},
    ],
    'ACL/策略丢弃': [
        {'cmd': 'display acl all', 'desc': '查看 ACL 规则，确认是否有误拦截或规则顺序问题。'},
        {'cmd': 'display packet-filter interface <端口>', 'desc': '查看端口方向上绑定的包过滤策略。'},
        {'cmd': 'display traffic classifier user-defined', 'desc': '查看流分类，辅助排查 QoS/安全策略命中。'},
    ],
    '认证/登录': [
        {'cmd': 'display local-user', 'desc': '核对本地账号和权限。'},
        {'cmd': 'display ssh server status', 'desc': '查看 SSH 服务状态和登录限制。'},
        {'cmd': 'display logbuffer | include LOGIN|AUTH|SSHS', 'desc': '过滤登录认证日志，确认是否存在失败尝试。'},
    ],
    '资源/性能': [
        {'cmd': 'display cpu-usage', 'desc': '查看 CPU 使用率和高负载进程。'},
        {'cmd': 'display memory', 'desc': '查看内存使用情况。'},
    ],
    '超时/管理链路': [
        {'cmd': 'ping <网管服务器IP>', 'desc': '验证到网管、认证或日志服务器的连通性。'},
        {'cmd': 'display ntp-service status', 'desc': '检查时间同步状态。'},
    ],
}


def build_alarm_command_suggestions(category_counts):
    commands = []
    seen = set()
    for category in sorted((category_counts or {}).keys(), key=lambda key: category_counts.get(key, 0), reverse=True):
        for item in ALARM_COMMAND_GUIDE.get(category, []):
            if item['cmd'] in seen:
                continue
            seen.add(item['cmd'])
            commands.append({'category': category, **item})
            if len(commands) >= 8:
                return commands
    return commands


def get_switch_runtime_data(switch_ip):
    target_sw = db.get_switch_by_ip(switch_ip)
    if not target_sw:
        raise ValueError(f"资产管理库未登记该 IP（{switch_ip}），无法获取设备凭据")
    return {
        'ip': switch_ip,
        'user': target_sw['username'],
        'pass': target_sw['password'],
        'port': target_sw['port'],
        'vendor': target_sw.get('vendor', 'h3c'),
    }


def assert_interface_not_protected(mgr, interface_name):
    info, raw = mgr.get_port_info(interface_name)
    info['_raw_config'] = raw
    desc = info.get('description', '')
    for kw in get_protected_keywords():
        if kw.lower() in desc.lower():
            raise ValueError(f"拒绝执行：该端口描述包含受保护关键字 '{kw}'")
    return info


def normalize_terminal_lookup(query):
    text = str(query or '').strip()
    if not text:
        raise ValueError('请输入 MAC 地址或 IP 地址')
    try:
        return 'ip', normalize_ip(text, '查询 IP')
    except ValueError:
        return 'mac', normalize_mac(text, '查询 MAC')


def get_terminal_binding_record(query, source_switch_ip=None):
    query_type, value = normalize_terminal_lookup(query)
    if source_switch_ip:
        source_switch_ip = normalize_ip(source_switch_ip, '源交换机 IP')
    if query_type == 'ip':
        rows = db.get_bindings_by_ip(value, source_switch_ip)
        if not rows:
            raise ValueError('已绑定终端列表中未找到该终端的绑定记录')
        macs = sorted({normalize_mac(row.get('mac_address', '')) for row in rows})
        if len(macs) > 1:
            details = '; '.join(
                f"{row.get('mac_address')} @ {row.get('switch_ip')} {row.get('port')}"
                for row in rows[:8]
            )
            raise ValueError(
                f"同一 IP {value} 在已绑定终端列表中存在 {len(macs)} 个不同 MAC，不能按 IP 自动迁移。"
                f"请改用明确的 MAC 地址定位，或先清理冲突绑定：{details}"
            )
        binding = rows[0]
    elif query_type == 'mac' and source_switch_ip:
        binding = db.get_mac_binding_on_switch(value, source_switch_ip)
    else:
        binding = db.get_mac_binding(value)
    if not binding:
        raise ValueError('已绑定终端列表中未找到该终端的绑定记录')
    return binding


def assert_no_ip_conflict(ip_address, selected_mac):
    rows = db.get_bindings_by_ip(ip_address)
    conflicts = [
        row for row in rows
        if normalize_mac(row.get('mac_address', '')) != normalize_mac(selected_mac)
    ]
    if conflicts:
        details = '; '.join(
            f"{row.get('mac_address')} @ {row.get('switch_ip')} {row.get('port')}"
            for row in conflicts[:8]
        )
        raise ValueError(
            f"检测到同一 IP {ip_address} 还绑定到其他 MAC，已拒绝迁移以避免残留冲突。"
            f"请先确认并删除冲突绑定，或改用正确 MAC 重新定位。冲突记录：{details}"
        )


def port_has_binding(mgr, interface_name, ip_address, mac_address):
    info, _ = mgr.get_port_info(interface_name)
    target_ip = normalize_ip(ip_address, '绑定 IP')
    target_mac = normalize_mac(mac_address, '绑定 MAC')
    for binding in info.get('bindings', []):
        try:
            if (
                normalize_ip(binding.get('ip'), '绑定 IP') == target_ip
                and normalize_mac(binding.get('mac'), '绑定 MAC') == target_mac
            ):
                return True
        except ValueError:
            continue
    return False


def binding_matches_query(binding, query_type, value):
    if query_type == 'ip':
        return binding.get('ip_address') == value
    return normalize_mac(binding.get('mac_address', '')) == value


def save_binding_state(switch_ip, interface_name, vlan, bind_ip, mac, mode):
    return db.upsert_mac_binding(
        mac_address=normalize_mac(mac),
        ip_address=normalize_ip(bind_ip, '绑定 IP'),
        switch_ip=normalize_ip(switch_ip, '交换机 IP'),
        port=str(interface_name).strip(),
        vlan=str(vlan or '').strip(),
        mode=normalize_mode(mode),
    )


def persist_switch_bindings(switch_row, all_bindings, query_type=None, query_value=None):
    changed = 0
    found = 0
    created = 0
    updated = 0
    unchanged = 0
    matched = None
    errors = []

    for binding in all_bindings or []:
        try:
            interface_name = binding.get('switch_port') or binding.get('port')
            bind_ip = binding.get('ip')
            mac = binding.get('mac')
            if not interface_name or not bind_ip or not mac or bind_ip == 'Unknown' or mac == 'Unknown':
                continue
            mode = normalize_mode(binding.get('mode', 'access'))
            vlan = str(binding.get('vlan') or '').strip()
            action = save_binding_state(switch_row['ip'], interface_name, vlan, bind_ip, mac, mode)
            found += 1
            if action == 'created':
                created += 1
                changed += 1
            elif action == 'updated':
                updated += 1
                changed += 1
            else:
                unchanged += 1
            saved = {
                'mac_address': normalize_mac(mac),
                'ip_address': normalize_ip(bind_ip, '绑定 IP'),
                'switch_ip': switch_row['ip'],
                'port': interface_name,
                'vlan': vlan,
                'mode': mode,
            }
            if query_type and binding_matches_query(saved, query_type, query_value):
                matched = saved
        except Exception as exc:
            errors.append(f"binding: {exc}")

    return {
        'synced': changed,
        'found': found,
        'created': created,
        'updated': updated,
        'unchanged': unchanged,
        'matched': matched,
        'errors': errors,
    }


def sync_switch_bindings(switch_row, query_type=None, query_value=None):
    runtime = {
        'ip': switch_row['ip'],
        'user': switch_row['username'],
        'pass': switch_row['password'],
        'port': switch_row.get('port', 22),
        'vendor': switch_row.get('vendor', 'h3c'),
    }
    mgr = get_manager(runtime)
    return persist_switch_bindings(
        switch_row,
        mgr.get_all_bindings(),
        query_type,
        query_value,
    )


def sync_all_switch_bindings(query_type=None, query_value=None):
    total_synced = 0
    scanned_switches = 0
    matched = None
    errors = []

    for sw in db.get_terminal_sync_switches():
        scanned_switches += 1
        try:
            result = sync_switch_bindings_with_timeout(sw, query_type, query_value)
            total_synced += result['synced']
            errors.extend([f"{sw['ip']} {err}" for err in result['errors'][:5]])
            if result['matched'] and not matched:
                matched = result['matched']
                break
        except Exception as exc:
            errors.append(f"{sw.get('ip', 'Unknown')}: {exc}")

    return {
        'scanned_switches': scanned_switches,
        'synced': total_synced,
        'matched': matched,
        'errors': errors,
    }


def scan_one_switch_for_terminal(source_switch_ip, query):
    source_switch_ip = normalize_ip(source_switch_ip, '源交换机 IP')
    sw = db.get_switch_by_ip(source_switch_ip)
    if not sw:
        raise ValueError(f"资产管理库未登记该源交换机 IP（{source_switch_ip}）")
    query_type, query_value = normalize_terminal_lookup(query)
    result = sync_switch_bindings_with_timeout(sw, query_type, query_value)
    return {
        'scanned_switches': 1,
        'synced': result['synced'],
        'matched': result['matched'],
        'errors': [f"{source_switch_ip} {err}" for err in result.get('errors', [])],
    }


def read_switch_bindings_with_timeout(sw, timeout=None):
    timeout = timeout or get_mac_sync_timeout()
    worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mac_sync_worker.py')
    payload = {
        'switch': {
            'ip': sw.get('ip'),
            'username': sw.get('username') or '',
            'password': sw.get('password') or '',
            'port': sw.get('port') or 22,
            'vendor': sw.get('vendor') or 'h3c',
        }
    }
    try:
        completed = subprocess.run(
            [sys.executable, worker_path],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    except subprocess.TimeoutExpired:
        return {
            'bindings': [],
            'errors': [f"设备扫描超过 {timeout} 秒，已终止子进程并跳过"],
        }

    stdout_lines = [line.strip() for line in (completed.stdout or '').splitlines() if line.strip()]
    data = None
    if stdout_lines:
        try:
            data = json.loads(stdout_lines[-1])
        except json.JSONDecodeError:
            data = None

    if completed.returncode != 0 or not data:
        detail = ''
        if data and data.get('error'):
            detail = data['error']
        else:
            detail = (completed.stderr or completed.stdout or '子进程无有效输出').strip()
        return {'bindings': [], 'errors': [detail[:500]]}

    if data.get('status') != 'success':
        return {'bindings': [], 'errors': [str(data.get('error') or '设备读取失败')]}

    return {'bindings': data.get('bindings') or [], 'errors': []}


def sync_switch_bindings_with_timeout(sw, query_type=None, query_value=None, timeout=None):
    timeout = timeout or get_mac_sync_timeout()
    read_result = read_switch_bindings_with_timeout(sw, timeout)
    if read_result.get('errors'):
        return {'synced': 0, 'matched': None, 'errors': read_result['errors']}
    return persist_switch_bindings(sw, read_result.get('bindings') or [], query_type, query_value)


def update_mac_sync_state(**kwargs):
    with MAC_SYNC_STATE_LOCK:
        MAC_SYNC_STATE.update(kwargs)
        return dict(MAC_SYNC_STATE)


def get_mac_sync_state_snapshot():
    with MAC_SYNC_STATE_LOCK:
        state = dict(MAC_SYNC_STATE)
        state['errors'] = list(MAC_SYNC_STATE.get('errors', []))[-20:]
        return state


def log_mac_sync_switch_result(actor, client_ip, sw, result=None, error=None):
    switch_ip = sw.get('ip', 'Unknown')
    switch_name = sw.get('name') or switch_ip
    vendor = sw.get('vendor') or 'unknown'
    if error:
        db.log_operation(
            actor,
            client_ip,
            switch_ip,
            "终端更新（单台设备）",
            f"{switch_name} | 厂商:{vendor} | 失败原因:{error}",
            "失败",
        )
        return

    errors = result.get('errors') or []
    synced = int(result.get('synced') or 0)
    found = int(result.get('found') or 0)
    created = int(result.get('created') or 0)
    updated = int(result.get('updated') or 0)
    unchanged = int(result.get('unchanged') or 0)
    if errors:
        db.log_operation(
            actor,
            client_ip,
            switch_ip,
            "终端更新（单台设备）",
            f"{switch_name} | 厂商:{vendor} | 发现:{found} | 新增:{created} | 更新:{updated} | 未变:{unchanged} | 失败原因:{'; '.join(errors[:3])}",
            "失败",
        )
        return

    status = "成功" if found else "无绑定"
    db.log_operation(
        actor,
        client_ip,
        switch_ip,
        "终端更新（单台设备）",
        f"{switch_name} | 厂商:{vendor} | 发现:{found} | 新增:{created} | 更新:{updated} | 未变:{unchanged}",
        status,
    )


def run_mac_bindings_sync(actor, client_ip, switch_ip=''):
    if not MAC_SYNC_LOCK.acquire(blocking=False):
        return {
            'status': 'busy',
            'msg': '终端绑定信息正在同步中，请稍后再试。',
            'data': {'scanned_switches': 0, 'synced': 0, 'errors': []},
        }

    try:
        started_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        update_mac_sync_state(
            running=True,
            status='running',
            message='正在同步终端绑定信息',
            started_at=started_at,
            finished_at='',
            actor=actor,
            current_switch_index=0,
            total_switches=0,
            current_switch_ip='',
            current_switch_name='',
            synced=0,
            found=0,
            created=0,
            updated=0,
            unchanged=0,
            errors=[],
        )

        all_errors = []
        total_synced = 0
        total_found = 0
        total_created = 0
        total_updated = 0
        total_unchanged = 0

        if switch_ip:
            switch_ip = normalize_ip(switch_ip, '交换机 IP')
            sw = db.get_switch_by_ip(switch_ip)
            if not sw:
                raise ValueError(f"资产管理库未登记该 IP（{switch_ip}）")
            update_mac_sync_state(
                current_switch_index=1,
                total_switches=1,
                current_switch_ip=sw['ip'],
                current_switch_name=sw.get('name', ''),
                message=f"正在扫描 {sw.get('name') or sw['ip']} ({sw['ip']})",
            )
            result = sync_switch_bindings_with_timeout(sw)
            log_mac_sync_switch_result(actor, client_ip, sw, result=result)
            total_synced += result['synced']
            total_found += result.get('found', 0)
            total_created += result.get('created', 0)
            total_updated += result.get('updated', 0)
            total_unchanged += result.get('unchanged', 0)
            all_errors.extend([f"{sw['ip']} {err}" for err in result['errors'][:5]])
            scanned_switches = 1
            device_scope = switch_ip
            update_mac_sync_state(
                synced=total_synced,
                found=total_found,
                created=total_created,
                updated=total_updated,
                unchanged=total_unchanged,
                errors=all_errors,
            )
        else:
            device_scope = 'ALL_SWITCHES'
            switches = db.get_terminal_sync_switches()
            scanned_switches = 0
            max_workers = get_mac_sync_max_workers()
            update_mac_sync_state(
                total_switches=len(switches),
                message=f"正在并发扫描终端绑定信息，最大并发 {max_workers} 台",
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(read_switch_bindings_with_timeout, sw): sw
                    for sw in switches
                }
                for future in as_completed(future_map):
                    sw = future_map[future]
                    scanned_switches += 1
                    update_mac_sync_state(
                        current_switch_index=scanned_switches,
                        total_switches=len(switches),
                        current_switch_ip=sw.get('ip', ''),
                        current_switch_name=sw.get('name', ''),
                        synced=total_synced,
                        found=total_found,
                        created=total_created,
                        updated=total_updated,
                        unchanged=total_unchanged,
                        errors=all_errors,
                        message=f"已完成 {scanned_switches}/{len(switches)} 台，正在汇总 {sw.get('name') or sw.get('ip')} ({sw.get('ip')})",
                    )
                    try:
                        read_result = future.result()
                        if read_result.get('errors'):
                            result = {
                                'synced': 0,
                                'found': 0,
                                'created': 0,
                                'updated': 0,
                                'unchanged': 0,
                                'matched': None,
                                'errors': read_result['errors'],
                            }
                        else:
                            result = persist_switch_bindings(sw, read_result.get('bindings') or [])
                        log_mac_sync_switch_result(actor, client_ip, sw, result=result)
                        total_synced += result['synced']
                        total_found += result.get('found', 0)
                        total_created += result.get('created', 0)
                        total_updated += result.get('updated', 0)
                        total_unchanged += result.get('unchanged', 0)
                        all_errors.extend([f"{sw['ip']} {err}" for err in result['errors'][:5]])
                    except Exception as exc:
                        log_mac_sync_switch_result(actor, client_ip, sw, error=str(exc))
                        all_errors.append(f"{sw.get('ip', 'Unknown')}: {exc}")
                    update_mac_sync_state(
                        synced=total_synced,
                        found=total_found,
                        created=total_created,
                        updated=total_updated,
                        unchanged=total_unchanged,
                        errors=all_errors,
                    )

        status = "成功" if not all_errors else "部分失败"
        db.log_operation(
            actor,
            client_ip,
            device_scope,
            "终端更新（汇总）",
            (
                f"扫描交换机:{scanned_switches} | 发现绑定:{total_found} | "
                f"新增:{total_created} | 更新:{total_updated} | 未变:{total_unchanged} | 错误:{len(all_errors)}"
            ),
            status,
        )
        finished_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        update_mac_sync_state(
            running=False,
            status='success' if not all_errors else 'partial',
            message=(
                f"同步完成：扫描 {scanned_switches} 台交换机，发现 {total_found} 条绑定，"
                f"新增 {total_created} 条，更新 {total_updated} 条，未变 {total_unchanged} 条。"
            ),
            finished_at=finished_at,
            current_switch_index=scanned_switches,
            synced=total_synced,
            found=total_found,
            created=total_created,
            updated=total_updated,
            unchanged=total_unchanged,
            errors=all_errors,
        )
        return {
            'status': 'success',
            'msg': (
                f"同步完成：扫描 {scanned_switches} 台交换机，发现 {total_found} 条绑定，"
                f"新增 {total_created} 条，更新 {total_updated} 条，未变 {total_unchanged} 条。"
            ),
            'data': {
                'scanned_switches': scanned_switches,
                'synced': total_synced,
                'found': total_found,
                'created': total_created,
                'updated': total_updated,
                'unchanged': total_unchanged,
                'errors': all_errors[:20],
            },
        }
    except Exception as exc:
        finished_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        update_mac_sync_state(
            running=False,
            status='error',
            message=f"同步失败：{exc}",
            finished_at=finished_at,
        )
        raise
    finally:
        MAC_SYNC_LOCK.release()


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
        role = normalize_switch_role(data.get('role'))
        if db.get_switch_by_ip(data['ip']):
            return jsonify({'status': 'error', 'msg': f"添加失败：IP 地址 {data['ip']} 已存在，请勿重复录入！"})

        db.add_switch(data['name'], data['ip'], data['port'], data['user'], data['pass'], vendor, role)
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


@app.route('/api/switches/update', methods=['POST'])
@login_required
def update_switch_api():
    try:
        data = get_json_data()
        require_fields(data, ['id', 'name', 'ip', 'port', 'user'])
        switch_id = int(data['id'])
        name = str(data['name']).strip()
        if not name:
            return json_error('设备名称不能为空')
        ip = normalize_ip(data['ip'])
        port = normalize_port(data['port'])
        username = str(data.get('user') or '').strip()
        password = str(data.get('pass') or '').strip()
        vendor = normalize_vendor(data.get('vendor'))
        role = normalize_switch_role(data.get('role'))

        before = db.get_switch_by_id(switch_id)
        if not before:
            return json_error('设备不存在或已被删除')

        same_ip_switch = db.get_switch_by_ip(ip)
        if same_ip_switch and int(same_ip_switch['id']) != switch_id:
            return json_error(f"修改失败：IP 地址 {ip} 已被其他设备使用")

        updated = db.update_switch(switch_id, name, ip, port, username, password, vendor, role)
        if not updated:
            return json_error('设备不存在或已被删除')

        db.log_operation(
            current_user.username,
            request.remote_addr,
            ip,
            "修改设备资产",
            f"id={switch_id}, {before['ip']} -> {ip}, name={before['name']} -> {name}, vendor={vendor}, role={role}",
            "成功",
        )
        return jsonify({'status': 'success'})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('修改设备失败，请检查输入或稍后重试', e)


@app.route('/api/switches/update_metadata', methods=['POST'])
@login_required
def update_switch_metadata_api():
    try:
        data = get_json_data()
        require_fields(data, ['id'])
        switch_id = int(data['id'])
        role = normalize_switch_role(data.get('role')) if 'role' in data else None
        db.update_switch_metadata(switch_id, role)
        db.log_operation(
            current_user.username,
            request.remote_addr,
            str(switch_id),
            "更新设备资产属性",
            f"role={role if role is not None else '-'}",
            "成功",
        )
        return jsonify({'status': 'success'})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('更新设备资产属性失败，请稍后重试', e)

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


@app.route('/api/backup_files', methods=['GET'])
@login_required
def api_backup_files():
    try:
        limit = int(request.args.get('limit', 500))
        limit = max(1, min(limit, 2000))
        return jsonify({'status': 'success', 'data': list_backup_config_files(limit=limit)})
    except Exception as e:
        return internal_error('获取备份文件列表失败，请稍后重试', e)


@app.route('/api/backup_diff', methods=['POST'])
@login_required
def api_backup_diff():
    try:
        data = get_json_data()
        require_fields(data, ['old_path', 'new_path'])
        old_path = str(data['old_path']).strip()
        new_path = str(data['new_path']).strip()
        old_lines = read_backup_text(old_path)
        new_lines = read_backup_text(new_path)
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=old_path,
                tofile=new_path,
                lineterm='',
                n=3,
            )
        )
        additions = sum(1 for line in diff_lines if line.startswith('+') and not line.startswith('+++'))
        deletions = sum(1 for line in diff_lines if line.startswith('-') and not line.startswith('---'))
        return jsonify(
            {
                'status': 'success',
                'data': {
                    'old_path': old_path,
                    'new_path': new_path,
                    'additions': additions,
                    'deletions': deletions,
                    'changed': bool(additions or deletions),
                    'diff': '\n'.join(diff_lines),
                },
            }
        )
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('配置差异比对失败，请检查备份文件', e)


@app.route('/api/task_center', methods=['GET'])
@login_required
def api_task_center():
    try:
        limit = int(request.args.get('limit', 300))
        limit = max(1, min(limit, 1000))
        logs = db.get_task_logs(limit=limit)
        task_name_map = {
            '同步终端绑定状态库': '终端更新（汇总）',
            '同步终端绑定信息': '终端更新（汇总）',
            '同步终端绑定状态库-单台': '终端更新（单台设备）',
            '同步终端绑定信息-单台': '终端更新（单台设备）',
        }
        summary = {}
        for row in logs:
            action = task_name_map.get(row.get('action'), row.get('action') or '未知')
            row['display_action'] = action
            status = row.get('status') or '未知'
            item = summary.setdefault(action, {'total': 0, 'success': 0, 'failed': 0, 'partial': 0})
            item['total'] += 1
            if status == '成功':
                item['success'] += 1
            elif '失败' in status:
                item['failed'] += 1
            else:
                item['partial'] += 1
        return jsonify({'status': 'success', 'data': {'logs': logs, 'summary': summary}})
    except Exception as e:
        return internal_error('获取任务中心数据失败，请稍后重试', e)


@app.route('/api/port_profiles', methods=['GET'])
@login_required
def api_port_profiles():
    try:
        rows = db.get_port_profiles()
        return jsonify({'status': 'success', 'data': rows})
    except Exception as e:
        return internal_error('获取端口画像失败，请稍后重试', e)


@app.route('/api/health_check', methods=['GET'])
@login_required
def api_health_check():
    try:
        switches = db.get_all_switches()
        bindings = db.get_mac_bindings(limit=100000)
        backup_files = list_backup_config_files(limit=2000)
        settings = db.get_system_settings()
        backup_dates = sorted({item['date'] for item in backup_files if item.get('date')}, reverse=True)
        access_ips = {sw['ip'] for sw in switches if (sw.get('role') or 'access') == 'access'}
        binding_switch_ips = {row['switch_ip'] for row in bindings}
        access_without_bindings = [
            sw for sw in switches
            if (sw.get('role') or 'access') == 'access' and sw['ip'] not in binding_switch_ips
        ]
        now = datetime.datetime.now()
        stale_bindings = []
        for row in bindings:
            try:
                updated = datetime.datetime.strptime(row.get('update_time', ''), '%Y-%m-%d %H:%M:%S')
                if (now - updated).days >= 3:
                    stale_bindings.append(row)
            except Exception:
                pass
        checks = [
            {'name': '设备资产', 'status': 'success' if switches else 'warning', 'detail': f"已登记 {len(switches)} 台设备"},
            {'name': '终端绑定', 'status': 'success' if bindings else 'warning', 'detail': f"已绑定终端 {len(bindings)} 条"},
            {'name': '备份文件', 'status': 'success' if backup_files else 'warning', 'detail': f"备份文件 {len(backup_files)} 个，最近日期 {backup_dates[0] if backup_dates else '-'}"},
            {'name': '接入设备覆盖', 'status': 'success' if not access_without_bindings else 'warning', 'detail': f"{len(access_without_bindings)} 台接入交换机暂无终端绑定记录"},
            {'name': '绑定新鲜度', 'status': 'success' if not stale_bindings else 'warning', 'detail': f"{len(stale_bindings)} 条绑定超过 3 天未确认"},
            {'name': '终端更新参数', 'status': 'success', 'detail': f"并发 {settings['mac_sync_max_workers']}，单台超时 {settings['mac_sync_timeout']} 秒"},
        ]
        return jsonify(
            {
                'status': 'success',
                'data': {
                    'checks': checks,
                    'access_without_bindings': access_without_bindings[:50],
                    'stale_bindings': stale_bindings[:50],
                    'settings': settings,
                },
            }
        )
    except Exception as e:
        return internal_error('运行健康检查失败，请稍后重试', e)


@app.route('/api/data_export', methods=['GET'])
@login_required
def api_data_export():
    try:
        memory_file, filename = create_data_package()
        return send_file(memory_file, as_attachment=True, download_name=filename, mimetype='application/zip')
    except Exception as e:
        return internal_error('导出数据包失败，请稍后重试', e)


@app.route('/api/data_import', methods=['POST'])
@login_required
def api_data_import():
    try:
        upload = request.files.get('file')
        if not upload or not upload.filename:
            return json_error('请选择要导入的数据包')
        backup_dir = restore_data_package(upload)
        return jsonify(
            {
                'status': 'success',
                'msg': '数据包已导入。当前服务仍可能保留旧状态，建议立即重启 run_server.py 后再继续操作。',
                'data': {'backup_dir': backup_dir},
            }
        )
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('导入数据包失败，请检查 zip 文件', e)


@app.route('/api/data_import_preview', methods=['POST'])
@login_required
def api_data_import_preview():
    try:
        upload = request.files.get('file')
        if not upload or not upload.filename:
            return json_error('请选择要预览的数据包')
        return jsonify({'status': 'success', 'data': preview_data_package(upload)})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('预览数据包失败，请检查 zip 文件', e)


@app.route('/api/offline_binding_import', methods=['POST'])
@login_required
def api_offline_binding_import():
    try:
        data = get_json_data()
        apply_import = bool(data.get('apply'))
        result = import_bindings_from_backup_files(limit=int(data.get('limit') or 2000), apply=apply_import)
        db.log_operation(
            current_user.username,
            request.remote_addr,
            "BACKUPS",
            "离线导入绑定库",
            f"apply={apply_import} | files={result['files']} | found={result['found']} | unique={result['unique_terminals']} | duplicates={result['duplicates']} | created={result['created']} | updated={result['updated']} | unchanged={result['unchanged']} | errors={len(result['errors'])}",
            "成功" if not result['errors'] else "部分失败",
        )
        return jsonify({'status': 'success', 'data': result})
    except Exception as e:
        return internal_error('离线导入绑定库失败，请检查备份配置', e)


@app.route('/api/deep_health_check', methods=['POST'])
@login_required
def api_deep_health_check():
    try:
        data = get_json_data()
        limit = max(1, min(int(data.get('limit') or 10), 50))
        switches = db.get_all_switches()[:limit]
        results = []
        for sw in switches:
            item = {'ip': sw['ip'], 'name': sw.get('name', ''), 'vendor': sw.get('vendor', 'h3c'), 'status': 'unknown', 'detail': ''}
            try:
                mgr = get_manager({'ip': sw['ip'], 'user': sw['username'], 'pass': sw['password'], 'port': sw['port'], 'vendor': sw.get('vendor', 'h3c')})
                info = mgr.get_device_info()
                item['status'] = 'success'
                item['detail'] = info
            except Exception as exc:
                msg = str(exc)
                item['status'] = 'failed'
                if 'Authentication' in msg:
                    item['detail'] = '认证失败'
                elif 'timed out' in msg.lower() or 'timeout' in msg.lower():
                    item['detail'] = '连接超时'
                else:
                    item['detail'] = msg[:300]
            results.append(item)
        return jsonify({'status': 'success', 'data': {'checked': len(results), 'results': results}})
    except Exception as e:
        return internal_error('深度在线健康检查失败', e)


@app.route('/api/switch_alarm_logs', methods=['POST'])
@login_required
def api_switch_alarm_logs():
    try:
        data = get_json_data()
        switch_ip = normalize_ip(data.get('switch_ip') or data.get('ip'), '交换机 IP')
        result = collect_switch_alarm_report(switch_ip)
        raw = result['raw']
        analysis = result['analysis']
        db.log_operation(current_user.username, request.remote_addr, switch_ip, "采集交换机日志告警", f"critical={analysis['critical']} warning={analysis['warning']}", "成功")
        return jsonify({'status': 'success', 'data': {'raw': raw[-20000:], 'analysis': analysis}})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('采集交换机日志失败，请检查设备状态', e)


@app.route('/api/switch_alarm_reports', methods=['GET'])
@login_required
def api_switch_alarm_reports():
    try:
        limit = int(request.args.get('limit') or 200)
        limit = max(1, min(limit, 1000))
        return jsonify({'status': 'success', 'data': db.get_switch_alarm_reports(limit)})
    except Exception as e:
        return internal_error('读取交换机日志分析报告失败', e)


@app.route('/api/alarm_dashboard', methods=['GET'])
@login_required
def api_alarm_dashboard():
    try:
        reports = db.get_latest_switch_alarm_reports()
        states = db.get_alarm_states()
        trends = db.get_alarm_trends(7)
        risk_rank = {'high': 4, 'medium': 3, 'low': 2, 'normal': 1}
        summary = {'total': len(reports), 'high': 0, 'medium': 0, 'low': 0, 'normal': 0, 'failed': 0, 'ack': 0, 'ignored': 0}
        devices = []
        for item in reports:
            state = states.get(item.get('switch_ip')) or {}
            item['alarm_state'] = state.get('state') or 'open'
            item['alarm_note'] = state.get('note') or ''
            item['ignore_until'] = state.get('ignore_until') or ''
            item['state_updated_by'] = state.get('updated_by') or ''
            item['state_update_time'] = state.get('update_time') or ''
            if item['alarm_state'] == 'ack':
                summary['ack'] += 1
            elif item['alarm_state'] == 'ignored':
                summary['ignored'] += 1
            if item.get('status') != '成功':
                risk_level = 'failed'
                priority = 500
                summary['failed'] += 1
            else:
                risk_level = item.get('risk_level') or 'normal'
                summary[risk_level] = summary.get(risk_level, 0) + 1
                priority = (
                    risk_rank.get(risk_level, 0) * 1000
                    + int(item.get('risk_score') or 0) * 5
                    + int(item.get('critical_count') or 0) * 30
                    + int(item.get('warning_count') or 0)
                )
            item['dashboard_risk'] = risk_level
            if item['alarm_state'] == 'ack':
                priority -= 300
            elif item['alarm_state'] == 'ignored':
                priority -= 600
            item['priority_score'] = priority
            item['commands'] = build_alarm_command_suggestions(item.get('category_counts') or {})
            devices.append(item)
        devices.sort(key=lambda row: (row.get('priority_score') or 0, row.get('timestamp') or ''), reverse=True)
        top_devices = [row for row in devices if row.get('alarm_state') == 'open'][:10]
        return jsonify(
            {
                'status': 'success',
                'data': {
                    'summary': summary,
                    'trends': trends,
                    'devices': devices,
                    'top_devices': top_devices,
                    'sort_rule': '采集失败/高风险优先，其次风险分、严重数、告警数、最新时间。Top 10 只是默认优先处理列表，完整设备仍在下方可筛选查看。',
                },
            }
        )
    except Exception as e:
        return internal_error('读取告警中心数据失败', e)


@app.route('/api/alarm_state/update', methods=['POST'])
@login_required
def api_alarm_state_update():
    try:
        data = get_json_data()
        switch_ip = normalize_ip(data.get('switch_ip'), '交换机 IP')
        state = str(data.get('state') or 'open').strip()
        if state not in {'open', 'ack', 'ignored'}:
            raise ValueError('告警状态必须是 open、ack 或 ignored')
        note = str(data.get('note') or '').strip()
        ignore_until = str(data.get('ignore_until') or '').strip()
        db.update_alarm_state(switch_ip, state, note, ignore_until, current_user.username)
        db.log_operation(current_user.username, request.remote_addr, switch_ip, "更新告警状态", f"state={state} note={note[:100]}", "成功")
        return jsonify({'status': 'success'})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('更新告警状态失败', e)


@app.route('/api/version', methods=['GET'])
@login_required
def api_version():
    data = dict(APP_VERSION_INFO)
    data['settings'] = db.get_system_settings()
    return jsonify({'status': 'success', 'data': data})


@app.route('/api/settings', methods=['GET'])
@login_required
def api_settings():
    return jsonify({'status': 'success', 'data': db.get_system_settings()})


@app.route('/api/settings/update', methods=['POST'])
@login_required
def update_settings_api():
    try:
        data = get_json_data()
        if 'auto_save_after_backup' in data:
            enabled = bool(data.get('auto_save_after_backup'))
            db.set_setting('auto_save_after_backup', '1' if enabled else '0')
            db.log_operation(
                current_user.username,
                request.remote_addr,
                "SYSTEM",
                "更新系统设置",
                f"auto_save_after_backup={1 if enabled else 0}",
                "成功",
            )
        if 'mac_sync_timeout' in data:
            timeout = int(data.get('mac_sync_timeout'))
            if timeout < 10 or timeout > 600:
                raise ValueError('单台终端更新时间必须在 10-600 秒之间')
            db.set_setting('mac_sync_timeout', str(timeout))
        if 'mac_sync_max_workers' in data:
            max_workers = int(data.get('mac_sync_max_workers'))
            if max_workers < 1 or max_workers > 16:
                raise ValueError('终端更新并发数必须在 1-16 之间')
            db.set_setting('mac_sync_max_workers', str(max_workers))
        if 'protected_keywords' in data:
            keywords = str(data.get('protected_keywords') or '').strip()
            if not keywords:
                raise ValueError('保护关键词不能为空')
            db.set_setting('protected_keywords', keywords)
        for key in ['auto_backup_hour', 'auto_sync_hour', 'auto_data_export_hour', 'auto_alarm_collect_hour']:
            if key in data:
                value = int(data.get(key))
                if value < 0 or value > 23:
                    raise ValueError(f'{key} 必须在 0-23 之间')
                db.set_setting(key, str(value))
        for key in ['auto_backup_minute', 'auto_sync_minute', 'auto_data_export_minute', 'auto_alarm_collect_minute']:
            if key in data:
                value = int(data.get(key))
                if value < 0 or value > 59:
                    raise ValueError(f'{key} 必须在 0-59 之间')
                db.set_setting(key, str(value))
        if 'auto_data_export_enabled' in data:
            db.set_setting('auto_data_export_enabled', '1' if bool(data.get('auto_data_export_enabled')) else '0')
        if 'auto_alarm_collect_enabled' in data:
            db.set_setting('auto_alarm_collect_enabled', '1' if bool(data.get('auto_alarm_collect_enabled')) else '0')
        if 'auto_data_export_dir' in data:
            export_dir = str(data.get('auto_data_export_dir') or 'data_packages').strip()
            if not export_dir:
                raise ValueError('自动数据包导出目录不能为空')
            db.set_setting('auto_data_export_dir', export_dir)
        if any(key.startswith('auto_') for key in data.keys()):
            configure_scheduler()
        return jsonify({'status': 'success', 'data': db.get_system_settings()})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('更新系统设置失败，请稍后重试', e)


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


@app.route('/set_interface_description', methods=['POST'])
@login_required
def set_interface_description():
    try:
        data = get_json_data()
        require_fields(data, ['ip', 'user', 'pass', 'interface'])
        client_ip = request.remote_addr
        data['ip'] = normalize_ip(data['ip'])
        if 'port' in data:
            data['port'] = normalize_port(data['port'])
        if 'vendor' in data:
            data['vendor'] = normalize_vendor(data['vendor'])
        description = str(data.get('description', '')).strip()
        if '\n' in description or '\r' in description:
            raise ValueError('端口描述不能包含换行符')
        if len(description) > 120:
            raise ValueError('端口描述不能超过 120 个字符')

        mgr = get_manager(data)
        log = mgr.set_interface_description(data['interface'], description)
        details = f"端口:{data['interface']} | 描述:{description or '(清空)'}"
        db.log_operation(current_user.username, client_ip, data['ip'], "设置端口描述", details, "成功")
        return jsonify({'status': 'success', 'log': format_switch_log(log).replace('\n', '<br>')})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        if 'data' in locals():
            db.log_operation(
                current_user.username,
                locals().get('client_ip', request.remote_addr),
                data.get('ip', 'Unknown'),
                "设置端口描述",
                f"端口:{data.get('interface', '')} | 报错:{str(e)}",
                "失败",
            )
        return internal_error('设置端口描述失败，请检查设备状态和参数', e)

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
        mode = normalize_mode(d.get('mode', 'access'))
        d['mode'] = mode
        d['vlan'] = normalize_vlan(d.get('vlan'))
        device_ip = d.get('ip', 'Unknown')
        details = f"端口:{d.get('interface')} | IP:{d.get('bind_ip')} | MAC:{d.get('mac')} | 模式:{mode} | VLAN:{d.get('vlan')}"
        mgr = get_manager(d)

        assert_interface_not_protected(mgr, d['interface'])

        log = mgr.configure_port_binding(d['interface'], d['vlan'], d['bind_ip'], d['mac'], mode)
        save_binding_state(d['ip'], d['interface'], d['vlan'], d['bind_ip'], d['mac'], mode)
        db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", details, "成功")
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except ValueError as e:
        if 'details' in locals():
            db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", f"{details} | 报错: {str(e)}", "失败")
        return json_error(str(e))
    except Exception as e:
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
        mode = normalize_mode(d.get('mode', 'access'))
        d['mode'] = mode
        vlan = normalize_vlan(d.get('vlan'), allow_empty=True)
        d['vlan'] = vlan
        device_ip = d.get('ip', 'Unknown')
        details = f"端口:{d.get('interface')} | IP:{d.get('del_ip')} | MAC:{d.get('del_mac')} | 模式:{mode} | VLAN:{vlan}"
        mgr = get_manager(d)

        assert_interface_not_protected(mgr, d['interface'])

        log = mgr.delete_port_binding(d['interface'], d['del_ip'], d['del_mac'], mode, vlan)
        db.delete_mac_binding(d['del_mac'])
        db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", details, "成功")
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except ValueError as e:
        if 'details' in locals():
            db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", f"{details} | 报错: {str(e)}", "失败")
        return json_error(str(e))
    except Exception as e:
        db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", f"{details} | 报错: {str(e)}", "失败")
        return internal_error('解除绑定失败，请检查设备状态和参数', e)


@app.route('/api/terminal_binding_lookup', methods=['POST'])
@login_required
def terminal_binding_lookup():
    try:
        data = get_json_data()
        require_fields(data, ['query'])
        source_switch_ip = str(data.get('source_switch_ip', '')).strip()
        try:
            binding = get_terminal_binding_record(data['query'], source_switch_ip or None)
            return jsonify({'status': 'success', 'data': binding, 'source': 'local'})
        except ValueError:
            if MAC_SYNC_LOCK.locked():
                return jsonify(
                    {
                        'status': 'error',
                        'msg': '终端绑定信息正在后台同步，请同步完成后再定位终端。',
                        'sync': get_mac_sync_state_snapshot(),
                    }
                ), 409
            if source_switch_ip:
                sync_result = scan_one_switch_for_terminal(source_switch_ip, data['query'])
            else:
                query_type, query_value = normalize_terminal_lookup(data['query'])
                sync_result = sync_all_switch_bindings(query_type, query_value)
            if sync_result['matched']:
                return jsonify(
                    {
                        'status': 'success',
                        'data': sync_result['matched'],
                        'source': 'live_scan',
                        'sync': sync_result,
                    }
                )
            return jsonify(
                {
                    'status': 'error',
                    'msg': f"已绑定终端列表和主动扫描都未找到该终端。已扫描 {sync_result['scanned_switches']} 台交换机，同步 {sync_result['synced']} 条绑定。",
                    'sync': sync_result,
                }
            )
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('查询终端位置失败，请稍后重试', e)


@app.route('/api/sync_mac_bindings', methods=['POST'])
@login_required
def sync_mac_bindings():
    try:
        data = get_json_data()
        switch_ip = str(data.get('switch_ip', '')).strip()
        if MAC_SYNC_LOCK.locked():
            return jsonify({'status': 'busy', 'msg': '终端绑定信息正在同步中，请稍后再试。', 'data': get_mac_sync_state_snapshot()}), 409

        actor = current_user.username
        client_ip = request.remote_addr
        worker = threading.Thread(
            target=run_mac_bindings_sync,
            args=(actor, client_ip, switch_ip),
            daemon=True,
        )
        worker.start()
        return jsonify({'status': 'success', 'msg': '同步任务已在后台启动。', 'data': get_mac_sync_state_snapshot()})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('同步终端绑定信息失败，请检查设备连通性和资产凭据', e)


@app.route('/api/mac_sync_status', methods=['GET'])
@login_required
def mac_sync_status():
    return jsonify({'status': 'success', 'data': get_mac_sync_state_snapshot()})


@app.route('/api/mac_bindings', methods=['GET'])
@login_required
def api_mac_bindings():
    try:
        limit = request.args.get('limit', '500')
        limit = max(1, min(5000, int(limit)))
        rows = db.get_mac_bindings(limit=limit)
        return jsonify({'status': 'success', 'data': rows})
    except ValueError as e:
        return json_error(str(e))
    except Exception as e:
        return internal_error('读取已绑定终端列表失败，请稍后重试', e)


@app.route('/api/migrate_terminal', methods=['POST'])
@login_required
def migrate_terminal():
    try:
        data = get_json_data()
        require_fields(data, ['query', 'target_switch_ip', 'target_interface'])
        client_ip = request.remote_addr
        source_switch_ip_hint = str(data.get('source_switch_ip', '')).strip()
        binding = get_terminal_binding_record(data['query'], source_switch_ip_hint or None)
        target_switch_ip = normalize_ip(data['target_switch_ip'], '目标交换机 IP')
        target_interface = str(data['target_interface']).strip()
        if not target_interface:
            raise ValueError('目标端口不能为空')

        source_switch_ip = normalize_ip(binding['switch_ip'], '源交换机 IP')
        source_interface = str(binding['port']).strip()
        source_ip = normalize_ip(binding['ip_address'], '源绑定 IP')
        source_mac = normalize_mac(binding['mac_address'], '源绑定 MAC')
        assert_no_ip_conflict(source_ip, source_mac)
        source_mode = normalize_mode(binding.get('mode', 'access'))
        source_vlan = str(binding.get('vlan') or '').strip()
        target_mode = normalize_mode(data.get('target_mode') or source_mode)
        target_vlan = data.get('target_vlan')
        if str(target_vlan or '').strip():
            target_vlan = normalize_vlan(target_vlan)
        elif target_mode == 'access':
            target_vlan = normalize_vlan(source_vlan, allow_empty=False)
        else:
            target_vlan = normalize_vlan(source_vlan or data.get('target_vlan'), allow_empty=False)

        if source_switch_ip == target_switch_ip and source_interface == target_interface:
            raise ValueError('源端口与目标端口相同，无需执行迁移')

        source_runtime = get_switch_runtime_data(source_switch_ip)
        target_runtime = get_switch_runtime_data(target_switch_ip)

        source_details = f"{source_switch_ip} {source_interface} VLAN:{source_vlan or '-'} 模式:{source_mode}"
        target_details = f"{target_switch_ip} {target_interface} VLAN:{target_vlan or '-'} 模式:{target_mode}"

        if bool(data.get('dry_run')):
            plan_log = (
                "[终端迁移试运行]\n"
                "本次只生成计划，不登录交换机，不下发任何配置。\n\n"
                f"终端: IP {source_ip} / MAC {source_mac}\n"
                f"源位置: {source_details}\n"
                f"目标位置: {target_details}\n\n"
                "预计执行步骤:\n"
                f"1. 登录源交换机 {source_switch_ip}，检查源端口 {source_interface} 是否受保护。\n"
                f"2. 在源端口删除 {source_ip} / {source_mac} 绑定。\n"
                "3. 只读复核旧端口是否仍存在相同 IP+MAC 绑定。\n"
                f"4. 登录目标交换机 {target_switch_ip}，检查目标端口 {target_interface} 是否受保护。\n"
                "5. 按目标端口现有配置差异化下发 VLAN、源绑定校验和 IP/MAC 绑定。\n"
                "6. 成功后更新已绑定终端列表。\n"
            )
            db.log_operation(
                current_user.username,
                client_ip,
                target_switch_ip,
                "终端迁移试运行",
                f"MAC:{source_mac} | IP:{source_ip} | 源:{source_details} -> 目标:{target_details}",
                "成功",
            )
            return jsonify(
                {
                    'status': 'success',
                    'msg': '终端迁移试运行完成，未下发配置',
                    'data': {
                        'source': binding,
                        'target': {
                            'switch_ip': target_switch_ip,
                            'port': target_interface,
                            'vlan': target_vlan,
                            'mode': target_mode,
                        },
                        'dry_run': True,
                    },
                    'log': plan_log.replace('\n', '<br>'),
                }
            )

        source_mgr = get_manager(source_runtime)
        target_mgr = get_manager(target_runtime)
        assert_interface_not_protected(source_mgr, source_interface)
        target_port_info = assert_interface_not_protected(target_mgr, target_interface)

        old_log = source_mgr.delete_port_binding(source_interface, source_ip, source_mac, source_mode, source_vlan)
        source_mgr_verify = get_manager(source_runtime)
        if port_has_binding(source_mgr_verify, source_interface, source_ip, source_mac):
            raise ValueError(
                f"旧端口解绑后复核失败：{source_switch_ip} {source_interface} 仍存在 "
                f"{source_ip} / {source_mac}，已停止迁移。请检查交换机返回信息或手动清理。"
            )
        rollback_needed = True
        try:
            new_log = target_mgr.configure_port_binding(
                target_interface,
                target_vlan,
                source_ip,
                source_mac,
                target_mode,
                current_config=target_port_info.get('_raw_config'),
            )
        except Exception:
            if rollback_needed:
                try:
                    source_mgr_rollback = get_manager(source_runtime)
                    source_mgr_rollback.configure_port_binding(source_interface, source_vlan, source_ip, source_mac, source_mode)
                except Exception:
                    pass
            raise

        save_binding_state(target_switch_ip, target_interface, target_vlan, source_ip, source_mac, target_mode)
        details = f"终端迁移 | MAC:{source_mac} | IP:{source_ip} | 源:{source_details} -> 目标:{target_details}"
        db.log_operation(current_user.username, client_ip, target_switch_ip, "终端迁移", details, "成功")

        combined_log = (
            "[旧端口清理]\n"
            f"{format_switch_log(old_log)}\n\n"
            "[新端口部署]\n"
            f"{format_switch_log(new_log)}"
        )
        return jsonify(
            {
                'status': 'success',
                'msg': '终端迁移完成',
                'data': {
                    'source': binding,
                    'target': {
                        'switch_ip': target_switch_ip,
                        'port': target_interface,
                        'vlan': target_vlan,
                        'mode': target_mode,
                    },
                },
                'log': combined_log.replace('\n', '<br>'),
            }
        )
    except ValueError as e:
        if 'client_ip' in locals():
            db.log_operation(
                current_user.username,
                client_ip,
                data.get('target_switch_ip', 'Unknown') if 'data' in locals() else 'Unknown',
                "终端迁移",
                f"查询:{data.get('query', '') if 'data' in locals() else ''} | 报错: {str(e)}",
                "失败",
            )
        return json_error(str(e))
    except Exception as e:
        if 'client_ip' in locals():
            db.log_operation(
                current_user.username,
                client_ip,
                data.get('target_switch_ip', 'Unknown') if 'data' in locals() else 'Unknown',
                "终端迁移",
                f"查询:{data.get('query', '') if 'data' in locals() else ''} | 报错: {str(e)}",
                "失败",
            )
        return internal_error('终端迁移失败，请检查设备状态和参数', e)

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
        query_all = bool(data.get('all'))
        if query_all:
            groups = mgr.get_acl_groups()
            return jsonify({'status': 'success', 'data': {'groups': groups}})
        acl_number = normalize_acl_number(data.get('acl_number', 4000))
        rules = mgr.get_acl_rules(acl_number)
        return jsonify({'status': 'success', 'data': {'groups': [{'number': acl_number, 'type': 'ACL', 'rules': rules}]}})
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
        acl_number = normalize_acl_number(d.get('acl_number', 4000))
        rid = d.get('rule_id')
        if rid == "":
            rid = None
        elif rid is not None:
            rid = str(int(str(rid).strip()))
        log = mgr.add_acl_mac(d['mac'], rid, acl_number)
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
        acl_number = normalize_acl_number(d.get('acl_number', 4000))
        log = mgr.delete_acl_rule(d['rule_id'], acl_number)
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
            mode = normalize_mode(row[col_indices['模式']], '模式列')
            
            data.append({
                'switch_ip': switch_ip,
                'interface': str(row[col_indices['端口']]).strip(),
                'vlan': normalize_vlan(row[col_indices['VLAN']], 'VLAN 列'),
                'bind_ip': bind_ip,
                'mac': mac,
                'mode': mode
            })
            
        return jsonify({'status': 'success', 'data': data})
        
    except Exception as e:
        return internal_error('解析 Excel 失败，请检查文件格式和内容', e)


@app.route('/api/execute_excel_group', methods=['POST'])
@login_required
def execute_excel_group():
    try:
        data = get_json_data()
        rows = data.get('rows')
        if not isinstance(rows, list) or not rows:
            raise ValueError('请求中必须包含 rows 数组，且不能为空')

        client_ip = request.remote_addr
        normalized_rows = []
        switch_ips = set()
        interfaces = set()
        modes = set()

        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('rows 中存在无效记录')
            require_fields(row, ['switch_ip', 'interface', 'vlan', 'bind_ip', 'mac', 'mode'])
            item = {
                'switch_ip': normalize_ip(row['switch_ip'], '交换机 IP'),
                'interface': str(row['interface']).strip(),
                'vlan': normalize_vlan(row['vlan']),
                'bind_ip': normalize_ip(row['bind_ip'], '绑定 IP'),
                'mac': normalize_mac(row['mac']),
                'mode': normalize_mode(row['mode']),
            }
            if not item['interface']:
                raise ValueError('端口不能为空')
            normalized_rows.append(item)
            switch_ips.add(item['switch_ip'])
            interfaces.add(item['interface'])
            modes.add(item['mode'])

        if len(switch_ips) != 1 or len(interfaces) != 1:
            raise ValueError('同一次批量下发只允许处理同一交换机的同一个端口')
        if len(modes) != 1:
            raise ValueError('同一端口的批量下发必须使用同一种模式')

        switch_ip = normalized_rows[0]['switch_ip']
        interface = normalized_rows[0]['interface']
        mode = normalized_rows[0]['mode']
        runtime = get_switch_runtime_data(switch_ip)
        mgr = get_manager(runtime)
        assert_interface_not_protected(mgr, interface)

        raw_log = mgr.configure_port_bindings_batch(interface, normalized_rows, mode)
        for row in normalized_rows:
            save_binding_state(
                row['switch_ip'],
                row['interface'],
                row['vlan'],
                row['bind_ip'],
                row['mac'],
                row['mode'],
            )

        vlan_summary = ','.join(sorted({row['vlan'] for row in normalized_rows}))
        details = f"[Excel批量聚合] 端口:{interface} | 条数:{len(normalized_rows)} | 模式:{mode} | VLAN:{vlan_summary}"
        db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", details, "成功")
        return jsonify({'status': 'success', 'log': format_switch_log(raw_log)})
    except ValueError as e:
        if 'client_ip' in locals():
            db.log_operation(
                current_user.username,
                client_ip,
                normalized_rows[0]['switch_ip'] if 'normalized_rows' in locals() and normalized_rows else 'Unknown',
                "批量端口绑定",
                f"[Excel批量聚合] 报错: {str(e)}",
                "失败",
            )
        return json_error(str(e))
    except Exception as e:
        if 'client_ip' in locals():
            db.log_operation(
                current_user.username,
                client_ip,
                normalized_rows[0]['switch_ip'] if 'normalized_rows' in locals() and normalized_rows else 'Unknown',
                "批量端口绑定",
                f"[Excel批量聚合] 报错: {str(e)}",
                "失败",
            )
        return internal_error('批量下发失败，请检查设备状态和表格内容', e)

# === 馃搳 Excel 鎵归噺鑷姩鍖栧紩鎿庝笓鐢ㄦ帴鍙?===
@app.route('/api/execute_excel_row', methods=['POST'])
@login_required
def execute_excel_row():
    try:
        d = get_json_data()
        client_ip = request.remote_addr
        require_fields(d, ['switch_ip', 'interface', 'vlan', 'bind_ip', 'mac', 'mode'])
        switch_ip = normalize_ip(d.get('switch_ip'), '交换机 IP')
        interface = str(d.get('interface')).strip()
        vlan = normalize_vlan(d.get('vlan'))
        bind_ip = normalize_ip(d.get('bind_ip'), '绑定 IP')
        mac = normalize_mac(d.get('mac'))
        mode = normalize_mode(d.get('mode', 'access'))
        runtime = get_switch_runtime_data(switch_ip)
        mgr = get_manager(runtime)
        assert_interface_not_protected(mgr, interface)

        raw_log = mgr.configure_port_binding(interface, vlan, bind_ip, mac, mode)
        log_output = format_switch_log(raw_log)
        save_binding_state(switch_ip, interface, vlan, bind_ip, mac, mode)
        details = f"[Excel批量] 端口:{interface} | IP:{bind_ip} | MAC:{mac} | 模式:{mode} | VLAN:{vlan}"
        db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", details, "成功")

        return jsonify({'status': 'success', 'log': log_output})
    except ValueError as e:
        details = f"[Excel批量] 端口:{locals().get('interface', '')} | IP:{locals().get('bind_ip', '')} | MAC:{locals().get('mac', '')}"
        db.log_operation(current_user.username, client_ip, locals().get('switch_ip', 'Unknown'), "批量端口绑定", f"{details} | 报错: {str(e)}", "失败")
        return json_error(str(e))
    except Exception as e:
        details = f"[Excel批量] 端口:{interface} | IP:{bind_ip} | MAC:{mac}"
        db.log_operation(current_user.username, client_ip, switch_ip, "批量端口绑定", f"{details} | 报错: {str(e)}", "失败")
        return internal_error('批量下发失败，请检查设备状态和参数', e)

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
    save_success_count, save_fail_count = 0, 0
    auto_save_enabled = db.get_setting('auto_save_after_backup', '1') == '1'

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
            if auto_save_enabled:
                try:
                    save_output = mgr.save_config_to_device()
                    save_success_count += 1
                    db.log_operation(
                        "System(系统)",
                        "Localhost",
                        target_ip,
                        "定时备份后保存配置",
                        f"备份成功后执行保存配置。备份文件: {filename}",
                        "成功",
                    )
                    print(f"  [{vendor.upper()}] {target_ip} 保存配置成功")
                except Exception as save_exc:
                    save_fail_count += 1
                    save_error = str(save_exc)
                    db.log_operation(
                        "System(系统)",
                        "Localhost",
                        target_ip,
                        "定时备份后保存配置",
                        f"备份文件: {filename} | 保存失败原因: {save_error}",
                        "失败",
                    )
                    print(f"  [{vendor.upper()}] {target_ip} 保存配置失败: {save_error}")
            else:
                print(f"  [{vendor.upper()}] {target_ip} 已按系统设置跳过保存配置")
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

    details = (
        f"任务结束。共 {len(switches)} 台。备份成功: {success_count}, 备份失败: {fail_count}。"
        f"备份后自动保存:{'开启' if auto_save_enabled else '关闭'}。"
        f"保存成功: {save_success_count}, 保存失败: {save_fail_count}。路径: {today_dir}"
    )
    status = "成功" if fail_count == 0 else ("部分失败" if success_count > 0 else "全部失败")
    
    try:
        db.log_operation("System(系统)", "Localhost", "ALL_SWITCHES", "定时自动备份", details, status)
    except Exception as log_e:
        pass
    print(f"[系统调度] 备份任务执行完毕：{details}\n")


def auto_sync_mac_bindings_task():
    start_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{start_time}] [系统调度] 开始同步终端绑定信息...")
    try:
        result = run_mac_bindings_sync("System(系统)", "Localhost")
        if result['status'] == 'busy':
            print("[系统调度] 终端绑定信息同步跳过：已有同步任务正在执行")
            return
        data = result.get('data', {})
        details = (
            f"扫描交换机:{data.get('scanned_switches', 0)} | "
            f"发现绑定:{data.get('found', 0)} | "
            f"新增:{data.get('created', 0)} | "
            f"更新:{data.get('updated', 0)} | "
            f"未变:{data.get('unchanged', 0)} | "
            f"错误:{len(data.get('errors', []))}"
        )
        print(f"[系统调度] 终端绑定信息同步完成：{details}\n")
    except Exception as exc:
        print(f"[系统调度] 终端绑定信息同步失败：{exc}")
        try:
            db.log_operation(
                "System(系统)",
                "Localhost",
                "ALL_SWITCHES",
                "同步终端绑定信息",
                f"定时同步失败: {exc}",
                "失败",
            )
        except Exception:
            pass


def auto_data_export_task():
    try:
        settings = db.get_system_settings()
        if not settings.get('auto_data_export_enabled'):
            print("[系统调度] 自动数据包导出已关闭")
            return
        path = write_data_package_to_dir(settings.get('auto_data_export_dir'))
        db.log_operation("System(系统)", "Localhost", "LOCAL", "自动导出数据包", f"导出路径: {path}", "成功")
        print(f"[系统调度] 自动数据包导出完成: {path}")
    except Exception as exc:
        print(f"[系统调度] 自动数据包导出失败：{exc}")
        try:
            db.log_operation("System(系统)", "Localhost", "LOCAL", "自动导出数据包", f"失败原因: {exc}", "失败")
        except Exception:
            pass


def auto_collect_switch_alarm_logs_task():
    try:
        settings = db.get_system_settings()
        if not settings.get('auto_alarm_collect_enabled'):
            print("[系统调度] 自动采集交换机日志告警已关闭")
            return
        switches = db.get_all_switches()
        success_count = 0
        fail_count = 0
        for sw in switches:
            switch_ip = sw.get('ip')
            try:
                collect_switch_alarm_report(switch_ip)
                success_count += 1
                print(f"[系统调度] 日志告警采集成功: {sw.get('name') or switch_ip}({switch_ip})")
            except Exception as exc:
                fail_count += 1
                db.add_switch_alarm_report(
                    switch_ip=switch_ip,
                    switch_name=sw.get('name', ''),
                    vendor=sw.get('vendor', ''),
                    status='失败',
                    error=str(exc)[:500],
                )
                print(f"[系统调度] 日志告警采集失败: {sw.get('name') or switch_ip}({switch_ip}) - {exc}")
        db.log_operation(
            "System(系统)",
            "Localhost",
            "ALL_SWITCHES",
            "定时采集交换机日志告警",
            f"成功 {success_count} 台，失败 {fail_count} 台",
            "成功" if fail_count == 0 else "部分失败",
        )
    except Exception as exc:
        print(f"[系统调度] 自动采集交换机日志告警失败：{exc}")
        try:
            db.log_operation("System(系统)", "Localhost", "ALL_SWITCHES", "定时采集交换机日志告警", f"失败原因: {exc}", "失败")
        except Exception:
            pass

# 调度器初始化与启动
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def configure_scheduler():
    settings = db.get_system_settings()
    scheduler.add_job(
        func=auto_backup_task,
        trigger="cron",
        hour=settings.get('auto_backup_hour', 2),
        minute=settings.get('auto_backup_minute', 37),
        id="auto_backup",
        replace_existing=True,
    )
    scheduler.add_job(
        func=auto_sync_mac_bindings_task,
        trigger="cron",
        hour=settings.get('auto_sync_hour', 3),
        minute=settings.get('auto_sync_minute', 20),
        id="auto_sync_mac_bindings",
        replace_existing=True,
    )
    scheduler.add_job(
        func=auto_data_export_task,
        trigger="cron",
        hour=settings.get('auto_data_export_hour', 4),
        minute=settings.get('auto_data_export_minute', 10),
        id="auto_data_export",
        replace_existing=True,
    )
    scheduler.add_job(
        func=auto_collect_switch_alarm_logs_task,
        trigger="cron",
        hour=settings.get('auto_alarm_collect_hour', 4),
        minute=settings.get('auto_alarm_collect_minute', 40),
        id="auto_alarm_collect",
        replace_existing=True,
    )


def start_scheduler():
    configure_scheduler()
    if not scheduler.running:
        scheduler.start()


start_scheduler()
# ============================================



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
