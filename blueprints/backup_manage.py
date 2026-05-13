import datetime
import os

from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user, login_required
from background_tasks import submit_task, update_task


def create_backup_manage_blueprint(
    db,
    H3CManager,
    HuaweiManager,
    BACKUP_ROOT,
    create_data_package,
    restore_data_package,
    preview_data_package,
    backup_current_db_key,
    import_legacy_switch_assets,
    import_bindings_from_backup_files,
    get_json_data,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('backup_manage', __name__)

    def run_batch_backup(actor, remote_addr, task_id=None):
        switches = db.get_all_switches()
        if not switches:
            return {'status': 'error', 'msg': '数据库中没有设备，请先添加！', 'log': '数据库中没有设备，请先添加！'}

        today = datetime.datetime.now().strftime("%Y-%m-%d")
        today_dir = os.path.join(BACKUP_ROOT, today)
        if not os.path.exists(today_dir):
            os.makedirs(today_dir)

        log_messages = [f"开始执行批量备份，共 {len(switches)} 台设备..."]
        success_count, fail_count = 0, 0

        for index, sw in enumerate(switches, start=1):
            safe_name = sw['name'].replace('/', '_').replace('\\', '_').replace(' ', '_')
            target_ip = sw['ip']
            vendor = sw.get('vendor', 'h3c').lower()
            if task_id:
                update_task(
                    task_id,
                    message=f"正在备份 {sw['name']} ({target_ip})",
                    progress=5 + int(index / max(len(switches), 1) * 85),
                )

            log_messages.append(f"正在连接: {sw['name']} ({target_ip}) [{vendor.upper()}]...")

            try:
                if vendor == 'huawei':
                    mgr = HuaweiManager(target_ip, sw['username'], sw['password'], sw['port'])
                else:
                    mgr = H3CManager(target_ip, sw['username'], sw['password'], sw['port'])

                config_text = mgr.get_full_config()

                time_suffix = datetime.datetime.now().strftime("%H%M")
                filename = f"{safe_name}_{target_ip}_{time_suffix}.cfg"
                filepath = os.path.join(today_dir, filename)

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(config_text)

                success_count += 1
                log_messages.append(f"<span class='status-permit'>备份成功</span>: 已保存至 {filename}")

            except Exception as e:
                fail_count += 1
                error_msg = str(e)
                if "Authentication failed" in error_msg:
                    error_msg = "认证失败(密码错误)"
                elif "timed out" in error_msg:
                    error_msg = "连接超时"
                log_messages.append(f"<span class='status-deny'>[{target_ip}] 备份失败</span>: {error_msg}")
                try:
                    db.log_operation(actor, remote_addr, target_ip, "单台配置备份", f"失败原因: {error_msg}", "失败")
                except Exception:
                    pass

        final_msg = f"<br><b>任务结束</b><br>成功: {success_count} 台<br>失败: {fail_count} 台<br>文件保存于: {today_dir}"
        full_log = "<br>".join(log_messages) + final_msg

        try:
            details = f"手动触发批量备份结束。成功: {success_count}, 失败: {fail_count}。存储路径: {today_dir}"
            status = "成功" if fail_count == 0 else ("部分失败" if success_count > 0 else "全部失败")
            db.log_operation(actor, remote_addr, "ALL_SWITCHES", "手动批量备份", details, status)
        except Exception:
            pass

        return {
            'status': 'success',
            'log': full_log,
            'success_count': success_count,
            'fail_count': fail_count,
            'target_dir': today_dir,
        }

    @bp.route('/api/data_export', methods=['GET'])
    @login_required
    @permission_required('backup.manage')
    def api_data_export():
        try:
            memory_file, filename = create_data_package()
            return send_file(memory_file, as_attachment=True, download_name=filename, mimetype='application/zip')
        except Exception as e:
            return internal_error('导出数据包失败，请稍后重试', e)

    @bp.route('/api/data_import', methods=['POST'])
    @login_required
    @permission_required('backup.manage')
    def api_data_import():
        try:
            upload = request.files.get('file')
            if not upload or not upload.filename:
                return json_error('请选择要导入的数据包')
            backup_dir = restore_data_package(upload)
            return jsonify(
                {
                    'status': 'success',
                    'msg': '数据包已导入。当前服务仍可能保留旧状态，建议立即重启 run_server.py 后再继续操作。',
                    'data': {'backup_dir': backup_dir},
                }
            )
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('导入数据包失败，请检查 zip 文件', e)

    @bp.route('/api/data_import_preview', methods=['POST'])
    @login_required
    @permission_required('backup.manage')
    def api_data_import_preview():
        try:
            upload = request.files.get('file')
            if not upload or not upload.filename:
                return json_error('请选择要预览的数据包')
            return jsonify({'status': 'success', 'data': preview_data_package(upload)})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('预览数据包失败，请检查 zip 文件', e)

    @bp.route('/api/legacy_assets_preview', methods=['POST'])
    @login_required
    @permission_required('backup.manage')
    def api_legacy_assets_preview():
        try:
            upload = request.files.get('file')
            if not upload or not upload.filename:
                return json_error('请选择旧版本 net_assets.db')
            result = import_legacy_switch_assets(upload, request.files.get('key'), apply=False)
            return jsonify({'status': 'success', 'data': result})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('预览旧版本资产失败，请检查数据库文件', e)

    @bp.route('/api/legacy_assets_import', methods=['POST'])
    @login_required
    @permission_required('backup.manage')
    def api_legacy_assets_import():
        try:
            upload = request.files.get('file')
            if not upload or not upload.filename:
                return json_error('请选择旧版本 net_assets.db')
            backup_info = backup_current_db_key('before_legacy_assets_import')
            result = import_legacy_switch_assets(upload, request.files.get('key'), apply=True)
            result['pre_import_backup'] = backup_info
            db.log_operation(
                current_user.username,
                request.remote_addr,
                'LOCAL',
                '导入旧版本交换机资产',
                f"识别:{result['total']} 新增:{result['created']} 更新:{result['updated']} 跳过:{result['skipped']} 备份:{backup_info['backup_dir']}",
                '成功',
            )
            return jsonify({'status': 'success', 'data': result})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('导入旧版本资产失败，请检查数据库文件', e)

    @bp.route('/api/offline_binding_import', methods=['POST'])
    @login_required
    @permission_required('backup.manage')
    def api_offline_binding_import():
        try:
            data = get_json_data()
            apply_import = bool(data.get('apply'))
            result = import_bindings_from_backup_files(limit=int(data.get('limit') or 2000), apply=apply_import)
            db.log_operation(
                current_user.username,
                request.remote_addr,
                "BACKUPS",
                "离线导入绑定库",
                f"apply={apply_import} | files={result['files']} | found={result['found']} | unique={result['unique_terminals']} | duplicates={result['duplicates']} | created={result['created']} | updated={result['updated']} | unchanged={result['unchanged']} | errors={len(result['errors'])}",
                "成功" if not result['errors'] else "部分失败",
            )
            return jsonify({'status': 'success', 'data': result})
        except Exception as e:
            return internal_error('离线导入绑定库失败，请检查备份配置', e)

    @bp.route('/batch_backup', methods=['POST'])
    @login_required
    @permission_required('backup.manage')
    def batch_backup():
        result = run_batch_backup(current_user.username, request.remote_addr)
        return jsonify(result)

    @bp.route('/batch_backup/start', methods=['POST'])
    @login_required
    @permission_required('backup.manage')
    def batch_backup_start():
        try:
            actor = current_user.username
            remote_addr = request.remote_addr

            def run(task_id):
                return run_batch_backup(actor, remote_addr, task_id=task_id)

            task = submit_task(
                '手动批量备份配置',
                run,
                category='batch_backup',
                actor=actor,
                target='ALL_SWITCHES',
            )
            return jsonify({'status': 'success', 'data': task, 'task_id': task['id']})
        except Exception as e:
            return internal_error('启动批量备份任务失败', e)

    return bp
