"""报表中心：预览、导出 Excel/PDF、归档历史。"""
from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from ..extensions import db
from ..models import InspectionPlan, Orchard, ReportRecord
from ..services import reports as rs
from ..services.storage import resolve
from ..utils import FormError, get_date

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _params(src):
    rtype = src.get("report_type", "inspection")
    return dict(report_type=rtype, orchard_id=src.get("orchard_id", type=int) or None,
                plan_id=src.get("plan_id", type=int) or None,
                date_from=get_date(src, "date_from", "开始日期"),
                date_to=get_date(src, "date_to", "结束日期"))


@bp.route("/")
def index():
    rep, params = None, {}
    if request.args.get("report_type"):
        try:
            params = _params(request.args)
            rep = rs.build(**params)
        except (FormError, rs.ReportError) as e:
            flash(str(e), "danger")
    history = ReportRecord.query.order_by(ReportRecord.id.desc()).limit(50).all()
    return render_template("reports/index.html", rep=rep, types=rs.REPORT_TYPES, args=request.args,
                           orchards=Orchard.query.all(), plans=InspectionPlan.query.all(),
                           history=history)


@bp.route("/export", methods=["POST"])
def export():
    fmt = request.form.get("fmt")
    if fmt not in ("xlsx", "pdf"):
        abort(400)
    try:
        params = _params(request.form)
        rep = rs.build(**params)
        rel = rs.to_excel(rep, params["report_type"]) if fmt == "xlsx" else rs.to_pdf(rep, params["report_type"])
    except (FormError, rs.ReportError) as e:
        flash(str(e), "danger")
        return redirect(url_for("reports.index"))
    stored = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in params.items()}
    rec = ReportRecord(report_type=params["report_type"], fmt=fmt, title=rep["title"],
                       file_path=rel, params=stored)
    db.session.add(rec)
    db.session.commit()
    return redirect(url_for("reports.download", rid=rec.id))


@bp.route("/download/<int:rid>")
def download(rid):
    rec = db.get_or_404(ReportRecord, rid)
    path = resolve(rec.file_path)
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=f"{rec.title}.{rec.fmt}")
