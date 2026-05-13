from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from runtime_paths import DATA_PACKAGE_DIR


def create_system_manage_blueprint(db, get_json_data, json_error, internal_error, permission_required, configure_scheduler):
    bp = Blueprint('system_manage', __name__)

    @bp.route('/api/settings/update', methods=['POST'])
    @login_required
    @permission_required('system.manage')
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
            if 'snmp_read_community' in data:
                community = str(data.get('snmp_read_community') or '').strip()
                if not community:
                    raise ValueError('SNMP 只读团体名不能为空')
                if len(community) > 128:
                    raise ValueError('SNMP 只读团体名过长')
                db.set_setting('snmp_read_community', community)
            if 'snmp_timeout' in data:
                timeout = float(data.get('snmp_timeout'))
                if timeout < 0.5 or timeout > 10:
                    raise ValueError('SNMP 超时时间必须在 0.5-10 秒之间')
                db.set_setting('snmp_timeout', timeout)
            if 'snmp_retries' in data:
                retries = int(data.get('snmp_retries'))
                if retries < 0 or retries > 3:
                    raise ValueError('SNMP 重试次数必须在 0-3 之间')
                db.set_setting('snmp_retries', retries)
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
                export_dir = str(data.get('auto_data_export_dir') or str(DATA_PACKAGE_DIR)).strip()
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

    return bp
