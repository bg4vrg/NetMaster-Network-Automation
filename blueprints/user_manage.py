import sqlite3

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required


def create_user_manage_blueprint(
    db,
    get_json_data,
    require_fields,
    validate_password_policy,
    json_error,
    internal_error,
    permission_required,
):
    bp = Blueprint('user_manage', __name__)

    def role_label(role):
        return '系统管理员' if role == 'admin' else '运维操作员'

    def status_label(status):
        return '禁用' if status == 'disabled' else '启用'

    @bp.route('/api/change_password', methods=['POST'])
    @login_required
    def change_pass_api():
        try:
            data = get_json_data()
            new_pass = validate_password_policy(data.get('new_password'))
            db.change_password(current_user.username, new_pass)
            return jsonify({'status': 'success'})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('修改密码失败，请稍后重试', e)

    @bp.route('/api/users/add', methods=['POST'])
    @login_required
    @permission_required('user.manage')
    def api_add_user():
        try:
            data = get_json_data()
            require_fields(data, ['username', 'password', 'role'])
            password = validate_password_policy(data.get('password'))
            role = db.normalize_user_role(data.get('role'))
            db.add_user(data.get('username'), password, role, data.get('display_name'))
            display_name = str(data.get('display_name') or '').strip() or '-'
            db.log_operation(
                current_user.username,
                request.remote_addr,
                'SYSTEM',
                '新增用户',
                f"目标用户:{data.get('username')} | 显示名:{display_name} | 角色:{role_label(role)}",
                '成功',
            )
            return jsonify({'status': 'success'})
        except sqlite3.IntegrityError:
            return json_error('用户名已存在')
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('新增用户失败，请稍后重试', e)

    @bp.route('/api/users/update', methods=['POST'])
    @login_required
    @permission_required('user.manage')
    def api_update_user():
        try:
            data = get_json_data()
            require_fields(data, ['id'])
            user_id = int(data.get('id'))
            target = db.get_user_by_id(user_id)
            if not target:
                return json_error('用户不存在')
            if user_id == int(current_user.id) and (
                data.get('status') == 'disabled' or data.get('role') == 'operator'
            ):
                return json_error('不能禁用或降级当前登录的系统管理员')
            role = db.normalize_user_role(data.get('role')) if 'role' in data else None
            status = db.normalize_user_status(data.get('status')) if 'status' in data else None
            target_role = target['role'] if 'role' in target.keys() else 'operator'
            target_status = target['status'] if 'status' in target.keys() else 'active'
            would_remove_admin = target_role == 'admin' and target_status == 'active' and (
                role == 'operator' or status == 'disabled'
            )
            if would_remove_admin and db.count_active_admins(exclude_user_id=user_id) == 0:
                return json_error('至少需要保留一个启用状态的系统管理员')
            old_role = target_role
            old_status = target_status
            old_display_name = target['display_name'] if 'display_name' in target.keys() else ''
            new_display_name = data.get('display_name') if 'display_name' in data else old_display_name
            db.update_user(
                user_id,
                role=role,
                status=status,
                display_name=data.get('display_name') if 'display_name' in data else None,
            )
            detail_parts = [
                f"目标用户:{target['username']}",
                f"ID:{user_id}",
            ]
            if role is not None and role != old_role:
                detail_parts.append(f"角色:{role_label(old_role)} -> {role_label(role)}")
            if status is not None and status != old_status:
                detail_parts.append(f"状态:{status_label(old_status)} -> {status_label(status)}")
            if 'display_name' in data and str(new_display_name or '').strip() != str(old_display_name or '').strip():
                detail_parts.append(f"显示名:{old_display_name or '-'} -> {str(new_display_name or '').strip() or '-'}")
            if len(detail_parts) == 2:
                detail_parts.append('无字段变化')
            db.log_operation(
                current_user.username,
                request.remote_addr,
                'SYSTEM',
                '更新用户',
                ' | '.join(detail_parts),
                '成功',
            )
            return jsonify({'status': 'success'})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('更新用户失败，请稍后重试', e)

    @bp.route('/api/users/reset_password', methods=['POST'])
    @login_required
    @permission_required('user.manage')
    def api_reset_user_password():
        try:
            data = get_json_data()
            require_fields(data, ['id', 'password'])
            password = validate_password_policy(data.get('password'))
            user_id = int(data.get('id'))
            target = db.get_user_by_id(user_id)
            if not target:
                return json_error('用户不存在')
            db.reset_user_password(user_id, password)
            db.log_operation(
                current_user.username,
                request.remote_addr,
                'SYSTEM',
                '重置用户密码',
                f"目标用户:{target['username']} | ID:{user_id}",
                '成功',
            )
            return jsonify({'status': 'success'})
        except ValueError as e:
            return json_error(str(e))
        except Exception as e:
            return internal_error('重置用户密码失败，请稍后重试', e)

    return bp
