from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from background_tasks import submit_task


def create_terminal_state_blueprint(
    db,
    normalize_ip,
    get_json_data,
    get_mac_sync_state_snapshot,
    mac_sync_lock,
    run_mac_bindings_sync,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('terminal_state', __name__)

    @bp.route('/api/sync_mac_bindings', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def sync_mac_bindings():
        try:
            data = get_json_data()
            switch_ip = str(data.get('switch_ip', '')).strip()
            if mac_sync_lock.locked():
                return jsonify(
                    {
                        'status': 'busy',
                        'msg': '终端绑定信息正在同步中，请稍后再试。',
                        'data': get_mac_sync_state_snapshot(),
                    }
                ), 409

            actor = current_user.username
            client_ip = request.remote_addr
            target = switch_ip or 'ALL_SWITCHES'

            def run(task_id):
                return run_mac_bindings_sync(actor, client_ip, switch_ip)

            task = submit_task(
                '终端绑定同步',
                run,
                category='terminal_sync',
                actor=actor,
                target=target,
                metadata={'switch_ip': switch_ip},
            )
            return jsonify(
                {
                    'status': 'success',
                    'msg': '同步任务已在后台启动。',
                    'data': get_mac_sync_state_snapshot(),
                    'task': task,
                }
            )
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('同步终端绑定信息失败，请检查设备连通性和资产凭据', e)

    @bp.route('/api/mac_sync_status', methods=['GET'])
    @login_required
    def mac_sync_status():
        return jsonify({'status': 'success', 'data': get_mac_sync_state_snapshot()})

    @bp.route('/api/mac_bindings', methods=['GET'])
    @login_required
    def api_mac_bindings():
        try:
            limit = request.args.get('limit', '500')
            limit = max(1, min(5000, int(limit)))
            switch_ip = str(request.args.get('switch_ip', '')).strip()
            if switch_ip:
                switch_ip = normalize_ip(switch_ip, '交换机 IP')
            rows = db.get_mac_bindings(limit=limit, switch_ip=switch_ip or None)
            return jsonify({'status': 'success', 'data': rows})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('读取已绑定终端列表失败，请稍后重试', e)

    return bp
