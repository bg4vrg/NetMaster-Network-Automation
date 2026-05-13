from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from background_tasks import submit_task, update_task


def create_alarm_manage_blueprint(
    db,
    get_json_data,
    normalize_ip,
    collect_switch_alarm_report,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('alarm_manage', __name__)

    @bp.route('/api/switch_alarm_logs', methods=['POST'])
    @login_required
    @permission_required('alarm.manage')
    def api_switch_alarm_logs():
        try:
            data = get_json_data()
            switch_ip = normalize_ip(data.get('switch_ip') or data.get('ip'), '交换机 IP')
            result = collect_switch_alarm_report(switch_ip)
            raw = result['raw']
            analysis = result['analysis']
            db.log_operation(
                current_user.username,
                request.remote_addr,
                switch_ip,
                "采集交换机日志告警",
                f"critical={analysis['critical']} warning={analysis['warning']}",
                "成功",
            )
            return jsonify({'status': 'success', 'data': {'raw': raw[-20000:], 'analysis': analysis}})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('采集交换机日志失败，请检查设备状态', e)

    @bp.route('/api/switch_alarm_logs/start', methods=['POST'])
    @login_required
    @permission_required('alarm.manage')
    def api_switch_alarm_logs_start():
        try:
            data = get_json_data()
            switch_ip = normalize_ip(data.get('switch_ip') or data.get('ip'), '交换机 IP')
            actor = current_user.username
            remote_addr = request.remote_addr

            def run(task_id):
                update_task(task_id, message=f'正在采集 {switch_ip} 日志', progress=30)
                result = collect_switch_alarm_report(switch_ip)
                analysis = result['analysis']
                db.log_operation(
                    actor,
                    remote_addr,
                    switch_ip,
                    "采集交换机日志告警",
                    f"critical={analysis['critical']} warning={analysis['warning']}",
                    "成功",
                )
                update_task(task_id, message='日志采集与分析完成', progress=95)
                return {'raw': result['raw'][-20000:], 'analysis': analysis}

            task = submit_task(
                f'采集交换机日志 {switch_ip}',
                run,
                category='alarm_collect',
                actor=actor,
                target=switch_ip,
            )
            return jsonify({'status': 'success', 'data': task, 'task_id': task['id']})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('启动日志采集任务失败', e)

    @bp.route('/api/alarm_state/update', methods=['POST'])
    @login_required
    @permission_required('alarm.manage')
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
            db.log_operation(
                current_user.username,
                request.remote_addr,
                switch_ip,
                "更新告警状态",
                f"state={state} note={note[:100]}",
                "成功",
            )
            return jsonify({'status': 'success'})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('更新告警状态失败', e)

    return bp
