"""首页（宣传页）、驾驶舱与图表数据接口。"""
from flask import Blueprint, jsonify, render_template

from ..services import detector, stats

bp = Blueprint("main", __name__)


@bp.route("/")
def landing():
    """对外首页：不登录也能看，用于展示系统与入口。"""
    return render_template("landing.html", d=stats.dashboard_data(),
                           status=detector.detector_status())


@bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", d=stats.dashboard_data(),
                           coverage=stats.coverage_data(),
                           status=detector.detector_status())


@bp.route("/api/charts")
def charts():
    return jsonify(stats.chart_data())


@bp.route("/api/model-status")
def model_status():
    return jsonify(detector.detector_status())
