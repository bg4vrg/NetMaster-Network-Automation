import re

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from background_tasks import submit_task, update_task


def _normalize_interface_snapshot(item):
    text = str(item.get('text') or '').strip()
    value = str(item.get('value') or item.get('name') or '').strip()
    link_status = str(item.get('link') or '').strip()
    mode = str(item.get('type') or '').strip()
    description = str(item.get('desc') or '').strip()

    match = re.match(r'^\[([^\]]+)\]\s+\[([^\]]+)\]\s+([^\s]+)(?:\s+\((.*)\))?$', text)
    if match:
        link_status = link_status or match.group(1)
        mode = mode or match.group(2)
        value = value or match.group(3)
        description = description or (match.group(4) or '')

    return {
        'port': value,
        'link_status': link_status,
        'mode': mode,
        'description': description,
        'raw_text': text,
    }


def create_port_snapshot_blueprint(
    db,
    get_json_data,
    normalize_ip,
    get_switch_runtime_data,
    get_manager,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('port_snapshot', __name__)

    @bp.route('/api/port_snapshots', methods=['GET'])
    @login_required
    def api_port_snapshots():
        try:
            switch_ip = str(request.args.get('switch_ip', '')).strip()
            if switch_ip:
                switch_ip = normalize_ip(switch_ip, '交换机 IP')
            limit = request.args.get('limit', '1000')
            return jsonify({'status': 'success', 'data': db.get_port_snapshots(switch_ip=switch_ip or None, limit=limit)})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('读取端口快照失败，请稍后重试', e)

    @bp.route('/api/port_snapshots/collect', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def api_collect_port_snapshots():
        try:
            data = get_json_data()
            switch_ip = str(data.get('switch_ip') or '').strip()
            collect_all = bool(data.get('all'))
            if switch_ip:
                switch_ip = normalize_ip(switch_ip, '交换机 IP')
            if not switch_ip and not collect_all:
                raise ValueError('请指定 switch_ip，或明确传入 all=true 才能全量采集端口快照')

            if switch_ip:
                switches = [get_switch_runtime_data(switch_ip)]
            else:
                switches = [dict(sw) for sw in db.get_terminal_sync_switches()]

            def collect(task_id):
                total = len(switches)
                saved_total = 0
                errors = []
                for index, sw in enumerate(switches, start=1):
                    target_ip = sw.get('ip')
                    update_task(
                        task_id,
                        message=f'正在采集端口快照 {index}/{total}: {sw.get("name") or target_ip}',
                        progress=int((index - 1) / max(total, 1) * 90) + 5,
                    )
                    try:
                        mgr = get_manager(sw)
                        interfaces = [_normalize_interface_snapshot(item) for item in mgr.get_interface_list()]
                        result = db.save_port_snapshots(target_ip, interfaces)
                        saved_total += result.get('saved', 0)
                    except Exception as exc:
                        errors.append(f'{target_ip}: {exc}')
                update_task(task_id, message='端口快照采集完成', progress=95)
                return {'switches': total, 'saved': saved_total, 'errors': errors}

            task = submit_task(
                '采集端口快照',
                collect,
                category='port_snapshot',
                actor=current_user.username,
                target=switch_ip or 'ALL_SWITCHES',
                metadata={'switch_ip': switch_ip, 'all': collect_all},
            )
            return jsonify({'status': 'success', 'data': task, 'task_id': task['id']})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('启动端口快照采集失败，请稍后重试', e)

    @bp.route('/api/port_probe_asset/start', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def api_port_probe_asset_start():
        try:
            data = get_json_data()
            switch_ip = normalize_ip(data.get('switch_ip'), '交换机 IP')
            interface = str(data.get('interface') or '').strip()
            if not interface:
                raise ValueError('端口不能为空')

            def probe(task_id):
                update_task(task_id, message=f'正在读取资产凭据并连接 {switch_ip}', progress=20)
                runtime = get_switch_runtime_data(switch_ip)
                mgr = get_manager(runtime)
                update_task(task_id, message=f'正在实时复核端口 {interface}', progress=65)
                info, raw = mgr.get_port_info(interface)
                return {
                    'switch_ip': switch_ip,
                    'port': interface,
                    'info': info,
                    'raw': raw,
                    'log': f"读取成功。<br>RAW:<br>{raw.replace(chr(10), '<br>')}",
                }

            task = submit_task(
                f'资产端口实时复核 {interface}',
                probe,
                category='port_probe',
                actor=current_user.username,
                target=f'{switch_ip} {interface}',
                metadata={'switch_ip': switch_ip, 'interface': interface, 'source': 'asset'},
            )
            return jsonify({'status': 'success', 'data': task, 'task_id': task['id']})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('启动资产端口实时复核失败，请稍后重试', e)

    return bp
