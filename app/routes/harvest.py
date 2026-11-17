"""实际采收记录：补历史产量，用于估产偏差与同比分析。"""
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import HarvestRecord, Orchard, Plot
from ..services import stats
from ..utils import FormError, get_float, get_int, get_str

bp = Blueprint("harvest", __name__, url_prefix="/harvest")


@bp.route("/")
def index():
    oid = request.args.get("orchard_id", type=int)
    year = request.args.get("year", type=int)
    query = HarvestRecord.query
    if oid:
        query = query.filter_by(orchard_id=oid)
    if year:
        query = query.filter_by(year=year)
    items = query.order_by(HarvestRecord.year.desc(), HarvestRecord.id.desc()).all()
    years = sorted({h.year for h in HarvestRecord.query.all()}, reverse=True)
    return render_template("harvest/index.html", items=items, orchards=Orchard.query.all(),
                           oid=oid, year=year, years=years,
                           total=round(sum(i.actual_yield_kg or 0 for i in items), 1),
                           compare=stats.harvest_compare())


@bp.route("/new", methods=["GET", "POST"])
def create():
    orchards = Orchard.query.order_by(Orchard.id).all()
    plots = Plot.query.order_by(Plot.code).all()
    if request.method == "POST":
        form = request.form
        try:
            oid = get_int(form, "orchard_id", "果园", required=True)
            orchard = db.session.get(Orchard, oid)
            if not orchard:
                raise FormError("果园不存在")
            pid = get_int(form, "plot_id", "地块")
            plot = db.session.get(Plot, pid) if pid else None
            if pid and (not plot or plot.orchard_id != oid):
                raise FormError("所选地块不属于该果园")
            year = get_int(form, "year", "年份", required=True)
            if not 2000 <= year <= 2100:
                raise FormError("年份应在 2000–2100 之间")
            kg = get_float(form, "actual_yield_kg", "实际产量", required=True)
            price = get_float(form, "avg_price", "均价")
            note = get_str(form, "remark", "备注", max_len=1000)
            db.session.add(HarvestRecord(orchard_id=oid, plot_id=pid, year=year,
                                         actual_yield_kg=kg, avg_price=price, note=note))
            db.session.commit()
            flash("采收记录已保存", "success")
            return redirect(url_for("harvest.index"))
        except FormError as e:
            flash(str(e), "danger")
    return render_template("harvest/form.html", orchards=orchards, plots=plots,
                           form=request.form, this_year=date.today().year)


@bp.route("/<int:hid>/delete", methods=["POST"])
def delete(hid):
    rec = db.get_or_404(HarvestRecord, hid)
    db.session.delete(rec)
    db.session.commit()
    flash("采收记录已删除", "success")
    return redirect(url_for("harvest.index"))
