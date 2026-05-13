import datetime
from pathlib import Path

from flask import Blueprint, jsonify
from flask_login import current_user, login_required


def create_info_read_blueprint(
    db,
    app_version_info,
    count_backup_days,
    list_backup_config_files,
    internal_error,
    admin_required,
):
    bp = Blueprint('info_read', __name__)

    @bp.route('/api/version', methods=['GET'])
    @login_required
    def api_version():
        data = dict(app_version_info)
        if current_user.is_admin:
            data['settings'] = db.get_system_settings()
        return jsonify({'status': 'success', 'data': data})

    @bp.route('/api/dashboard_stats', methods=['GET'])
    @login_required
    def api_dashboard_stats():
        try:
            stats = db.get_dashboard_stats()
            stats['backup_day_count'] = count_backup_days()
            return jsonify({'status': 'success', 'data': stats})
        except Exception as e:
            return internal_error('获取统计数据失败，请稍后重试', e)

    @bp.route('/api/health_check', methods=['GET'])
    @login_required
    @admin_required
    def api_health_check():
        try:
            switches = db.get_all_switches()
            bindings = db.get_mac_bindings(limit=100000)
            backup_files = list_backup_config_files(limit=2000)
            settings = db.get_system_settings()
            backup_dates = sorted({item['date'] for item in backup_files if item.get('date')}, reverse=True)
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
            return jsonify({'status': 'success', 'data': {
                'checks': checks,
                'access_without_bindings': access_without_bindings[:50],
                'stale_bindings': stale_bindings[:50],
                'settings': settings,
            }})
        except Exception as e:
            return internal_error('运行健康检查失败，请稍后重试', e)

    @bp.route('/api/settings', methods=['GET'])
    @login_required
    @admin_required
    def api_settings():
        return jsonify({'status': 'success', 'data': db.get_system_settings()})

    @bp.route('/api/help', methods=['GET'])
    @login_required
    def api_help():
        try:
            guide_path = Path(__file__).resolve().parents[1] / 'USER_GUIDE.md'
            content = guide_path.read_text(encoding='utf-8')
            return jsonify({'status': 'success', 'data': {'content': content}})
        except Exception as e:
            return internal_error('加载使用说明失败，请稍后重试', e)

    return bp
