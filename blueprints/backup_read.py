import difflib
import re

from flask import Blueprint, jsonify, request
from flask_login import login_required


def create_backup_read_blueprint(
    list_backup_config_files,
    read_backup_text,
    get_json_data,
    require_fields,
    normalize_ip,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('backup_read', __name__)

    def classify_diff_lines(diff_lines):
        categories = {
            'interface': {'label': '接口配置', 'count': 0},
            'vlan': {'label': 'VLAN', 'count': 0},
            'binding': {'label': '终端绑定/准入', 'count': 0},
            'acl': {'label': 'ACL/策略', 'count': 0},
            'route': {'label': '路由', 'count': 0},
            'management': {'label': '管理服务', 'count': 0},
            'other': {'label': '其他', 'count': 0},
        }
        for line in diff_lines:
            if not (line.startswith('+') or line.startswith('-')) or line.startswith(('+++', '---')):
                continue
            text = line[1:].strip().lower()
            if not text:
                continue
            if any(key in text for key in ['ip source binding', 'user-bind', 'arp detection', 'ip verify source', 'mac-address']):
                key = 'binding'
            elif text.startswith('interface ') or re.search(r'\b(x?ge|gigabitethernet|xgigabitethernet|ten-gigabit)\d', text):
                key = 'interface'
            elif text.startswith('vlan') or 'port access vlan' in text or 'port trunk permit vlan' in text:
                key = 'vlan'
            elif text.startswith('acl') or 'packet-filter' in text or 'rule ' in text:
                key = 'acl'
            elif text.startswith('ip route') or text.startswith('route-static') or 'ospf' in text or 'static-route' in text:
                key = 'route'
            elif any(word in text for word in ['snmp', 'ntp', 'radius', 'tacacs', 'ssh server', 'local-user', 'info-center', 'syslog']):
                key = 'management'
            else:
                key = 'other'
            categories[key]['count'] += 1
        return [value for value in categories.values() if value['count']]

    def build_diff_response(old_path, new_path, old_lines, new_lines):
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
        return jsonify({'status': 'success', 'data': {
            'old_path': old_path,
            'new_path': new_path,
            'additions': additions,
            'deletions': deletions,
            'changed': bool(additions or deletions),
            'categories': classify_diff_lines(diff_lines),
            'diff': '\n'.join(diff_lines),
        }})

    @bp.route('/api/backup_files', methods=['GET'])
    @login_required
    @permission_required('backup.view')
    def api_backup_files():
        try:
            limit = int(request.args.get('limit', 500))
            limit = max(1, min(limit, 2000))
            return jsonify({'status': 'success', 'data': list_backup_config_files(limit=limit)})
        except Exception as e:
            return internal_error('获取备份文件列表失败，请稍后重试', e)

    @bp.route('/api/backup_diff', methods=['POST'])
    @login_required
    @permission_required('backup.view')
    def api_backup_diff():
        try:
            data = get_json_data()
            require_fields(data, ['old_path', 'new_path'])
            old_path = str(data['old_path']).strip()
            new_path = str(data['new_path']).strip()
            return build_diff_response(old_path, new_path, read_backup_text(old_path), read_backup_text(new_path))
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('配置差异比对失败，请检查备份文件', e)

    @bp.route('/api/backup_diff_latest', methods=['POST'])
    @login_required
    @permission_required('backup.view')
    def api_backup_diff_latest():
        try:
            data = get_json_data()
            device_ip = normalize_ip(data.get('device_ip'), '交换机 IP')
            files = [item for item in list_backup_config_files(limit=2000) if item.get('device_ip') == device_ip]
            if len(files) < 2:
                return json_error('该设备少于 2 份备份文件，无法一键比对')
            new_file, old_file = files[0], files[1]
            return build_diff_response(
                old_file['path'],
                new_file['path'],
                read_backup_text(old_file['path']),
                read_backup_text(new_file['path']),
            )
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('最近两次配置比对失败，请检查备份文件', e)

    return bp
