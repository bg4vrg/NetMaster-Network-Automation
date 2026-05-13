import datetime
import os

from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler_service(
    *,
    db,
    h3c_manager_cls,
    huawei_manager_cls,
    backup_root,
    write_data_package_to_dir,
    run_mac_bindings_sync,
    collect_switch_alarm_report,
):
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    def auto_backup_task():
        print(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [系统调度] 开始执行凌晨自动备份...")
        switches = db.get_all_switches()
        if not switches:
            return

        today = datetime.datetime.now().strftime("%Y-%m-%d")
        today_dir = os.path.join(backup_root, today)
        os.makedirs(today_dir, exist_ok=True)

        success_count, fail_count = 0, 0
        save_success_count, save_fail_count = 0, 0
        auto_save_enabled = db.get_setting('auto_save_after_backup', '1') == '1'

        for sw in switches:
            safe_name = sw['name'].replace('/', '_').replace('\\', '_').replace(' ', '_')
            target_ip = sw['ip']
            vendor = sw.get('vendor', 'h3c').lower()

            try:
                if vendor == 'huawei':
                    mgr = huawei_manager_cls(target_ip, sw['username'], sw['password'], sw['port'])
                else:
                    mgr = h3c_manager_cls(target_ip, sw['username'], sw['password'], sw['port'])

                config_text = mgr.get_full_config()

                time_suffix = datetime.datetime.now().strftime("%H%M")
                filename = f"{safe_name}_{target_ip}_{time_suffix}.cfg"
                filepath = os.path.join(today_dir, filename)

                with open(filepath, 'w', encoding='utf-8') as file_obj:
                    file_obj.write(config_text)

                success_count += 1
                print(f"  [{vendor.upper()}] {target_ip} 备份成功 -> {filename}")
                if auto_save_enabled:
                    try:
                        mgr.save_config_to_device()
                        save_success_count += 1
                        db.log_operation(
                            "System(系统)",
                            "Localhost",
                            target_ip,
                            "定时备份后保存配置",
                            f"备份成功后执行保存配置。备份文件: {filename}",
                            "成功",
                        )
                        print(f"  [{vendor.upper()}] {target_ip} 保存配置成功")
                    except Exception as save_exc:
                        save_fail_count += 1
                        save_error = str(save_exc)
                        db.log_operation(
                            "System(系统)",
                            "Localhost",
                            target_ip,
                            "定时备份后保存配置",
                            f"备份文件: {filename} | 保存失败原因: {save_error}",
                            "失败",
                        )
                        print(f"  [{vendor.upper()}] {target_ip} 保存配置失败: {save_error}")
                else:
                    print(f"  [{vendor.upper()}] {target_ip} 已按系统设置跳过保存配置")
            except Exception as exc:
                fail_count += 1
                error_msg = str(exc)
                if "Authentication failed" in error_msg:
                    error_msg = "认证失败(密码错误)"
                elif "timed out" in error_msg:
                    error_msg = "连接超时"
                print(f"  [{vendor.upper()}] {target_ip} 备份失败: {error_msg}")
                try:
                    db.log_operation("System(系统)", "Localhost", target_ip, "定时单台备份", f"失败原因: {error_msg}", "失败")
                except Exception:
                    pass

        details = (
            f"任务结束。共 {len(switches)} 台。备份成功: {success_count}, 备份失败: {fail_count}。"
            f"备份后自动保存:{'开启' if auto_save_enabled else '关闭'}。"
            f"保存成功: {save_success_count}, 保存失败: {save_fail_count}。路径: {today_dir}"
        )
        status = "成功" if fail_count == 0 else ("部分失败" if success_count > 0 else "全部失败")

        try:
            db.log_operation("System(系统)", "Localhost", "ALL_SWITCHES", "定时自动备份", details, status)
        except Exception:
            pass
        print(f"[系统调度] 备份任务执行完毕：{details}\n")

    def auto_sync_mac_bindings_task():
        start_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n[{start_time}] [系统调度] 开始同步终端绑定信息...")
        try:
            result = run_mac_bindings_sync("System(系统)", "Localhost")
            if result['status'] == 'busy':
                print("[系统调度] 终端绑定信息同步跳过：已有同步任务正在执行")
                return
            data = result.get('data', {})
            details = (
                f"扫描交换机:{data.get('scanned_switches', 0)} | "
                f"发现绑定:{data.get('found', 0)} | "
                f"新增:{data.get('created', 0)} | "
                f"更新:{data.get('updated', 0)} | "
                f"未变:{data.get('unchanged', 0)} | "
                f"错误:{len(data.get('errors', []))}"
            )
            print(f"[系统调度] 终端绑定信息同步完成：{details}\n")
        except Exception as exc:
            print(f"[系统调度] 终端绑定信息同步失败：{exc}")
            try:
                db.log_operation(
                    "System(系统)",
                    "Localhost",
                    "ALL_SWITCHES",
                    "同步终端绑定信息",
                    f"定时同步失败: {exc}",
                    "失败",
                )
            except Exception:
                pass

    def auto_data_export_task():
        try:
            settings = db.get_system_settings()
            if not settings.get('auto_data_export_enabled'):
                print("[系统调度] 自动数据包导出已关闭")
                return
            path = write_data_package_to_dir(settings.get('auto_data_export_dir'))
            db.log_operation("System(系统)", "Localhost", "LOCAL", "自动导出数据包", f"导出路径: {path}", "成功")
            print(f"[系统调度] 自动数据包导出完成: {path}")
        except Exception as exc:
            print(f"[系统调度] 自动数据包导出失败：{exc}")
            try:
                db.log_operation("System(系统)", "Localhost", "LOCAL", "自动导出数据包", f"失败原因: {exc}", "失败")
            except Exception:
                pass

    def auto_collect_switch_alarm_logs_task():
        try:
            settings = db.get_system_settings()
            if not settings.get('auto_alarm_collect_enabled'):
                print("[系统调度] 自动采集交换机日志告警已关闭")
                return
            switches = db.get_all_switches()
            success_count = 0
            fail_count = 0
            for sw in switches:
                switch_ip = sw.get('ip')
                try:
                    collect_switch_alarm_report(switch_ip)
                    success_count += 1
                    print(f"[系统调度] 日志告警采集成功: {sw.get('name') or switch_ip}({switch_ip})")
                except Exception as exc:
                    fail_count += 1
                    db.add_switch_alarm_report(
                        switch_ip=switch_ip,
                        switch_name=sw.get('name', ''),
                        vendor=sw.get('vendor', ''),
                        status='失败',
                        error=str(exc)[:500],
                    )
                    print(f"[系统调度] 日志告警采集失败: {sw.get('name') or switch_ip}({switch_ip}) - {exc}")
            db.log_operation(
                "System(系统)",
                "Localhost",
                "ALL_SWITCHES",
                "定时采集交换机日志告警",
                f"成功 {success_count} 台，失败 {fail_count} 台",
                "成功" if fail_count == 0 else "部分失败",
            )
        except Exception as exc:
            print(f"[系统调度] 自动采集交换机日志告警失败：{exc}")
            try:
                db.log_operation("System(系统)", "Localhost", "ALL_SWITCHES", "定时采集交换机日志告警", f"失败原因: {exc}", "失败")
            except Exception:
                pass

    def configure_scheduler():
        settings = db.get_system_settings()
        scheduler.add_job(
            func=auto_backup_task,
            trigger="cron",
            hour=settings.get('auto_backup_hour', 2),
            minute=settings.get('auto_backup_minute', 37),
            id="auto_backup",
            replace_existing=True,
        )
        scheduler.add_job(
            func=auto_sync_mac_bindings_task,
            trigger="cron",
            hour=settings.get('auto_sync_hour', 3),
            minute=settings.get('auto_sync_minute', 20),
            id="auto_sync_mac_bindings",
            replace_existing=True,
        )
        scheduler.add_job(
            func=auto_data_export_task,
            trigger="cron",
            hour=settings.get('auto_data_export_hour', 4),
            minute=settings.get('auto_data_export_minute', 10),
            id="auto_data_export",
            replace_existing=True,
        )
        scheduler.add_job(
            func=auto_collect_switch_alarm_logs_task,
            trigger="cron",
            hour=settings.get('auto_alarm_collect_hour', 4),
            minute=settings.get('auto_alarm_collect_minute', 40),
            id="auto_alarm_collect",
            replace_existing=True,
        )

    def start_scheduler():
        configure_scheduler()
        if not scheduler.running:
            scheduler.start()

    return {
        'scheduler': scheduler,
        'configure_scheduler': configure_scheduler,
        'start_scheduler': start_scheduler,
    }
