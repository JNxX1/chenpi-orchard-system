"""数据模型：果园、地块、巡检计划、影像、识别批次、检测框、估产记录、报表记录。"""
from datetime import datetime

from .extensions import db


def now():
    return datetime.now()


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)


class Orchard(TimestampMixin, db.Model):
    __tablename__ = "orchards"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    region = db.Column(db.String(200))            # 地址/区域
    area_mu = db.Column(db.Float)                  # 面积（亩）
    variety = db.Column(db.String(50), default="茶枝柑")
    planting_date = db.Column(db.Date)
    density = db.Column(db.Float)                  # 种植密度（株/亩）
    expected_trees = db.Column(db.Integer)         # 预计株数
    remark = db.Column(db.Text)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)

    plots = db.relationship("Plot", backref="orchard", lazy="dynamic", order_by="Plot.code")
    plans = db.relationship("InspectionPlan", backref="orchard", lazy="dynamic")

    @property
    def plot_tree_total(self):
        return sum(p.tree_count or 0 for p in self.plots)


class Plot(TimestampMixin, db.Model):
    __tablename__ = "plots"
    __table_args__ = (db.UniqueConstraint("orchard_id", "code", name="uq_plot_code"),)
    id = db.Column(db.Integer, primary_key=True)
    orchard_id = db.Column(db.Integer, db.ForeignKey("orchards.id"), nullable=False, index=True)
    code = db.Column(db.String(32), nullable=False)
    name = db.Column(db.String(100))
    area_mu = db.Column(db.Float)
    tree_count = db.Column(db.Integer)
    variety = db.Column(db.String(50))
    # 预留地理坐标（无真实定位数据时为空）
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    remark = db.Column(db.Text)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)

    plans = db.relationship("InspectionPlan", backref="plot", lazy="dynamic")

    @property
    def label(self):
        return f"{self.code} {self.name or ''}".strip()


PLAN_STATUSES = ["待执行", "进行中", "已完成", "已取消"]
PLAN_METHODS = ["无人机航拍", "手持拍摄", "固定摄像头", "其他"]


class InspectionPlan(TimestampMixin, db.Model):
    """巡检计划 / 批次：每个计划即一个影像采集批次。"""
    __tablename__ = "inspection_plans"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    orchard_id = db.Column(db.Integer, db.ForeignKey("orchards.id"), nullable=False, index=True)
    plot_id = db.Column(db.Integer, db.ForeignKey("plots.id"), index=True)  # 为空表示全园
    planned_date = db.Column(db.Date, nullable=False)
    executed_date = db.Column(db.Date)
    owner = db.Column(db.String(50))
    method = db.Column(db.String(20), default="手持拍摄")
    status = db.Column(db.String(10), default="待执行", nullable=False)
    remark = db.Column(db.Text)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)

    images = db.relationship("ImageRecord", backref="plan", lazy="dynamic")

    def progress(self):
        """依据实际影像与识别记录计算进度。"""
        total = self.images.count()
        done = self.images.filter(ImageRecord.status == "已识别").count()
        return {"total": total, "recognized": done,
                "percent": round(done * 100 / total) if total else 0}


IMAGE_STATUSES = ["待识别", "已识别", "识别失败"]


class ImageRecord(TimestampMixin, db.Model):
    __tablename__ = "images"
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("inspection_plans.id"), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(255), unique=True, nullable=False)  # 相对 STORAGE_DIR
    file_size = db.Column(db.Integer)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    captured_at = db.Column(db.DateTime)
    sample_trees = db.Column(db.Integer)   # 该图覆盖的样本树数量（估产用，可空）
    source = db.Column(db.String(20))      # 采集方式：无人机航拍/手持拍摄/固定摄像头/其他
    latitude = db.Column(db.Float)         # GPS（可来自 EXIF 或手工填写）
    longitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    status = db.Column(db.String(10), default="待识别", nullable=False)
    archived = db.Column(db.Boolean, default=False, nullable=False)
    is_abnormal = db.Column(db.Boolean, default=False, nullable=False)  # 异常点位标记
    remark = db.Column(db.Text)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)

    runs = db.relationship("RecognitionRun", backref="image", lazy="dynamic",
                           order_by="RecognitionRun.id.desc()", cascade="all, delete-orphan")

    @property
    def latest_run(self):
        return self.runs.filter_by(status="成功").first()


