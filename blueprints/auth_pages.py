from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user


def create_auth_pages_blueprint(db, User):
    bp = Blueprint('auth_pages', __name__)

    @bp.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            user_data = db.verify_user(username, password)
            if user_data:
                user = User(
                    id=user_data['id'],
                    username=user_data['username'],
                    role=user_data['role'] if 'role' in user_data.keys() else 'operator',
                    display_name=user_data['display_name'] if 'display_name' in user_data.keys() else user_data['username'],
                )
                login_user(user)
                return redirect(url_for('index'))

            db.log_operation(
                username or '-',
                request.remote_addr,
                'SYSTEM',
                '登录失败',
                '用户名、密码错误、账号禁用或临时锁定',
                '失败',
            )
            return render_template('login.html', error='用户名或密码错误')

        return render_template('login.html')

    @bp.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('auth_pages.login'))

    return bp
