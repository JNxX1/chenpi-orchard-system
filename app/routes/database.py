"""只读数据库浏览：在页面里直接看表结构、行数和记录（不提供任何写操作）。

设计约束：
- 只允许访问 SQLAlchemy inspector 返回的真实表名，表名来自白名单，杜绝 SQL 注入；
- 只执行 SELECT，页面明确提示“业务数据请到对应功能页修改”；
- 支持按关键字过滤（对所有文本列做 LIKE）与 CSV 导出，方便写论文时取数。
"""
import csv
import io
import json
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, Response, current_app, render_template, request
from sqlalchemy import inspect, text

from ..extensions import db

bp = Blueprint("database", __name__, url_prefix="/database")

PAGE_SIZE = 25

TABLE_LABELS = {
    "orchards": "果园",
    "plots": "地块",
    "inspection_plans": "巡检计划",
    "images": "巡检影像",
    "recognition_runs": "识别记录",
    "detections": "检测框",
    "yield_estimates": "估产记录",
    "harvest_records": "实际采收",
    "reports": "报表归档",
    "users": "系统用户",
}

# 分类用于列表色点、图表配色
TABLE_CATEGORY = {
    "orchards": ("业务档案", "#34c759"), "plots": ("业务档案", "#34c759"),
    "inspection_plans": ("业务档案", "#34c759"),
    "images": ("影像识别", "#007aff"), "recognition_runs": ("影像识别", "#007aff"),
    "detections": ("影像识别", "#007aff"),
    "yield_estimates": ("分析与报表", "#ff9500"), "harvest_records": ("分析与报表", "#ff9500"),
    "reports": ("分析与报表", "#ff9500"),
    "users": ("系统", "#8e8e93"),
}

COLUMN_LABELS = {
    "id": "ID", "code": "编号", "name": "名称", "region": "区域", "area_mu": "面积(亩)",
    "variety": "品种", "planting_date": "种植时间", "density": "密度(株/亩)",
    "expected_trees": "预计株数", "remark": "备注", "is_demo": "演示数据",
    "created_at": "创建时间", "updated_at": "更新时间", "orchard_id": "果园ID",
    "plot_id": "地块ID", "plan_id": "计划ID", "tree_count": "株数", "latitude": "纬度",
    "longitude": "经度", "planned_date": "计划日期", "executed_date": "执行日期",
    "owner": "负责人", "method": "巡检方式", "status": "状态", "original_name": "原文件名",
    "stored_path": "存储路径", "file_size": "文件大小", "width": "宽", "height": "高",
    "captured_at": "拍摄时间", "sample_trees": "样本树数", "archived": "已归档",
    "is_abnormal": "异常点位", "image_id": "影像ID", "mode": "识别方式",
    "model_name": "模型", "conf_threshold": "置信度阈值", "device": "设备",
    "error_message": "错误信息", "total_count": "检测数", "class_counts": "类别统计",
    "size_counts": "大小统计", "result_path": "结果图", "duration_ms": "耗时(ms)",
    "reviewed_count": "复核果数", "review_note": "复核说明", "reviewed_at": "复核时间",
    "run_id": "识别ID", "class_id": "类别ID", "class_name": "类别", "confidence": "置信度",
    "x1": "x1", "y1": "y1", "x2": "x2", "y2": "y2", "area_ratio": "面积占比",
    "size_grade": "相对大小", "level": "层级", "count_source": "计数来源",
    "sample_images": "样本图片数", "sample_fruit_count": "样本果数",
    "sample_tree_count": "样本树数", "avg_fruit_per_tree": "株均果数",
    "target_tree_count": "目标树数", "correction_factor": "校正系数",
    "avg_fruit_weight_g": "单果重(g)", "est_fruit_count": "预计果数",
    "est_yield_kg": "预计产量(kg)", "class_breakdown": "分级拆分", "formula": "公式",
    "report_type": "报表类型", "fmt": "格式", "title": "标题", "file_path": "文件路径",
    "params": "参数", "username": "用户名", "password_hash": "密码哈希",
    "display_name": "显示名", "role": "角色", "is_active": "启用",
    "must_change_password": "需改密", "last_login_at": "最近登录",
    "source": "采集方式", "maturity": "成熟度(颜色)", "maturity_counts": "成熟度统计",
    "year": "年份", "actual_yield_kg": "实际产量(kg)", "avg_price": "均价(元/kg)",
}


