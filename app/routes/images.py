"""影像管理：上传、预览、查询、归档、异常标记、识别/重新识别。"""
from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)

from ..extensions import db
from ..models import Detection, IMAGE_STATUSES, ImageRecord, InspectionPlan, Orchard, Plot
from ..services import detector
from ..services.recognition import recognize_image
from ..services.storage import UploadError, delete_file, resolve, save_upload
from ..utils import FormError, get_float, get_int, get_str

bp = Blueprint("images", __name__, url_prefix="/images")


@bp.route("/")
def index():
    args = request.args
    query = ImageRecord.query.join(InspectionPlan)
    oid, pid, plan_id = (args.get(k, type=int) for k in ("orchard_id", "plot_id", "plan_id"))
    if oid:
        query = query.filter(InspectionPlan.orchard_id == oid)
    if pid:
        query = query.filter(InspectionPlan.plot_id == pid)
    if plan_id:
        query = query.filter(ImageRecord.plan_id == plan_id)
    if args.get("status") in IMAGE_STATUSES:
        query = query.filter(ImageRecord.status == args["status"])
    if args.get("archived") in ("0", "1"):
        query = query.filter(ImageRecord.archived == (args["archived"] == "1"))
    if args.get("abnormal") == "1":
        query = query.filter(ImageRecord.is_abnormal.is_(True))
    page = query.order_by(ImageRecord.id.desc()).paginate(page=args.get("page", 1, type=int),
                                                         per_page=24, error_out=False)
    return render_template("images/index.html", page=page, orchards=Orchard.query.all(),
                           plots=Plot.query.all(), plans=InspectionPlan.query.all(),
                           statuses=IMAGE_STATUSES, args=args)


@bp.route("/upload", methods=["GET", "POST"])
def upload():
    plans = InspectionPlan.query.filter(InspectionPlan.status != "已取消") \
        .order_by(InspectionPlan.id.desc()).all()
    if request.method == "POST":
        try:
            plan_id = get_int(request.form, "plan_id", "巡检计划", required=True)
            sample_trees = get_int(request.form, "sample_trees", "每图样本树数")
            lat = get_float(request.form, "latitude", "纬度", min_value=-90)
            lng = get_float(request.form, "longitude", "经度", min_value=-180)
            source = get_str(request.form, "source", "采集方式", max_len=20)
        except FormError as e:
            flash(str(e), "danger")
            return render_template("images/upload.html", plans=plans, status=detector.detector_status())
        plan = db.session.get(InspectionPlan, plan_id)
        if not plan or plan.status == "已取消":
            flash("巡检计划不存在或已取消", "danger")
            return redirect(url_for("images.upload"))
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            flash("请选择要上传的图片", "warning")
            return redirect(url_for("images.upload", plan_id=plan_id))
        saved, errors = [], []
        for f in files:
            try:
                meta = save_upload(f)
            except UploadError as e:
                errors.append(str(e))
                continue
            exif_lat = meta.pop("exif_lat", None)
            exif_lng = meta.pop("exif_lng", None)
            img = ImageRecord(plan_id=plan_id, sample_trees=sample_trees, source=source,
                              latitude=lat if lat is not None else exif_lat,
                              longitude=lng if lng is not None else exif_lng, **meta)
            db.session.add(img)
            saved.append(img)
        if saved and plan.status == "待执行":
            plan.status = "进行中"
        db.session.commit()
        if saved:
            flash(f"成功上传 {len(saved)} 张图片", "success")
        for e in errors:
            flash(e, "danger")
        if saved and request.form.get("auto_recognize"):
            ok = sum(recognize_image(img).status == "成功" for img in saved)
            flash(f"自动识别完成：成功 {ok} 张，失败 {len(saved) - ok} 张",
                  "success" if ok == len(saved) else "warning")
        return redirect(url_for("plans.detail", pid=plan_id))
    return render_template("images/upload.html", plans=plans,
                           selected=request.args.get("plan_id", type=int),
                           status=detector.detector_status())


@bp.route("/<int:iid>")
def detail(iid):
    image = db.get_or_404(ImageRecord, iid)
    run_id = request.args.get("run_id", type=int)
    run = image.runs.filter_by(id=run_id).first() if run_id else image.runs.first()
    return render_template("images/detail.html", image=image, run=run, runs=image.runs.all(),
                           status=detector.detector_status())


