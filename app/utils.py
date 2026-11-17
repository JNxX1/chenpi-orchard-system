"""表单解析与模板辅助函数。"""
from datetime import date, datetime


class FormError(ValueError):
    pass


def get_str(form, key, label, required=False, max_len=200):
    val = (form.get(key) or "").strip()
    if required and not val:
        raise FormError(f"{label}不能为空")
    if len(val) > max_len:
        raise FormError(f"{label}长度不能超过{max_len}个字符")
    return val or None


def get_float(form, key, label, required=False, min_value=0.0):
    raw = (form.get(key) or "").strip()
    if not raw:
        if required:
            raise FormError(f"{label}不能为空")
        return None
    try:
        val = float(raw)
    except ValueError:
        raise FormError(f"{label}必须是数字")
    if min_value is not None and val < min_value:
        raise FormError(f"{label}不能小于{min_value:g}")
    return val


def get_int(form, key, label, required=False, min_value=0):
    raw = (form.get(key) or "").strip()
    if not raw:
        if required:
            raise FormError(f"{label}不能为空")
        return None
    try:
        val = int(raw)
    except ValueError:
        raise FormError(f"{label}必须是整数")
    if min_value is not None and val < min_value:
        raise FormError(f"{label}不能小于{min_value}")
    return val


def get_date(form, key, label, required=False):
    raw = (form.get(key) or "").strip()
    if not raw:
        if required:
            raise FormError(f"{label}不能为空")
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise FormError(f"{label}格式应为 YYYY-MM-DD")


def get_choice(form, key, label, choices, default=None):
    val = (form.get(key) or "").strip() or default
    if val not in choices:
        raise FormError(f"{label}取值无效")
    return val


def fmt_num(value, digits=2):
    if value is None:
        return "—"
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.{digits}f}"


def register_template_helpers(app):
    app.jinja_env.filters["num"] = fmt_num
    app.jinja_env.filters["dt"] = lambda v: v.strftime("%Y-%m-%d %H:%M") if v else "—"
    app.jinja_env.filters["d"] = lambda v: v.strftime("%Y-%m-%d") if v else "—"
    app.jinja_env.filters["dict_without_page"] = lambda d: {k: v for k, v in d.items() if k != "page"}
    app.jinja_env.globals["today"] = date.today
