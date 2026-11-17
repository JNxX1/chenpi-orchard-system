"""果园管理：增删改查。"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Orchard
from ..utils import FormError, get_date, get_float, get_int, get_str

bp = Blueprint("orchards", __name__, url_prefix="/orchards")


def _fill(orchard, form):
    orchard.code = get_str(form, "code", "果园编号", required=True, max_len=32)
    orchard.name = get_str(form, "name", "果园名称", required=True, max_len=100)
    orchard.region = get_str(form, "region", "地址/区域")
    orchard.area_mu = get_float(form, "area_mu", "面积")
    orchard.variety = get_str(form, "variety", "品种", max_len=50)
    orchard.planting_date = get_date(form, "planting_date", "种植时间")
    orchard.density = get_float(form, "density", "种植密度")
    orchard.expected_trees = get_int(form, "expected_trees", "预计株数")
    orchard.remark = get_str(form, "remark", "备注", max_len=1000)


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    query = Orchard.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Orchard.name.like(like), Orchard.code.like(like),
                                    Orchard.region.like(like)))
    items = query.order_by(Orchard.id.desc()).all()
    summary = {"count": len(items),
               "area": round(sum(o.area_mu or 0 for o in items), 1),
               "trees": sum(o.expected_trees or 0 for o in items),
               "plots": sum(o.plots.count() for o in items)}
    return render_template("orchards/index.html", orchards=items, q=q, summary=summary)


@bp.route("/new", methods=["GET", "POST"])
def create():
    orchard = Orchard()
    if request.method == "POST":
        try:
            _fill(orchard, request.form)
            db.session.add(orchard)
            db.session.commit()
            flash("果园已创建", "success")
            return redirect(url_for("orchards.detail", oid=orchard.id))
        except FormError as e:
            flash(str(e), "danger")
        except IntegrityError:
            db.session.rollback()
            flash("果园编号已存在", "danger")
    return render_template("orchards/form.html", orchard=orchard, form=request.form)


@bp.route("/<int:oid>")
def detail(oid):
    orchard = db.get_or_404(Orchard, oid)
    return render_template("orchards/detail.html", orchard=orchard)


@bp.route("/<int:oid>/edit", methods=["GET", "POST"])
def edit(oid):
    orchard = db.get_or_404(Orchard, oid)
    if request.method == "POST":
        try:
            _fill(orchard, request.form)
            db.session.commit()
            flash("果园信息已更新", "success")
            return redirect(url_for("orchards.detail", oid=oid))
        except FormError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except IntegrityError:
            db.session.rollback()
            flash("果园编号已存在", "danger")
    return render_template("orchards/form.html", orchard=orchard, form=request.form)


@bp.route("/<int:oid>/delete", methods=["POST"])
def delete(oid):
    orchard = db.get_or_404(Orchard, oid)
    if orchard.plots.count() or orchard.plans.count():
        flash("该果园下仍有地块或巡检计划，请先处理关联数据后再删除", "warning")
        return redirect(url_for("orchards.detail", oid=oid))
    from ..models import YieldEstimate
    if YieldEstimate.query.filter_by(orchard_id=oid).count():
        flash("该果园已有估产记录，不能删除", "warning")
        return redirect(url_for("orchards.detail", oid=oid))
    db.session.delete(orchard)
    db.session.commit()
    flash("果园已删除", "success")
    return redirect(url_for("orchards.index"))
