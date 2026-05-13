from flask import Blueprint, jsonify, request
from flask_login import login_required

from background_tasks import get_task, list_tasks


def create_task_runtime_blueprint(permission_required):
    bp = Blueprint('task_runtime', __name__)

    @bp.route('/api/runtime_tasks', methods=['GET'])
    @login_required
    @permission_required('task.view')
    def api_runtime_tasks():
        limit = request.args.get('limit', '50')
        category = str(request.args.get('category', '')).strip()
        return jsonify({'status': 'success', 'data': list_tasks(limit=limit, category=category)})

    @bp.route('/api/runtime_tasks/<task_id>', methods=['GET'])
    @login_required
    @permission_required('task.view')
    def api_runtime_task_detail(task_id):
        task = get_task(task_id)
        if not task:
            return jsonify({'status': 'error', 'msg': '任务不存在或已过期'}), 404
        return jsonify({'status': 'success', 'data': task})

    return bp