@bp.route("/file/<int:iid>/<kind>")
def file(iid, kind):
    """安全地输出原图或结果图（路径来自数据库，不接受用户路径）。"""
    image = db.get_or_404(ImageRecord, iid)
    if kind == "original":
        rel = image.stored_path
    elif kind == "result":
        run = image.runs.filter_by(id=request.args.get("run_id", type=int)).first() \
            if request.args.get("run_id") else image.latest_run
        rel = run.result_path if run else None
    else:
        abort(404)
    if not rel:
        abort(404)
    path = resolve(rel)
    if not path.is_file():
        abort(404)
    return send_file(path, max_age=3600)


@bp.route("/<int:iid>/detections.json")
def detections_json(iid):
    """返回某次识别的检测框，供前端做逐框动画。"""
    image = db.get_or_404(ImageRecord, iid)
    run_id = request.args.get("run_id", type=int)
    run = image.runs.filter_by(id=run_id).first() if run_id else image.latest_run
    if not run or run.status != "成功":
        return jsonify(ok=False, error="没有成功的识别记录"), 404
    boxes = [{"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2,
              "label": d.class_name, "conf": d.confidence, "grade": d.size_grade}
             for d in run.detections.order_by(Detection.id).all()]
    return jsonify(ok=True, run_id=run.id, width=image.width, height=image.height,
                   mode=run.mode, count=len(boxes), boxes=boxes)


@bp.route("/<int:iid>/recognize", methods=["POST"])
def recognize(iid):
    image = db.get_or_404(ImageRecord, iid)
    mode = request.form.get("mode", "auto")
    if mode not in ("auto", "yolo", "opencv_demo"):
        abort(400)
    run = recognize_image(image, mode)
    if run.status == "成功":
        flash(f"识别完成（{run.mode_label}），检测到 {run.total_count} 个目标", "success")
    else:
        flash(f"识别失败：{run.error_message}", "danger")
    return redirect(url_for("images.detail", iid=iid, run_id=run.id))


@bp.route("/plan/<int:pid>/recognize", methods=["POST"])
def recognize_plan(pid):
    plan = db.get_or_404(InspectionPlan, pid)
    only_pending = request.form.get("scope", "pending") == "pending"
    query = plan.images
    if only_pending:
        query = query.filter(ImageRecord.status != "已识别")
    images = query.all()
    if not images:
        flash("没有需要识别的图片", "info")
    else:
        ok = sum(recognize_image(img, request.form.get("mode", "auto")).status == "成功"
                 for img in images)
        flash(f"批量识别完成：成功 {ok} 张，失败 {len(images) - ok} 张",
              "success" if ok == len(images) else "warning")
    return redirect(url_for("plans.detail", pid=pid))


@bp.route("/<int:iid>/update", methods=["POST"])
def update(iid):
    image = db.get_or_404(ImageRecord, iid)
    try:
        image.sample_trees = get_int(request.form, "sample_trees", "样本树数")
        image.remark = get_str(request.form, "remark", "备注", max_len=1000)
        image.latitude = get_float(request.form, "latitude", "纬度", min_value=-90)
        image.longitude = get_float(request.form, "longitude", "经度", min_value=-180)
        db.session.commit()
        flash("影像信息已保存", "success")
    except FormError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("images.detail", iid=iid))


@bp.route("/<int:iid>/toggle/<field>", methods=["POST"])
def toggle(iid, field):
    image = db.get_or_404(ImageRecord, iid)
    if field not in ("archived", "is_abnormal"):
        abort(400)
    setattr(image, field, not getattr(image, field))
    db.session.commit()
    names = {"archived": ("已归档", "已取消归档"), "is_abnormal": ("已标记异常", "已取消异常标记")}
    flash(names[field][0] if getattr(image, field) else names[field][1], "success")
    return redirect(request.form.get("next") or url_for("images.detail", iid=iid))


@bp.route("/<int:iid>/delete", methods=["POST"])
def delete(iid):
    image = db.get_or_404(ImageRecord, iid)
    if image.archived:
        flash("已归档的影像不能删除，请先取消归档", "warning")
        return redirect(url_for("images.detail", iid=iid))
    plan_id = image.plan_id
    files = [image.stored_path] + [r.result_path for r in image.runs]
    db.session.delete(image)
    db.session.commit()
    for rel in files:
        delete_file(rel)
    flash("影像及其识别记录已删除", "success")
    return redirect(url_for("plans.detail", pid=plan_id))