class RecognitionRun(db.Model):
    """一次识别（重新识别会产生新记录，旧记录保留）。"""
    __tablename__ = "recognition_runs"
    id = db.Column(db.Integer, primary_key=True)
    image_id = db.Column(db.Integer, db.ForeignKey("images.id"), nullable=False, index=True)
    mode = db.Column(db.String(20), nullable=False)       # yolo / opencv_demo
    model_name = db.Column(db.String(255))
    conf_threshold = db.Column(db.Float)
    device = db.Column(db.String(20))
    status = db.Column(db.String(10), nullable=False)     # 成功 / 失败
    error_message = db.Column(db.Text)
    total_count = db.Column(db.Integer, default=0)
    class_counts = db.Column(db.JSON, default=dict)       # {类别: 数量}
    size_counts = db.Column(db.JSON, default=dict)        # {相对大小等级: 数量}
    maturity_counts = db.Column(db.JSON, default=dict)    # {颜色估算成熟度: 数量}，非模型分类
    result_path = db.Column(db.String(255))
    duration_ms = db.Column(db.Integer)
    # 人工复核（不覆盖模型原始结果）
    reviewed_count = db.Column(db.Integer)
    review_note = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    detections = db.relationship("Detection", backref="run", lazy="dynamic",
                                 cascade="all, delete-orphan")

    @property
    def effective_count(self):
        return self.reviewed_count if self.reviewed_count is not None else self.total_count

    @property
    def mode_label(self):
        return "YOLO 模型" if self.mode == "yolo" else "OpenCV 颜色阈值演示（非深度学习）"


class Detection(db.Model):
    __tablename__ = "detections"
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("recognition_runs.id"), nullable=False, index=True)
    class_id = db.Column(db.Integer)
    class_name = db.Column(db.String(50))
    confidence = db.Column(db.Float)
    x1 = db.Column(db.Float)
    y1 = db.Column(db.Float)
    x2 = db.Column(db.Float)
    y2 = db.Column(db.Float)
    area_ratio = db.Column(db.Float)       # 框面积 / 图像面积
    size_grade = db.Column(db.String(10))  # 相对大小：小/中/大（基于像素占比，非真实直径）
    maturity = db.Column(db.String(10))    # 颜色估算：青/转色/成熟（非模型分类）


YIELD_LEVELS = ["单株", "地块", "全园"]


class YieldEstimate(db.Model):
    __tablename__ = "yield_estimates"
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), nullable=False)
    orchard_id = db.Column(db.Integer, db.ForeignKey("orchards.id"), nullable=False, index=True)
    plot_id = db.Column(db.Integer, db.ForeignKey("plots.id"))
    plan_id = db.Column(db.Integer, db.ForeignKey("inspection_plans.id"))
    count_source = db.Column(db.String(10))     # model / reviewed
    sample_images = db.Column(db.Integer)
    sample_fruit_count = db.Column(db.Integer, nullable=False)
    sample_tree_count = db.Column(db.Integer, nullable=False)
    avg_fruit_per_tree = db.Column(db.Float, nullable=False)
    target_tree_count = db.Column(db.Integer, nullable=False)
    correction_factor = db.Column(db.Float, nullable=False)
    avg_fruit_weight_g = db.Column(db.Float, nullable=False)
    est_fruit_count = db.Column(db.Float, nullable=False)
    est_yield_kg = db.Column(db.Float, nullable=False)
    class_breakdown = db.Column(db.JSON, default=dict)  # 按类别比例拆分的预计果数
    formula = db.Column(db.Text)
    remark = db.Column(db.Text)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    orchard = db.relationship("Orchard")
    plot = db.relationship("Plot")
    plan = db.relationship("InspectionPlan")


class HarvestRecord(db.Model):
    """实际采收记录：用于和估产对比，补充“历史产量数据”。"""
    __tablename__ = "harvest_records"
    id = db.Column(db.Integer, primary_key=True)
    orchard_id = db.Column(db.Integer, db.ForeignKey("orchards.id"), nullable=False, index=True)
    plot_id = db.Column(db.Integer, db.ForeignKey("plots.id"))
    year = db.Column(db.Integer, nullable=False)
    actual_yield_kg = db.Column(db.Float, nullable=False)
    avg_price = db.Column(db.Float)
    note = db.Column(db.Text)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    orchard = db.relationship("Orchard")
    plot = db.relationship("Plot")


class ReportRecord(db.Model):
    __tablename__ = "reports"
    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(20), nullable=False)
    fmt = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(200))
    file_path = db.Column(db.String(255), nullable=False)
    params = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class User(db.Model):
    """系统用户。密码只保存哈希，不保存明文。"""
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(50))
    role = db.Column(db.String(20), default="管理员", nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    @property
    def name(self):
        return self.display_name or self.username

