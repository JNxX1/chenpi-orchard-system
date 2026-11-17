"""地块管理：与果园关联。"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Orchard, Plot, YieldEstimate
from ..utils import FormError, get_float, get_int, get_str

bp = Blueprint("plots", __name__, url_prefix="/plots")


def _fill(plot, form):
    oid = get_int(form, "orchard_id", "所属果园", required=True)
    if not db.session.get(Orchard, oid):
        raise FormError("所属果园不存在")
    plot.orchard_id = oid
    plot.code = get_str(form, "code", "地块编号", required=True, max_len=32)
    plot.name = get_str(form, "name", "地块名称", max_len=100)
    plot.area_mu = get_float(form, "area_mu", "面积")
    plot.tree_count = get_int(form, "tree_count", "株数")
    plot.variety = get_str(form, "variety", "品种", max_len=50)
    plot.latitude = get_float(form, "latitude", "纬度", min_value=-90)
    plot.longitude = get_float(form, "longitude", "经度", min_value=-180)
    plot.remark = get_str(form, "remark", "备注", max_len=1000)


@bp.route("/")
def index():
    oid = request.args.get("orchard_id", type=int)
    q = request.args.get("q", "").strip()
    query = Plot.query
    if oid:
        query = query.filter_by(orchard_id=oid)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Plot.code.like(like), Plot.name.like(like)))
    items = query.order_by(Plot.orchard_id, Plot.code).all()
    summary = {"count": len(items),
               "area": round(sum(p.area_mu or 0 for p in items), 1),
               "trees": sum(p.tree_count or 0 for p in items),
               "plans": sum(p.plans.count() for p in items)}
    return render_template("plots/index.html", plots=items, orchards=Orchard.query.all(),
                           oid=oid, q=q, summary=summary)


@bp.route("/new", methods=["GET", "POST"])
def create():
    plot = Plot(orchard_id=request.args.get("orchard_id", type=int))
    if request.method == "POST":
        try:
            _fill(plot, request.form)
            db.session.add(plot)
            db.session.commit()
            flash("地块已创建", "success")
            return redirect(url_for("orchards.detail", oid=plot.orchard_id))
        except FormError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except IntegrityError:
            db.session.rollback()
            flash("同一果园内地块编号不能重复", "danger")
    return render_template("plots/form.html", plot=plot, orchards=Orchard.query.all(), form=request.form)


@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
def edit(pid):
    plot = db.get_or_404(Plot, pid)
    if request.method == "POST":
        try:
            _fill(plot, request.form)
            db.session.commit()
            flash("地块已更新", "success")
            return redirect(url_for("orchards.detail", oid=plot.orchard_id))
        except FormError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except IntegrityError:
            db.session.rollback()
            flash("同一果园内地块编号不能重复", "danger")
    return render_template("plots/form.html", plot=plot, orchards=Orchard.query.all(), form=request.form)


@bp.route("/<int:pid>/delete", methods=["POST"])
def delete(pid):
    plot = db.get_or_404(Plot, pid)
    oid = plot.orchard_id
    if plot.plans.count() or YieldEstimate.query.filter_by(plot_id=pid).count():
        flash("该地块已关联巡检计划或估产记录，不能删除", "warning")
    else:
        db.session.delete(plot)
        db.session.commit()
        flash("地块已删除", "success")
    return redirect(url_for("orchards.detail", oid=oid))
