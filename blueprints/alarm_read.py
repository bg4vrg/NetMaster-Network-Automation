from flask import Blueprint, jsonify, request
from flask_login import login_required


def create_alarm_read_blueprint(db, build_alarm_command_suggestions, internal_error):
    bp = Blueprint('alarm_read', __name__)

    @bp.route('/api/switch_alarm_reports', methods=['GET'])
    @login_required
    def api_switch_alarm_reports():
        try:
            limit = int(request.args.get('limit') or 200)
            limit = max(1, min(limit, 1000))
            return jsonify({'status': 'success', 'data': db.get_switch_alarm_reports(limit)})
        except Exception as e:
            return internal_error('读取交换机日志分析报告失败', e)

    @bp.route('/api/alarm_dashboard', methods=['GET'])
    @login_required
    def api_alarm_dashboard():
        try:
            reports = db.get_latest_switch_alarm_reports()
            states = db.get_alarm_states()
            trends = db.get_alarm_trends(7)
            risk_rank = {'high': 4, 'medium': 3, 'low': 2, 'normal': 1}
            summary = {
                'total': len(reports),
                'high': 0,
                'medium': 0,
                'low': 0,
                'normal': 0,
                'failed': 0,
                'ack': 0,
                'ignored': 0,
            }
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

    return bp
