"""估产：单株 / 地块 / 全园，保存来源、参数、公式与结果。"""
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from ..extensions import db
from ..models import YIELD_LEVELS, InspectionPlan, Orchard, Plot, YieldEstimate
from ..services import stats
from ..services import yield_service as ys
from ..utils import FormError, get_choice, get_float, get_int, get_str

bp = Blueprint("yields", __name__, url_prefix="/yields")


@bp.route("/")
def index():
    query = YieldEstimate.query
    oid = request.args.get("orchard_id", type=int)
    level = request.args.get("level", "")
    if oid:
        query = query.filter_by(orchard_id=oid)
    if level in YIELD_LEVELS:
        query = query.filter_by(level=level)
    return render_template("yields/index.html", items=query.order_by(YieldEstimate.id.desc()).all(),
                           orchards=Orchard.query.all(), levels=YIELD_LEVELS, oid=oid, level=level,
                           trend=stats.yield_trend(), harvest=stats.harvest_compare())


@bp.route("/samples/<int:plan_id>")
def samples(plan_id):
    """前端预填样本数据用。"""
    plan = db.get_or_404(InspectionPlan, plan_id)
    data = ys.collect_samples(plan_id, request.args.get("source", "reviewed"))
    data.update(orchard_id=plan.orchard_id, plot_id=plan.plot_id,
                plot_trees=plan.plot.tree_count if plan.plot else None,
                orchard_trees=plan.orchard.expected_trees or plan.orchard.plot_tree_total or None)
    return jsonify(data)


@bp.route("/new", methods=["GET", "POST"])
def create():
    plans = InspectionPlan.query.order_by(InspectionPlan.id.desc()).all()
    if request.method == "POST":
        form = request.form
        try:
            level = get_choice(form, "level", "估产层级", YIELD_LEVELS)
            plan = db.session.get(InspectionPlan, get_int(form, "plan_id", "数据来源批次", required=True))
            if not plan:
                raise FormError("巡检批次不存在")
            source = get_choice(form, "count_source", "计数来源", ["reviewed", "model"], "reviewed")
            orchard = plan.orchard
            plot = None
            if level == "地块":
                plot = db.session.get(Plot, get_int(form, "plot_id", "地块") or plan.plot_id or 0)
                if not plot or plot.orchard_id != orchard.id:
                    raise FormError("地块级估产需选择该果园下的地块")
            sample = ys.collect_samples(plan.id, source)
            fruit = get_int(form, "sample_fruit_count", "样本果数")
            trees = get_int(form, "sample_tree_count", "样本树数")
            fruit = sample["fruit"] if fruit is None else fruit
            trees = sample["trees"] if trees is None else trees
            target = get_int(form, "target_tree_count", "目标树数") or ys.target_trees_for(level, orchard, plot)
            if level == "单株":
                target = 1
            factor = get_float(form, "correction_factor", "校正系数", required=True)
            weight = get_float(form, "avg_fruit_weight_g", "平均单果重", required=True)
            res = ys.compute(fruit, trees, target, factor, weight)
        except (FormError, ys.YieldError) as e:
            flash(str(e), "danger")
            return render_template("yields/form.html", plans=plans, levels=YIELD_LEVELS,
                                   plots=Plot.query.all(), form=form)
        manual = fruit != sample["fruit"] or trees != sample["trees"]
        remark = get_str(form, "remark", "备注", max_len=1000) or ""
        if manual:
            remark = ("[样本数据含人工输入] " + remark).strip()
        if sample["demo_images"]:
            remark = (f"[含 {sample['demo_images']} 张演示模式识别结果，仅供流程演示] " + remark).strip()
        item = YieldEstimate(level=level, orchard_id=orchard.id, plot_id=plot.id if plot else None,
                             plan_id=plan.id, count_source=source, sample_images=sample["images"],
                             sample_fruit_count=fruit, sample_tree_count=trees,
                             target_tree_count=target, correction_factor=factor,
                             avg_fruit_weight_g=weight, formula=ys.FORMULA, remark=remark,
                             is_demo=bool(sample["demo_images"]) or plan.is_demo,
                             class_breakdown=ys.class_breakdown(sample["class_counts"],
                                                                res["est_fruit_count"]), **res)
        db.session.add(item)
        db.session.commit()
        flash("估产记录已保存", "success")
        return redirect(url_for("yields.detail", yid=item.id))
    return render_template("yields/form.html", plans=plans, levels=YIELD_LEVELS,
                           plots=Plot.query.all(), form=request.args)


@bp.route("/<int:yid>")
def detail(yid):
    return render_template("yields/detail.html", y=db.get_or_404(YieldEstimate, yid))


@bp.route("/<int:yid>/delete", methods=["POST"])
def delete(yid):
    db.session.delete(db.get_or_404(YieldEstimate, yid))
    db.session.commit()
    flash("估产记录已删除", "success")
    return redirect(url_for("yields.index"))
