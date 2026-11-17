"""识别结果查询、汇总与人工复核。"""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import InspectionPlan, Orchard, Plot, RecognitionRun
from ..services import stats
from ..utils import FormError, get_date, get_int, get_str

bp = Blueprint("results", __name__, url_prefix="/results")


def parse_filters(args):
    try:
        f = {"orchard_id": args.get("orchard_id", type=int), "plot_id": args.get("plot_id", type=int),
             "plan_id": args.get("plan_id", type=int),
             "date_from": get_date(args, "date_from", "开始日期"),
             "date_to": get_date(args, "date_to", "结束日期")}
    except FormError as e:
        flash(str(e), "danger")
        f = {"orchard_id": None, "plot_id": None, "plan_id": None, "date_from": None, "date_to": None}
    return f


@bp.route("/")
def index():
    f = parse_filters(request.args)
    cls = request.args.get("class_name") or None
    rows = stats.latest_runs_query(**f).order_by(RecognitionRun.id.desc()).all()
    if cls:
        rows = [r for r in rows if cls in (r[0].class_counts or {})]
    all_classes = sorted({c for r in stats.latest_runs_query().all() for c in (r[0].class_counts or {})})
    return render_template("results/index.html", rows=rows, summary=stats.summarize(rows, cls),
                           orchards=Orchard.query.all(), plots=Plot.query.all(),
                           plans=InspectionPlan.query.all(), classes=all_classes,
                           args=request.args)


@bp.route("/run/<int:rid>/review", methods=["POST"])
def review(rid):
    run = db.get_or_404(RecognitionRun, rid)
    if request.form.get("clear"):
        run.reviewed_count = run.review_note = run.reviewed_at = None
        flash("已清除人工复核结果，恢复使用模型原始结果", "info")
    else:
        try:
            run.reviewed_count = get_int(request.form, "reviewed_count", "复核果数", required=True)
            run.review_note = get_str(request.form, "review_note", "复核说明", max_len=500)
            run.reviewed_at = datetime.now()
            flash("人工复核结果已保存（模型原始结果保留不变）", "success")
        except FormError as e:
            flash(str(e), "danger")
    db.session.commit()
    return redirect(url_for("images.detail", iid=run.image_id, run_id=rid))
