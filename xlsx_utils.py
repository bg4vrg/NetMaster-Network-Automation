import io

from flask import send_file


def autosize_worksheet(sheet, min_width=12, max_width=34):
    for column in sheet.columns:
        values = [str(cell.value or '') for cell in column]
        width = min(max(max((len(value) for value in values), default=0) + 4, min_width), max_width)
        sheet.column_dimensions[column[0].column_letter].width = width


def send_xlsx_workbook(wb, filename):
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
