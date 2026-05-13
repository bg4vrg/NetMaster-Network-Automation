import datetime
import io

from flask import Blueprint, jsonify, request, send_file
from flask_login import login_required


def create_audit_task_blueprint(db, permission_required, internal_error, csv_text):
    bp = Blueprint('audit_task', __name__)

    @bp.route('/api/audit_logs', methods=['GET'])
    @login_required
    @permission_required('audit.view')
    def api_audit_logs():
        try:
            limit = int(request.args.get('limit', 20))
            offset = int(request.args.get('offset', 0))
            limit = max(1, min(limit, 100))
            offset = max(0, offset)
            filters = {
                'action': request.args.get('action'),
                'username': request.args.get('username'),
                'device_ip': request.args.get('device_ip'),
                'status': request.args.get('status'),
                'start_time': request.args.get('start_time'),
                'end_time': request.args.get('end_time'),
            }
            rows = db.get_audit_logs(limit=limit + 1, offset=offset, filters=filters)
            has_more = len(rows) > limit
            logs = rows[:limit]
            return jsonify({'status': 'success', 'data': {
                'logs': logs,
                'limit': limit,
                'offset': offset,
                'next_offset': offset + len(logs),
                'has_more': has_more,
            }})
        except Exception as e:
            return internal_error('获取审计日志失败，请稍后重试', e)

    @bp.route('/api/audit_logs/export', methods=['GET'])
    @login_required
    @permission_required('audit.view')
    def api_audit_logs_export():
        try:
            filters = {
                'action': request.args.get('action'),
                'username': request.args.get('username'),
                'device_ip': request.args.get('device_ip'),
                'status': request.args.get('status'),
                'start_time': request.args.get('start_time'),
                'end_time': request.args.get('end_time'),
            }
            rows = db.get_audit_logs(limit=5000, offset=0, filters=filters)
            headers = ['timestamp', 'username', 'client_ip', 'device_ip', 'action', 'details', 'status']
            memory = io.BytesIO(csv_text(headers, rows).encode('utf-8-sig'))
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            return send_file(memory, as_attachment=True, download_name=f'audit_logs_{timestamp}.csv', mimetype='text/csv')
        except Exception as e:
            return internal_error('导出审计日志失败，请稍后重试', e)

    @bp.route('/api/audit_logs/options', methods=['GET'])
    @login_required
    @permission_required('audit.view')
    def api_audit_log_options():
        try:
            return jsonify({'status': 'success', 'data': db.get_audit_filter_options()})
        except Exception as e:
            return internal_error('获取审计日志筛选项失败，请稍后重试', e)

    @bp.route('/api/task_center', methods=['GET'])
    @login_required
    @permission_required('task.view')
    def api_task_center():
        try:
            limit = int(request.args.get('limit', 20))
            offset = int(request.args.get('offset', 0))
            limit = max(1, min(limit, 100))
            offset = max(0, offset)
            rows = db.get_task_logs(limit=limit + 1, offset=offset)
            has_more = len(rows) > limit
            logs = rows[:limit]
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
            return jsonify({'status': 'success', 'data': {
                'logs': logs,
                'summary': summary,
                'limit': limit,
                'offset': offset,
                'next_offset': offset + len(logs),
                'has_more': has_more,
            }})
        except Exception as e:
            return internal_error('获取任务中心数据失败，请稍后重试', e)

    return bp
