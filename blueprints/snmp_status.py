from flask import Blueprint, jsonify
from flask_login import login_required

from snmp_client import SnmpUnavailable, get_interface_list, get_port_status


def create_snmp_status_blueprint(db, get_json_data, require_fields, normalize_ip, json_error, internal_error, permission_required):
    bp = Blueprint('snmp_status', __name__)

    @bp.route('/api/snmp/port_status', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def api_snmp_port_status():
        try:
            data = get_json_data()
            require_fields(data, ['ip', 'interface'])
            switch_ip = normalize_ip(data.get('ip'))
            interface = str(data.get('interface') or '').strip()
            if not interface:
                raise ValueError('端口不能为空')
            community = str(data.get('community') or db.get_setting('snmp_read_community', 'suyuga0527') or '').strip()
            if not community:
                raise ValueError('SNMP 只读团体名不能为空')
            timeout = float(data.get('timeout') or db.get_setting('snmp_timeout', '2.5') or 2.5)
            retries = int(data.get('retries') or db.get_setting('snmp_retries', '2') or 2)
            result = get_port_status(switch_ip, interface, community, timeout=max(0.5, min(timeout, 10)), retries=max(0, min(retries, 3)))
            return jsonify({'status': 'success', 'data': result})
        except SnmpUnavailable as e:
            return json_error(str(e), 503)
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('SNMP 端口状态查询失败，请检查团体名、SNMP 可达性和端口名称', e)

    @bp.route('/api/snmp/interfaces', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def api_snmp_interfaces():
        try:
            data = get_json_data()
            require_fields(data, ['ip'])
            switch_ip = normalize_ip(data.get('ip'))
            community = str(data.get('community') or db.get_setting('snmp_read_community', 'suyuga0527') or '').strip()
            if not community:
                raise ValueError('SNMP 只读团体名不能为空')
            timeout = float(data.get('timeout') or db.get_setting('snmp_timeout', '2.5') or 2.5)
            retries = int(data.get('retries') or db.get_setting('snmp_retries', '2') or 2)
            result = get_interface_list(
                switch_ip,
                community,
                timeout=max(0.5, min(timeout, 10)),
                retries=max(0, min(retries, 3)),
            )
            return jsonify({'status': 'success', 'data': result})
        except SnmpUnavailable as e:
            return json_error(str(e), 503)
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('SNMP 端口列表读取失败，已可回退 SSH 获取端口列表', e)

    return bp
