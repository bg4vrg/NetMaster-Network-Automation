from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required


def create_roam_manage_blueprint(
    db,
    get_json_data,
    require_fields,
    normalize_ip,
    normalize_mac,
    normalize_mode,
    normalize_vlan,
    get_terminal_binding_record,
    get_mac_sync_state_snapshot,
    mac_sync_lock,
    scan_one_switch_for_terminal,
    normalize_terminal_lookup,
    sync_all_switch_bindings,
    assert_no_ip_conflict,
    get_switch_runtime_data,
    get_manager,
    assert_interface_not_protected,
    port_has_binding,
    save_binding_state,
    format_switch_log,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('roam_manage', __name__)

    @bp.route('/api/terminal_binding_lookup', methods=['POST'])
    @login_required
    @permission_required('roam.write')
    def terminal_binding_lookup():
        try:
            data = get_json_data()
            require_fields(data, ['query'])
            source_switch_ip = str(data.get('source_switch_ip', '')).strip()
            try:
                binding = get_terminal_binding_record(data['query'], source_switch_ip or None)
                return jsonify({'status': 'success', 'data': binding, 'source': 'local'})
            except ValueError:
                if mac_sync_lock.locked():
                    return jsonify(
                        {
                            'status': 'error',
                            'msg': '终端绑定信息正在后台同步，请同步完成后再定位终端。',
                            'sync': get_mac_sync_state_snapshot(),
                        }
                    ), 409
                if source_switch_ip:
                    sync_result = scan_one_switch_for_terminal(source_switch_ip, data['query'])
                else:
                    query_type, query_value = normalize_terminal_lookup(data['query'])
                    sync_result = sync_all_switch_bindings(query_type, query_value)
                if sync_result['matched']:
                    return jsonify(
                        {
                            'status': 'success',
                            'data': sync_result['matched'],
                            'source': 'live_scan',
                            'sync': sync_result,
                        }
                    )
                return jsonify(
                    {
                        'status': 'error',
                        'msg': f"已绑定终端列表和主动扫描都未找到该终端。已扫描 {sync_result['scanned_switches']} 台交换机，同步 {sync_result['synced']} 条绑定。",
                        'sync': sync_result,
                    }
                )
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('查询终端位置失败，请稍后重试', e)

    @bp.route('/api/migrate_terminal', methods=['POST'])
    @login_required
    @permission_required('roam.write')
    def migrate_terminal():
        try:
            data = get_json_data()
            require_fields(data, ['query', 'target_switch_ip', 'target_interface'])
            client_ip = request.remote_addr
            source_switch_ip_hint = str(data.get('source_switch_ip', '')).strip()
            binding = get_terminal_binding_record(data['query'], source_switch_ip_hint or None)
            target_switch_ip = normalize_ip(data['target_switch_ip'], '目标交换机 IP')
            target_interface = str(data['target_interface']).strip()
            if not target_interface:
                raise ValueError('目标端口不能为空')

            source_switch_ip = normalize_ip(binding['switch_ip'], '源交换机 IP')
            source_interface = str(binding['port']).strip()
            source_ip = normalize_ip(binding['ip_address'], '源绑定 IP')
            source_mac = normalize_mac(binding['mac_address'], '源绑定 MAC')
            assert_no_ip_conflict(source_ip, source_mac)
            source_mode = normalize_mode(binding.get('mode', 'access'))
            source_vlan = str(binding.get('vlan') or '').strip()
            target_mode = normalize_mode(data.get('target_mode') or source_mode)
            target_vlan = data.get('target_vlan')
            if str(target_vlan or '').strip():
                target_vlan = normalize_vlan(target_vlan)
            elif target_mode == 'access':
                target_vlan = normalize_vlan(source_vlan, allow_empty=False)
            else:
                target_vlan = normalize_vlan(source_vlan or data.get('target_vlan'), allow_empty=False)

            if source_switch_ip == target_switch_ip and source_interface == target_interface:
                raise ValueError('源端口与目标端口相同，无需执行迁移')

            source_runtime = get_switch_runtime_data(source_switch_ip)
            target_runtime = get_switch_runtime_data(target_switch_ip)

            source_details = f"{source_switch_ip} {source_interface} VLAN:{source_vlan or '-'} 模式:{source_mode}"
            target_details = f"{target_switch_ip} {target_interface} VLAN:{target_vlan or '-'} 模式:{target_mode}"

            if bool(data.get('dry_run')):
                plan_log = (
                    "[终端迁移试运行]\n"
                    "本次只生成计划，不登录交换机，不下发任何配置。\n\n"
                    f"终端: IP {source_ip} / MAC {source_mac}\n"
                    f"源位置: {source_details}\n"
                    f"目标位置: {target_details}\n\n"
                    "预计执行步骤:\n"
                    f"1. 登录源交换机 {source_switch_ip}，检查源端口 {source_interface} 是否受保护。\n"
                    f"2. 在源端口删除 {source_ip} / {source_mac} 绑定。\n"
                    "3. 只读复核旧端口是否仍存在相同 IP+MAC 绑定。\n"
                    f"4. 登录目标交换机 {target_switch_ip}，检查目标端口 {target_interface} 是否受保护。\n"
                    "5. 按目标端口现有配置差异化下发 VLAN、源绑定校验和 IP/MAC 绑定。\n"
                    "6. 成功后更新已绑定终端列表。\n"
                )
                db.log_operation(
                    current_user.username,
                    client_ip,
                    target_switch_ip,
                    "终端迁移试运行",
                    f"MAC:{source_mac} | IP:{source_ip} | 源:{source_details} -> 目标:{target_details}",
                    "成功",
                )
                return jsonify(
                    {
                        'status': 'success',
                        'msg': '终端迁移试运行完成，未下发配置',
                        'data': {
                            'source': binding,
                            'target': {
                                'switch_ip': target_switch_ip,
                                'port': target_interface,
                                'vlan': target_vlan,
                                'mode': target_mode,
                            },
                            'dry_run': True,
                        },
                        'log': plan_log.replace('\n', '<br>'),
                    }
                )

            source_mgr = get_manager(source_runtime)
            target_mgr = get_manager(target_runtime)
            assert_interface_not_protected(source_mgr, source_interface)
            target_port_info = assert_interface_not_protected(target_mgr, target_interface)

            old_log = source_mgr.delete_port_binding(source_interface, source_ip, source_mac, source_mode, source_vlan)
            source_mgr_verify = get_manager(source_runtime)
            if port_has_binding(source_mgr_verify, source_interface, source_ip, source_mac):
                raise ValueError(
                    f"旧端口解绑后复核失败：{source_switch_ip} {source_interface} 仍存在 "
                    f"{source_ip} / {source_mac}，已停止迁移。请检查交换机返回信息或手动清理。"
                )
            rollback_needed = True
            try:
                new_log = target_mgr.configure_port_binding(
                    target_interface,
                    target_vlan,
                    source_ip,
                    source_mac,
                    target_mode,
                    current_config=target_port_info.get('_raw_config'),
                )
            except Exception:
                if rollback_needed:
                    try:
                        source_mgr_rollback = get_manager(source_runtime)
                        source_mgr_rollback.configure_port_binding(
                            source_interface,
                            source_vlan,
                            source_ip,
                            source_mac,
                            source_mode,
                        )
                    except Exception:
                        pass
                raise

            save_binding_state(target_switch_ip, target_interface, target_vlan, source_ip, source_mac, target_mode)
            details = f"终端迁移 | MAC:{source_mac} | IP:{source_ip} | 源:{source_details} -> 目标:{target_details}"
            db.log_operation(current_user.username, client_ip, target_switch_ip, "终端迁移", details, "成功")

            combined_log = (
                "[旧端口清理]\n"
                f"{format_switch_log(old_log)}\n\n"
                "[新端口部署]\n"
                f"{format_switch_log(new_log)}"
            )
            return jsonify(
                {
                    'status': 'success',
                    'msg': '终端迁移完成',
                    'data': {
                        'source': binding,
                        'target': {
                            'switch_ip': target_switch_ip,
                            'port': target_interface,
                            'vlan': target_vlan,
                            'mode': target_mode,
                        },
                    },
                    'log': combined_log.replace('\n', '<br>'),
                }
            )
        except ValueError as e:
            if 'client_ip' in locals():
                db.log_operation(
                    current_user.username,
                    client_ip,
                    data.get('target_switch_ip', 'Unknown') if 'data' in locals() else 'Unknown',
                    "终端迁移",
                    f"查询:{data.get('query', '') if 'data' in locals() else ''} | 报错: {str(e)}",
                    "失败",
                )
            return json_error(str(e))
        except Exception as e:
            if 'client_ip' in locals():
                db.log_operation(
                    current_user.username,
                    client_ip,
                    data.get('target_switch_ip', 'Unknown') if 'data' in locals() else 'Unknown',
                    "终端迁移",
                    f"查询:{data.get('query', '') if 'data' in locals() else ''} | 报错: {str(e)}",
                    "失败",
                )
            return internal_error('终端迁移失败，请检查设备状态和参数', e)

    return bp
