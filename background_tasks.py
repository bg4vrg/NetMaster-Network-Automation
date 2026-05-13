import datetime
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

import database as db


_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_TASKS = {}
_LOCK = threading.Lock()
_MAX_TASKS = 300


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _public_task(task):
    public = dict(task)
    public.pop('future', None)
    return public


def _persist_task(task):
    try:
        db.save_runtime_task(_public_task(task))
        db.trim_runtime_tasks(_MAX_TASKS)
    except Exception as exc:
        print(f"保存后台任务状态失败: {exc}")


def _trim_tasks_locked():
    if len(_TASKS) <= _MAX_TASKS:
        return
    removable = [
        (task.get('created_at') or '', task_id)
        for task_id, task in _TASKS.items()
        if task.get('status') in ('success', 'failed', 'cancelled')
    ]
    removable.sort()
    for _, task_id in removable[: max(0, len(_TASKS) - _MAX_TASKS)]:
        _TASKS.pop(task_id, None)


def create_task(name, category='general', actor='', target='', metadata=None):
    task_id = uuid.uuid4().hex
    task = {
        'id': task_id,
        'name': name,
        'category': category,
        'status': 'queued',
        'message': '任务已排队',
        'progress': 0,
        'actor': actor,
        'target': target,
        'metadata': metadata or {},
        'result': None,
        'error': '',
        'traceback': '',
        'created_at': _now(),
        'started_at': '',
        'finished_at': '',
    }
    with _LOCK:
        _TASKS[task_id] = task
        _trim_tasks_locked()
        snapshot = _public_task(task)
    _persist_task(snapshot)
    return task_id


def update_task(task_id, **changes):
    snapshot = None
    with _LOCK:
        task = _TASKS.get(task_id)
        if not task:
            task = db.get_runtime_task(task_id)
            if not task:
                return None
            _TASKS[task_id] = task
        if 'progress' in changes:
            changes['progress'] = max(0, min(100, int(changes['progress'] or 0)))
        task.update(changes)
        snapshot = _public_task(task)
    _persist_task(snapshot)
    return snapshot


def get_task(task_id):
    with _LOCK:
        task = _TASKS.get(task_id)
        if task:
            return _public_task(task)
    return db.get_runtime_task(task_id)


def list_tasks(limit=50, category=''):
    limit = max(1, min(int(limit or 50), 300))
    rows = db.list_runtime_tasks(limit=limit, category=category)
    merged = {row.get('id'): row for row in rows if row}
    with _LOCK:
        memory_rows = [_public_task(task) for task in _TASKS.values()]
    for row in memory_rows:
        if category and row.get('category') != category:
            continue
        merged[row.get('id')] = row
    result = list(merged.values())
    result.sort(key=lambda row: (row.get('created_at') or '', row.get('updated_at') or ''), reverse=True)
    return result[:limit]


def submit_task(name, func, *, category='general', actor='', target='', metadata=None, args=None, kwargs=None):
    task_id = create_task(name, category=category, actor=actor, target=target, metadata=metadata)
    args = args or ()
    kwargs = kwargs or {}

    def runner():
        update_task(task_id, status='running', message='任务执行中', progress=5, started_at=_now())
        try:
            result = func(task_id, *args, **kwargs)
            snapshot = get_task(task_id) or {}
            progress = snapshot.get('progress') or 100
            update_task(
                task_id,
                status='success',
                message='任务完成',
                progress=max(progress, 100),
                result=result,
                finished_at=_now(),
            )
            return result
        except Exception as exc:
            update_task(
                task_id,
                status='failed',
                message='任务失败',
                progress=100,
                error=str(exc),
                traceback=traceback.format_exc(),
                finished_at=_now(),
            )
            raise

    future = _EXECUTOR.submit(runner)
    with _LOCK:
        if task_id in _TASKS:
            _TASKS[task_id]['future'] = future
    return get_task(task_id)