def _type_kind(type_name):
    t = (type_name or "").upper()
    if "INT" in t:
        return "int"
    if "FLOAT" in t or "REAL" in t or "NUMERIC" in t:
        return "num"
    if "DATE" in t or "TIME" in t:
        return "date"
    if "JSON" in t:
        return "json"
    if "BOOL" in t:
        return "bool"
    return "text"


def _inspector():
    return inspect(db.engine)


def _table_names():
    return sorted(_inspector().get_table_names())


def _count(table):
    return db.session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0


def _columns(table):
    insp = _inspector()
    pk = set(insp.get_pk_constraint(table).get("constrained_columns") or [])
    cols = []
    for c in insp.get_columns(table):
        cols.append({"name": c["name"], "type": str(c["type"]),
                     "label": COLUMN_LABELS.get(c["name"], c["name"]),
                     "kind": _type_kind(str(c["type"])),
                     "pk": c["name"] in pk, "nullable": c.get("nullable", True)})
    return cols


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, bytes):
        return f"<二进制 {len(value)} 字节>"
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            value = json.dumps(json.loads(value), ensure_ascii=False, separators=(",", ":"))
        except ValueError:
            pass
    text_value = str(value)
    return text_value if len(text_value) <= 120 else text_value[:117] + "…"


def _rows(table, columns, keyword, page):
    where, params = "", {}
    if keyword:
        text_cols = [c["name"] for c in columns
                     if any(k in c["type"].lower() for k in ("char", "text", "clob"))]
        if text_cols:
            where = " WHERE " + " OR ".join(f'CAST("{c}" AS TEXT) LIKE :kw' for c in text_cols)
            params["kw"] = f"%{keyword}%"
    total = db.session.execute(text(f'SELECT COUNT(*) FROM "{table}"{where}'), params).scalar() or 0
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    sql = f'SELECT * FROM "{table}"{where} ORDER BY 1 DESC LIMIT :limit OFFSET :offset'
    result = db.session.execute(text(sql), {**params, "limit": PAGE_SIZE,
                                            "offset": (page - 1) * PAGE_SIZE})
    rows = [[_fmt(v) for v in row] for row in result.fetchall()]
    return rows, total, page, pages


@bp.route("/")
def index():
    tables = _table_names()
    selected = request.args.get("table") or (tables[0] if tables else None)
    if selected not in tables:
        selected = None
    keyword = (request.args.get("q") or "").strip()[:60]
    page = request.args.get("page", 1, type=int) or 1

    detail = None
    if selected:
        columns = _columns(selected)
        rows, total, page, pages = _rows(selected, columns, keyword, page)
        category, color = TABLE_CATEGORY.get(selected, ("数据", "#8e8e93"))
        detail = {"name": selected, "label": TABLE_LABELS.get(selected, selected),
                  "category": category, "color": color,
                  "columns": columns, "rows": rows, "total": total, "pages": pages, "page": page}

    db_path = Path(current_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
    counts = {t: _count(t) for t in tables}
    max_count = max(counts.values() or [1])
    items = []
    for t in tables:
        category, color = TABLE_CATEGORY.get(t, ("数据", "#8e8e93"))
        items.append({"name": t, "label": TABLE_LABELS.get(t, t), "count": counts[t],
                      "share": round(counts[t] * 100 / max_count) if max_count else 0,
                      "category": category, "color": color})
    info = {
        "tables": items,
        "chart": sorted(items, key=lambda x: x["count"], reverse=True),
        "total_rows": sum(counts.values()),
        "path": db_path,
        "size_kb": round(db_path.stat().st_size / 1024, 1) if db_path.is_file() else 0,
        "keyword": keyword,
    }
    return render_template("database/index.html", info=info, detail=detail)


@bp.route("/export")
def export():
    """把当前表导出为 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""
    table = request.args.get("table")
    if table not in _table_names():
        return "未知数据表", 404
    columns = _columns(table)
    keyword = (request.args.get("q") or "").strip()[:60]
    where, params = "", {}
    if keyword:
        text_cols = [c["name"] for c in columns
                     if any(k in c["type"].lower() for k in ("char", "text", "clob"))]
        if text_cols:
            where = " WHERE " + " OR ".join(f'CAST("{c}" AS TEXT) LIKE :kw' for c in text_cols)
            params["kw"] = f"%{keyword}%"
    result = db.session.execute(text(f'SELECT * FROM "{table}"{where} ORDER BY 1'), params)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c["label"] for c in columns])
    for row in result.fetchall():
        writer.writerow([_fmt(v) for v in row])
    data = "\ufeff" + buf.getvalue()
    return Response(data, content_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{table}.csv"'})
