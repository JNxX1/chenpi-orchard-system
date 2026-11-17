"""统计服务：识别结果汇总、驾驶舱指标与图表数据，全部来自数据库。"""
from collections import Counter, defaultdict

from sqlalchemy import func

from ..extensions import db
from ..models import (HarvestRecord, ImageRecord, InspectionPlan, Orchard, Plot,
                      RecognitionRun, YieldEstimate)


def latest_run_ids():
    """每张影像最近一次成功识别的 run.id 子查询。"""
    return db.session.query(func.max(RecognitionRun.id)) \
        .filter(RecognitionRun.status == "成功").group_by(RecognitionRun.image_id)


def latest_runs_query(orchard_id=None, plot_id=None, plan_id=None, date_from=None, date_to=None):
    q = db.session.query(RecognitionRun, ImageRecord, InspectionPlan) \
        .join(ImageRecord, RecognitionRun.image_id == ImageRecord.id) \
        .join(InspectionPlan, ImageRecord.plan_id == InspectionPlan.id) \
        .filter(RecognitionRun.id.in_(latest_run_ids()))
    if orchard_id:
        q = q.filter(InspectionPlan.orchard_id == orchard_id)
    if plot_id:
        q = q.filter(InspectionPlan.plot_id == plot_id)
    if plan_id:
        q = q.filter(InspectionPlan.id == plan_id)
    if date_from:
        q = q.filter(func.date(RecognitionRun.created_at) >= date_from.isoformat())
    if date_to:
        q = q.filter(func.date(RecognitionRun.created_at) <= date_to.isoformat())
    return q


def summarize(rows, class_filter=None):
    """rows: [(run, image, plan)]。返回模型原始结果与人工复核结果分开的汇总。"""
    classes, sizes, maturity = Counter(), Counter(), Counter()
    model_total = effective_total = reviewed = demo = 0
    for run, _img, _plan in rows:
        cc = run.class_counts or {}
        if class_filter:
            cc = {k: v for k, v in cc.items() if k == class_filter}
        classes.update(cc)
        sizes.update(run.size_counts or {})
        maturity.update(getattr(run, "maturity_counts", None) or {})
        model_total += run.total_count or 0
        effective_total += run.effective_count or 0
        reviewed += run.reviewed_count is not None
        demo += run.mode != "yolo"
    return {"images": len(rows), "model_total": model_total, "effective_total": effective_total,
            "reviewed_images": reviewed, "demo_images": demo,
            "class_counts": dict(classes.most_common()),
            "size_counts": {k: sizes.get(k, 0) for k in ("小", "中", "大") if k in sizes},
            "maturity_counts": {k: maturity.get(k, 0) for k in ("青", "转色", "成熟")
                                if k in maturity}}


def harvest_compare():
    """按年对比“全园估产”和“实际采收”，用于同比与估产偏差分析。"""
    years = sorted({h.year for h in HarvestRecord.query.all()}
                   | {y.created_at.year for y in YieldEstimate.query.filter_by(level="全园").all()},
                   reverse=True)
    rows = []
    for year in years:
        actual = sum(h.actual_yield_kg or 0 for h in HarvestRecord.query.filter_by(year=year).all())
        estimate = sum(y.est_yield_kg or 0
                       for y in YieldEstimate.query.filter_by(level="全园").all()
                       if y.created_at.year == year)
        diff = (estimate - actual) / actual * 100 if actual and estimate else None
        rows.append({"year": year, "actual": round(actual, 1), "estimate": round(estimate, 1),
                     "diff": round(diff, 1) if diff is not None else None})
    return rows


def coverage_data():
    """地块巡检覆盖：计划数、已开展（有影像）、影像数、识别率。"""
    rows = []
    for p in Plot.query.order_by(Plot.orchard_id, Plot.code).all():
        plans = p.plans.all()
        total = len(plans)
        started = sum(1 for pl in plans if pl.images.count() > 0)
        imgs = ImageRecord.query.join(InspectionPlan).filter(InspectionPlan.plot_id == p.id).count()
        recognized = ImageRecord.query.join(InspectionPlan).filter(
            InspectionPlan.plot_id == p.id, ImageRecord.status == "已识别").count()
        rows.append({"plot": p, "plans": total, "started": started, "images": imgs,
                     "recognized": recognized,
                     "percent": round(started * 100 / total) if total else 0,
                     "recognition": round(recognized * 100 / imgs) if imgs else 0})
    return rows


