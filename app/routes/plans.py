"""巡检计划与批次管理。"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import (PLAN_METHODS, PLAN_STATUSES, ImageRecord, InspectionPlan, Orchard,
                      Plot, YieldEstimate)
from ..utils import FormError, get_choice, get_date, get_int, get_str

bp = Blueprint("plans", __name__, url_prefix="/plans")


def _fill(plan, form):
    plan.name = get_str(form, "name", "计划名称", required=True, max_len=100)
    oid = get_int(form, "orchard_id", "果园", required=True)
    if not db.session.get(Orchard, oid):
        raise FormError("果园不存在")
    pid = get_int(form, "plot_id", "地块")
    if pid:
        plot = db.session.get(Plot, pid)
        if not plot or plot.orchard_id != oid:
            raise FormError("所选地块不属于该果园")
    plan.orchard_id, plan.plot_id = oid, pid
    plan.planned_date = get_date(form, "planned_date", "计划日期", required=True)
    plan.executed_date = get_date(form, "executed_date", "执行日期")
    plan.owner = get_str(form, "owner", "负责人", max_len=50)
    plan.method = get_choice(form, "method", "巡检方式", PLAN_METHODS, default="手持拍摄")
    plan.status = get_choice(form, "status", "状态", PLAN_STATUSES, default="待执行")
    plan.remark = get_str(form, "remark", "备注", max_len=1000)


def _ctx(plan):
    return dict(plan=plan, orchards=Orchard.query.all(), plots=Plot.query.order_by(Plot.code).all(),
                statuses=PLAN_STATUSES, methods=PLAN_METHODS, form=request.form)


@bp.route("/")
def index():
    query = InspectionPlan.query
    oid = request.args.get("orchard_id", type=int)
    status = request.args.get("status", "")
    if oid:
        query = query.filter_by(orchard_id=oid)
    if status in PLAN_STATUSES:
        query = query.filter_by(status=status)
    plans = query.order_by(InspectionPlan.planned_date.desc(), InspectionPlan.id.desc()).all()
    return render_template("plans/index.html", plans=plans, orchards=Orchard.query.all(),
                           statuses=PLAN_STATUSES, oid=oid, status=status)


@bp.route("/new", methods=["GET", "POST"])
def create():
    plan = InspectionPlan(orchard_id=request.args.get("orchard_id", type=int),
                          plot_id=request.args.get("plot_id", type=int))
    if request.method == "POST":
        try:
            _fill(plan, request.form)
            db.session.add(plan)
            db.session.commit()
            flash("巡检计划已创建", "success")
            return redirect(url_for("plans.detail", pid=plan.id))
        except FormError as e:
            db.session.rollback()
            flash(str(e), "danger")
    return render_template("plans/form.html", **_ctx(plan))


@bp.route("/<int:pid>")
def detail(pid):
    plan = db.get_or_404(InspectionPlan, pid)
    status = request.args.get("status", "")
    images = plan.images
    if status:
        images = images.filter_by(status=status)
    return render_template("plans/detail.html", plan=plan, progress=plan.progress(),
                           images=images.order_by(ImageRecord.id.desc()).all(), status=status)


@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
def edit(pid):
    plan = db.get_or_404(InspectionPlan, pid)
    if request.method == "POST":
        try:
            _fill(plan, request.form)
            db.session.commit()
            flash("巡检计划已更新", "success")
            return redirect(url_for("plans.detail", pid=pid))
        except FormError as e:
            db.session.rollback()
            flash(str(e), "danger")
    return render_template("plans/form.html", **_ctx(plan))


@bp.route("/<int:pid>/status", methods=["POST"])
def set_status(pid):
    plan = db.get_or_404(InspectionPlan, pid)
    status = request.form.get("status")
    if status not in PLAN_STATUSES:
        flash("状态取值无效", "danger")
    else:
        plan.status = status
        if status == "已完成" and not plan.executed_date:
            from datetime import date
            plan.executed_date = date.today()
        db.session.commit()
        flash(f"计划状态已更新为“{status}”", "success")
    return redirect(url_for("plans.detail", pid=pid))


@bp.route("/<int:pid>/delete", methods=["POST"])
def delete(pid):
    plan = db.get_or_404(InspectionPlan, pid)
    if plan.images.count() or YieldEstimate.query.filter_by(plan_id=pid).count():
        flash("该计划已有影像或估产记录，不能删除（可将状态设为“已取消”）", "warning")
        return redirect(url_for("plans.detail", pid=pid))
    db.session.delete(plan)
    db.session.commit()
    flash("巡检计划已删除", "success")
    return redirect(url_for("plans.index"))
