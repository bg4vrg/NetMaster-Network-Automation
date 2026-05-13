import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from background_tasks import submit_task, update_task


def create_profile_health_blueprint(db, get_json_data, get_manager, internal_error, permission_required):
    bp = Blueprint('profile_health', __name__)

    def build_deep_health_results(limit, task_id=None):
        switches = db.get_all_switches()[:limit]
        results = []
        for index, sw in enumerate(switches, start=1):
            if task_id:
                update_task(
                    task_id,
                    message=f"正在检查 {sw.get('name') or sw.get('ip')}",
                    progress=10 + int(index / max(len(switches), 1) * 80),
                )
            item = {'ip': sw['ip'], 'name': sw.get('name', ''), 'vendor': sw.get('vendor', 'h3c'), 'status': 'unknown', 'detail': ''}
            try:
                mgr = get_manager({'ip': sw['ip'], 'user': sw['username'], 'pass': sw['password'], 'port': sw['port'], 'vendor': sw.get('vendor', 'h3c')})
                info = mgr.get_device_info()
                item['status'] = 'success'
                item['detail'] = info
            except Exception as exc:
                msg = str(exc)
                item['status'] = 'failed'
                if 'Authentication' in msg:
                    item['detail'] = '认证失败'
                elif 'timed out' in msg.lower() or 'timeout' in msg.lower():
                    item['detail'] = '连接超时'
                else:
                    item['detail'] = msg[:300]
            results.append(item)
        return {'checked': len(results), 'results': results}

    @bp.route('/api/port_profiles', methods=['GET'])
    @login_required
    def api_port_profiles():
        try:
            limit = max(1, min(int(request.args.get('limit') or 20), 100))
            offset = max(0, int(request.args.get('offset') or 0))
            query = str(request.args.get('q') or '').strip()
            risk_filter = str(request.args.get('risk') or '').strip()
            state_filter = str(request.args.get('state') or '').strip()
            if risk_filter or state_filter:
                rows = db.get_port_profiles()
                page_meta = {'total': len(rows), 'limit': limit, 'offset': offset, 'has_more': False}
            else:
                page = db.get_port_profiles_page(limit=limit, offset=offset, query=query)
                rows = page['rows']
                page_meta = {
                    'total': page['total'],
                    'limit': page['limit'],
                    'offset': page['offset'],
                    'has_more': page['has_more'],
                }
            now = datetime.datetime.now()
            for row in rows:
                tags = []
                score = 0
                terminal_count = int(row.get('terminal_count') or 0)
                vlan_count = len([v for v in str(row.get('vlans') or '').split(',') if v.strip()])
                modes = str(row.get('modes') or '').lower()
                snapshot_mode = str(row.get('snapshot_mode') or '').lower()
                combined_modes = ','.join([m for m in [modes, snapshot_mode] if m])
                snapshot_status = str(row.get('snapshot_status') or '').lower()
                snapshot_description = str(row.get('snapshot_description') or '').strip()
                if 'down' in snapshot_status and terminal_count > 0:
                    tags.append('端口Down仍有绑定')
                    score += 40
                if terminal_count >= 5:
                    tags.append('高密度')
                    score += 40
                elif terminal_count >= 3:
                    tags.append('多终端')
                    score += 25
                if vlan_count >= 3:
                    tags.append('多VLAN')
                    score += 30
                elif vlan_count >= 2:
                    tags.append('双VLAN')
                    score += 20
                if 'trunk' in combined_modes:
                    tags.append('Trunk')
                    score += 20
                if 'access' in combined_modes and 'trunk' in combined_modes:
                    tags.append('模式混用')
                    score += 35
                if not snapshot_description and terminal_count >= 2:
                    tags.append('缺少端口描述')
                    score += 10
                last_update = row.get('last_update') or ''
                try:
                    dt = datetime.datetime.strptime(last_update[:19], '%Y-%m-%d %H:%M:%S')
                    stale_days = (now - dt).days
                    row['stale_days'] = stale_days
                    if stale_days > 7:
                        tags.append('超7天未巡检')
                        score += 25
                    elif stale_days > 3:
                        tags.append('超3天未巡检')
                        score += 15
                except Exception:
                    row['stale_days'] = None
                row['risk_tags'] = tags
                row['risk_score'] = min(score, 100)
                row['risk_level'] = 'high' if score >= 60 else ('medium' if score >= 25 else 'low')
                suggestions = []
                if '端口Down仍有绑定' in tags:
                    suggestions.append('优先核查端口是否废弃或终端离线')
                if terminal_count >= 3:
                    suggestions.append('核查该端口是否为汇聚/AP/小交换机口')
                if vlan_count >= 2:
                    suggestions.append('确认多 VLAN 是否符合端口规划')
                if 'trunk' in combined_modes:
                    suggestions.append('下发前优先复核 Trunk 业务范围')
                if '模式混用' in tags:
                    suggestions.append('清理同端口 Access/Trunk 混用记录')
                if '缺少端口描述' in tags:
                    suggestions.append('补充端口描述，便于后续定位')
                if row.get('stale_days') and row['stale_days'] > 3:
                    suggestions.append('建议刷新终端绑定状态或标记巡检')
                row['suggestion'] = '；'.join(suggestions) if suggestions else '维持观察'
            if risk_filter or state_filter:
                filtered_rows = []
                query_lower = query.lower()
                for row in rows:
                    stale_days = int(row.get('stale_days') or 0)
                    terminal_count = int(row.get('terminal_count') or 0)
                    modes = f"{row.get('modes') or ''} {row.get('snapshot_mode') or ''}".lower()
                    snapshot_status = str(row.get('snapshot_status') or '').lower()
                    snapshot_description = str(row.get('snapshot_description') or '').strip()
                    if risk_filter and row.get('risk_level') != risk_filter:
                        continue
                    if state_filter == 'stale' and stale_days <= 3:
                        continue
                    if state_filter == 'dense' and terminal_count < 3:
                        continue
                    if state_filter == 'trunk' and 'trunk' not in modes:
                        continue
                    if state_filter == 'down-bound' and not ('down' in snapshot_status and terminal_count > 0):
                        continue
                    if state_filter == 'no-desc' and not ((not snapshot_description) and terminal_count >= 2):
                        continue
                    if query_lower:
                        tags = ' '.join(row.get('risk_tags') or [])
                        text = f"{row.get('switch_name') or ''} {row.get('switch_ip') or ''} {row.get('port') or ''} {row.get('vlans') or ''} {row.get('modes') or ''} {row.get('snapshot_mode') or ''} {row.get('snapshot_description') or ''} {row.get('suggestion') or ''} {tags}".lower()
                        if query_lower not in text:
                            continue
                    filtered_rows.append(row)
                rows = filtered_rows
                page_meta['total'] = len(rows)
            rows.sort(key=lambda item: (item.get('risk_score') or 0, item.get('terminal_count') or 0), reverse=True)
            if risk_filter or state_filter:
                rows = rows[offset:offset + limit]
                page_meta['has_more'] = offset + len(rows) < page_meta['total']
            return jsonify({'status': 'success', 'data': rows, 'meta': page_meta})
        except Exception as e:
            return internal_error('获取端口画像失败，请稍后重试', e)

    @bp.route('/api/port_profiles/confirm', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def api_confirm_port_profiles():
        try:
            data = get_json_data()
            items = data.get('items') or []
            if not isinstance(items, list) or not items:
                return jsonify({'status': 'error', 'msg': '请选择需要标记巡检的端口画像记录'}), 400
            clean_items = []
            for item in items[:200]:
                switch_ip = str(item.get('switch_ip') or '').strip()
                port = str(item.get('port') or '').strip()
                if switch_ip and port:
                    clean_items.append({'switch_ip': switch_ip, 'port': port})
            if not clean_items:
                return jsonify({'status': 'error', 'msg': '没有可标记巡检的端口记录'}), 400
            result = db.confirm_port_profiles(clean_items)
            db.log_operation(
                current_user.username,
                request.remote_addr,
                'LOCAL',
                '标记端口已巡检',
                f"端口数:{len(clean_items)} | 更新绑定记录:{result.get('confirmed', 0)}",
                '成功',
            )
            return jsonify({'status': 'success', 'data': result})
        except Exception as e:
            return internal_error('标记端口巡检失败，请稍后重试', e)

    @bp.route('/api/deep_health_check', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def api_deep_health_check():
        try:
            data = get_json_data()
            limit = max(1, min(int(data.get('limit') or 10), 50))
            return jsonify({'status': 'success', 'data': build_deep_health_results(limit)})
        except Exception as e:
            return internal_error('深度在线健康检查失败', e)

    @bp.route('/api/deep_health_check/start', methods=['POST'])
    @login_required
    @permission_required('access.write')
    def api_deep_health_check_start():
        try:
            data = get_json_data()
            limit = max(1, min(int(data.get('limit') or 10), 50))

            def run(task_id):
                return build_deep_health_results(limit, task_id=task_id)

            task = submit_task(
                f'深度在线健康检查 {limit} 台',
                run,
                category='deep_health',
                actor=current_user.username,
                target=f'{limit} switches',
            )
            return jsonify({'status': 'success', 'data': task, 'task_id': task['id']})
        except Exception as e:
            return internal_error('启动深度在线健康检查失败', e)

    return bp