def dashboard_data():
    rows = latest_runs_query().all()
    summary = summarize(rows)
    latest_yields = YieldEstimate.query.order_by(YieldEstimate.id.desc()).limit(5).all()
    plan_status = dict(db.session.query(InspectionPlan.status, func.count())
                       .group_by(InspectionPlan.status).all())
    return {
        "orchards": Orchard.query.count(),
        "plots": Plot.query.count(),
        "plans": InspectionPlan.query.count(),
        "plans_open": InspectionPlan.query.filter(InspectionPlan.status.in_(["待执行", "进行中"])).count(),
        "images": ImageRecord.query.count(),
        "images_pending": ImageRecord.query.filter(ImageRecord.status != "已识别").count(),
        "abnormal": ImageRecord.query.filter_by(is_abnormal=True).count(),
        "summary": summary,
        "plan_status": plan_status,
        "latest_yields": latest_yields,
        "total_yield_kg": _latest_orchard_yield_total(),
        "recent_plans": InspectionPlan.query.order_by(InspectionPlan.updated_at.desc()).limit(6).all(),
    }


def _latest_orchard_yield_total():
    """各果园最近一次“全园”估产之和；无全园估产时返回 None。"""
    total, found = 0.0, False
    for o in Orchard.query.all():
        y = YieldEstimate.query.filter_by(orchard_id=o.id, level="全园") \
            .order_by(YieldEstimate.id.desc()).first()
        if y:
            total += y.est_yield_kg
            found = True
    return round(total, 2) if found else None


def chart_data():
    rows = latest_runs_query().all()
    summary = summarize(rows)
    by_day = defaultdict(int)
    for run, _i, _p in rows:
        by_day[run.created_at.strftime("%Y-%m-%d")] += run.effective_count or 0
    days = sorted(by_day)
    plot_yield = {}
    for y in YieldEstimate.query.filter_by(level="地块").order_by(YieldEstimate.id).all():
        plot_yield[f"{y.orchard.name}/{y.plot.code}"] = round(y.est_yield_kg, 2)  # 取每地块最新
    plan_status = dict(db.session.query(InspectionPlan.status, func.count())
                       .group_by(InspectionPlan.status).all())
    return {
        "class_counts": summary["class_counts"],
        "size_counts": summary["size_counts"],
        "daily": {"labels": days, "values": [by_day[d] for d in days]},
        "plot_yield": plot_yield,
        "plan_status": plan_status,
    }


def _shift_month(ym, delta):
    """ym 形如 2026-10；返回相对偏移后的月份字符串。"""
    year, month = (int(v) for v in ym.split("-"))
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def yield_trend():
    """按月的全园估产合计，并计算环比（上月）与同比（去年同月）。

    同一果园同一个月只取最新一条“全园”估产，避免重复累加；
    没有相邻月份/去年同月数据时对应指标为 None，页面据此提示“数据不足”。
    """
    latest = {}
    for y in YieldEstimate.query.filter_by(level="全园").order_by(YieldEstimate.created_at).all():
        latest[(y.orchard_id, y.created_at.strftime("%Y-%m"))] = y
    monthly, demo = defaultdict(float), False
    for (oid, ym), y in latest.items():
        monthly[ym] += y.est_yield_kg or 0.0
        demo = demo or y.is_demo
    rows = []
    for ym in sorted(monthly):
        cur = monthly[ym]
        prev = monthly.get(_shift_month(ym, -1))
        last_year = monthly.get(_shift_month(ym, -12))
        rows.append({"month": ym, "total": round(cur, 2),
                     "mom": round((cur - prev) / prev * 100, 1) if prev else None,
                     "yoy": round((cur - last_year) / last_year * 100, 1) if last_year else None})
    return {"rows": rows, "months": len(monthly), "demo": demo,
            "has_mom": any(r["mom"] is not None for r in rows),
            "has_yoy": any(r["yoy"] is not None for r in rows)}
