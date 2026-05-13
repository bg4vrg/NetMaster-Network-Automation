from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required


def create_access_manage_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    normalize_port,
    normalize_vendor,
    normalize_mac,
    normalize_mode,
    normalize_vlan,
    normalize_acl_number,
    get_manager,
    assert_interface_not_protected,
    save_binding_state,
    format_switch_log,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('access_manage', __name__)

    @bp.route('/set_interface_description', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def set_interface_description():
        try:
            data = get_json_data()
            require_fields(data, ['ip', 'user', 'pass', 'interface'])
            client_ip = request.remote_addr
            data['ip'] = normalize_ip(data['ip'])
            if 'port' in data:
                data['port'] = normalize_port(data['port'])
            if 'vendor' in data:
                data['vendor'] = normalize_vendor(data['vendor'])
            description = str(data.get('description', '')).strip()
            if '\n' in description or '\r' in description:
                raise ValueError('端口描述不能包含换行符')
            if len(description) > 120:
                raise ValueError('端口描述不能超过 120 个字符')

            mgr = get_manager(data)
            log = mgr.set_interface_description(data['interface'], description)
            details = f"端口:{data['interface']} | 描述:{description or '(清空)'}"
            db.log_operation(current_user.username, client_ip, data['ip'], "设置端口描述", details, "成功")
            return jsonify({'status': 'success', 'log': format_switch_log(log).replace('\n', '<br>')})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            if 'data' in locals():
                db.log_operation(
                    current_user.username,
                    locals().get('client_ip', request.remote_addr),
                    data.get('ip', 'Unknown'),
                    "设置端口描述",
                    f"端口:{data.get('interface', '')} | 报错:{str(e)}",
                    "失败",
                )
            return internal_error('设置端口描述失败，请检查设备状态和参数', e)

    @bp.route('/bind_port', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def bind_port():
        try:
            d = get_json_data()
            require_fields(d, ['ip', 'interface', 'bind_ip', 'mac', 'mode'])
            client_ip = request.remote_addr
            d['ip'] = normalize_ip(d['ip'])
            d['bind_ip'] = normalize_ip(d['bind_ip'], '绑定 IP')
            d['mac'] = normalize_mac(d['mac'])
            mode = normalize_mode(d.get('mode', 'access'))
            d['mode'] = mode
            d['vlan'] = normalize_vlan(d.get('vlan'))
            device_ip = d.get('ip', 'Unknown')
            details = f"端口:{d.get('interface')} | IP:{d.get('bind_ip')} | MAC:{d.get('mac')} | 模式:{mode} | VLAN:{d.get('vlan')}"
            mgr = get_manager(d)

            assert_interface_not_protected(mgr, d['interface'])

            log = mgr.configure_port_binding(d['interface'], d['vlan'], d['bind_ip'], d['mac'], mode)
            save_binding_state(d['ip'], d['interface'], d['vlan'], d['bind_ip'], d['mac'], mode)
            db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", details, "成功")
            return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
        except ValueError as e:
            if 'details' in locals():
                db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", f"{details} | 报错: {str(e)}", "失败")
            return json_error(str(e))
        except Exception as e:
            db.log_operation(current_user.username, client_ip, device_ip, "端口绑定", f"{details} | 报错: {str(e)}", "失败")
            return internal_error('端口绑定失败，请检查设备状态和参数', e)

    @bp.route('/del_port_binding', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def del_port_binding():
        try:
            d = get_json_data()
            require_fields(d, ['ip', 'interface', 'del_ip', 'del_mac', 'mode'])
            client_ip = request.remote_addr
            d['ip'] = normalize_ip(d['ip'])
            d['del_ip'] = normalize_ip(d['del_ip'], '解绑 IP')
            d['del_mac'] = normalize_mac(d['del_mac'], '解绑 MAC')
            mode = normalize_mode(d.get('mode', 'access'))
            d['mode'] = mode
            vlan = normalize_vlan(d.get('vlan'), allow_empty=True)
            d['vlan'] = vlan
            device_ip = d.get('ip', 'Unknown')
            details = f"端口:{d.get('interface')} | IP:{d.get('del_ip')} | MAC:{d.get('del_mac')} | 模式:{mode} | VLAN:{vlan}"
            mgr = get_manager(d)

            assert_interface_not_protected(mgr, d['interface'])

            log = mgr.delete_port_binding(d['interface'], d['del_ip'], d['del_mac'], mode, vlan)
            db.delete_mac_binding(d['del_mac'])
            db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", details, "成功")
            return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
        except ValueError as e:
            if 'details' in locals():
                db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", f"{details} | 报错: {str(e)}", "失败")
            return json_error(str(e))
        except Exception as e:
            db.log_operation(current_user.username, client_ip, device_ip, "解除绑定", f"{details} | 报错: {str(e)}", "失败")
            return internal_error('解除绑定失败，请检查设备状态和参数', e)

    @bp.route('/get_acl', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def get_acl():
        try:
            data = get_json_data()
            require_fields(data, ['ip', 'user', 'pass'])
            data['ip'] = normalize_ip(data['ip'])
            if 'port' in data:
                data['port'] = normalize_port(data['port'])
            if 'vendor' in data:
                data['vendor'] = normalize_vendor(data['vendor'])
            mgr = get_manager(data)
            query_all = bool(data.get('all'))
            if query_all:
                groups = mgr.get_acl_groups()
                return jsonify({'status': 'success', 'data': {'groups': groups}})
            acl_number = normalize_acl_number(data.get('acl_number', 4000))
            rules = mgr.get_acl_rules(acl_number)
            return jsonify({'status': 'success', 'data': {'groups': [{'number': acl_number, 'type': 'ACL', 'rules': rules}]}})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('获取 ACL 失败，请稍后重试', e)

    @bp.route('/add_acl', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def add_acl():
        try:
            d = get_json_data()
            require_fields(d, ['ip', 'user', 'pass', 'mac'])
            d['ip'] = normalize_ip(d['ip'])
            d['mac'] = normalize_mac(d['mac'])
            if 'port' in d:
                d['port'] = normalize_port(d['port'])
            if 'vendor' in d:
                d['vendor'] = normalize_vendor(d['vendor'])
            mgr = get_manager(d)
            acl_number = normalize_acl_number(d.get('acl_number', 4000))
            rid = d.get('rule_id')
            if rid == "":
                rid = None
            elif rid is not None:
                rid = str(int(str(rid).strip()))
            log = mgr.add_acl_mac(d['mac'], rid, acl_number)
            return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('添加 ACL 失败，请检查参数后重试', e)

    @bp.route('/del_acl', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def del_acl():
        try:
            d = get_json_data()
            require_fields(d, ['ip', 'user', 'pass', 'rule_id'])
            d['ip'] = normalize_ip(d['ip'])
            d['rule_id'] = str(int(str(d['rule_id']).strip()))
            if 'port' in d:
                d['port'] = normalize_port(d['port'])
            if 'vendor' in d:
                d['vendor'] = normalize_vendor(d['vendor'])
            mgr = get_manager(d)
            acl_number = normalize_acl_number(d.get('acl_number', 4000))
            log = mgr.delete_acl_rule(d['rule_id'], acl_number)
            return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('删除 ACL 失败，请检查参数后重试', e)

    return bp
