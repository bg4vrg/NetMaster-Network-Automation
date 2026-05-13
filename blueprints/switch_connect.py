from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from background_tasks import submit_task, update_task


def create_switch_connect_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    normalize_port,
    normalize_vendor,
    get_manager,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('switch_connect', __name__)

    @bp.route('/test_connection', methods=['POST'])
    @login_required
    @permission_required('switch.write')
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

    @bp.route('/get_interfaces', methods=['POST'])
    @login_required
    @permission_required('access.write')
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
            return jsonify({'status': 'success', 'data': mgr.get_interface_list()})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('获取端口列表失败，请检查设备连通性和凭据', e)

    @bp.route('/get_port_info', methods=['POST'])
    @login_required
    @permission_required('access.write')
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

    @bp.route('/api/port_probe/start', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def start_port_probe():
        try:
            data = get_json_data()
            require_fields(data, ['ip', 'user', 'pass', 'interface'])
            data['ip'] = normalize_ip(data['ip'])
            if 'port' in data:
                data['port'] = normalize_port(data['port'])
            if 'vendor' in data:
                data['vendor'] = normalize_vendor(data['vendor'])
            interface = str(data.get('interface') or '').strip()
            if not interface:
                raise ValueError('端口不能为空')

            def probe(task_id):
                update_task(task_id, message=f'正在连接 {data["ip"]} 查询 {interface}', progress=25)
                mgr = get_manager(data)
                update_task(task_id, message=f'正在读取端口 {interface} 当前配置', progress=65)
                info, raw = mgr.get_port_info(interface)
                return {
                    'port': interface,
                    'info': info,
                    'raw': raw,
                    'log': f"读取成功。<br>RAW:<br>{raw.replace(chr(10), '<br>')}",
                }

            task = submit_task(
                f'实时查询端口 {interface}',
                probe,
                category='port_probe',
                actor=current_user.username,
                target=f'{data["ip"]} {interface}',
                metadata={'switch_ip': data['ip'], 'interface': interface},
            )
            return jsonify({'status': 'success', 'data': task, 'task_id': task['id']})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('启动端口实时查询失败，请稍后重试', e)

    @bp.route('/save_config', methods=['POST'])
    @login_required
    @permission_required('switch.write')
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
            db.log_operation(current_user.username, locals().get('client_ip', request.remote_addr), locals().get('device_ip', 'Unknown'), "保存配置", f"报错: {str(e)}", "失败")
            return internal_error('保存配置失败，请检查设备状态后重试', e)

    return bp
