import openpyxl

from flask import Blueprint, jsonify
from flask_login import login_required


def create_asset_user_read_blueprint(db, send_xlsx_workbook, autosize_worksheet, internal_error, permission_required):
    bp = Blueprint('asset_user_read', __name__)

    @bp.route('/api/switches', methods=['GET'])
    @login_required
    def list_switches():
        return jsonify({'status': 'success', 'data': db.get_all_switches()})

    @bp.route('/api/switches/import_template', methods=['GET'])
    @login_required
    def download_switch_import_template():
        try:
            wb = openpyxl.Workbook()
            sheet = wb.active
            sheet.title = 'switch_import_template'
            sheet.append(['设备名称', 'IP地址', '端口', '用户名', '密码', '厂商', '角色'])
            sheet.append(['示例-接入交换机', '10.139.100.205', 22, 'admin', '请填写密码', 'h3c', 'access'])
            sheet.append(['示例-备份设备', '10.139.100.206', 22, 'admin', '请填写密码', 'h3c', 'backup'])
            sheet['G1'].comment = openpyxl.comments.Comment('角色可填 access 或 backup；不填时默认 access。', 'NetMaster')
            sheet.freeze_panes = 'A2'
            for cell in sheet[1]:
                cell.font = openpyxl.styles.Font(bold=True, color='FFFFFF')
                cell.fill = openpyxl.styles.PatternFill('solid', fgColor='206BC4')
            autosize_worksheet(sheet)
            return send_xlsx_workbook(wb, 'switch_import_template.xlsx')
        except Exception as e:
            return internal_error('生成设备导入模板失败，请稍后重试', e)

    @bp.route('/api/users', methods=['GET'])
    @login_required
    @permission_required('user.manage')
    def api_users():
        return jsonify({'status': 'success', 'data': db.list_users()})

    return bp
