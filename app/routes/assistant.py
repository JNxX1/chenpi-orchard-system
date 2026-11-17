"""果园业务助手：数据库查事实 + 本地/外部大模型把事实讲成人话。

原则：事实（数量、名称、日期）一律来自数据库，模型只负责组织语言；
模型不可用时自动退回规则问答，核心业务不受影响。
"""
from flask import Blueprint, current_app, jsonify, render_template, request

from ..models import ImageRecord, InspectionPlan, YieldEstimate
from ..services import llm, stats

bp = Blueprint("assistant", __name__, url_prefix="/assistant")

INTENTS = [
    ("pending", ("未完成", "待执行", "进行中", "没完成", "任务")),
    ("yield", ("估产", "产量", "多少斤", "多少公斤", "kg")),
    ("recognition", ("识别", "检测", "果数", "数量", "类别", "分级", "成熟")),
    ("abnormal", ("异常",)),
    ("overview", ("概况", "总体", "多少个果园", "果园", "地块", "汇总")),
    ("disease", ("病", "虫", "黄化", "黄龙", "溃疡", "炭疽", "疮痂", "红蜘蛛", "潜叶蛾", "腐烂",
                 "落果", "霉", "斑点", "防治")),
]

# 柑橘常见病虫害知识库（文本，仅作辅助参考，不做图像诊断）
DISEASE_KB = {
    "黄龙病": "症状：叶片斑驳黄化、叶脉附近先黄，果实小、畸形、转色不均（红鼻子果），树势衰退。"
              "传播：柑橘木虱；病树无法治愈。处理：发现疑似病树及时报告农技部门，扑杀木虱、挖除病树，"
              "补种用无病苗木。",
    "溃疡病": "症状：叶片、果实出现木栓化、火山口状病斑，周围有黄晕，严重时落叶落果。"
              "传播：风雨、带菌苗木和工具。处理：剪除病枝病叶、清扫落叶，使用铜制剂等登记药剂，"
              "避免雨天作业，工具消毒。",
    "炭疽病": "症状：叶片出现半圆形或不定形病斑，果实上形成褐色凹陷斑，潮湿时有粉红色孢子堆，"
              "引起落果。处理：清除病果病枝，改善通风透光，发病初期按登记药剂喷施。",
    "疮痂病": "症状：幼果、嫩叶出现油渍状小点，后变木栓化疮痂，果实畸形。"
              "处理：春梢期和幼果期是防治关键，剪除病枝，按登记药剂防治。",
    "红蜘蛛": "症状：叶片出现密集灰白小点、失去光泽，严重时落叶，果面粗糙。"
              "处理：检查叶背虫口密度，保护天敌，达到防治指标时轮换使用登记杀螨剂。",
    "潜叶蛾": "症状：嫩叶出现弯曲银白色隧道，叶片卷曲，多发生在夏秋梢。"
              "处理：统一放梢、抹芽控梢，新梢期按登记药剂防治。",
    "裙腐病": "症状：树干基部树皮腐烂、流胶，叶片黄化，严重时整株死亡。"
              "处理：刮除病部、涂药，改善排水，避免嫁接口埋土过深。",
}

DISEASE_DISCLAIMER = ("以上为通用柑橘病虫害知识，仅供辅助参考；实际诊断需结合果园现场、"
                      "病样镜检或农技人员确认，不能仅凭文字或照片下结论。")


def answer_from_db(question):
    """规则问答：命中意图时返回一段确定的事实文本，否则返回 None。"""
    q = question.strip()
    intent = next((name for name, kws in INTENTS if any(k in q for k in kws)), None)
    if intent == "pending":
        plans = InspectionPlan.query.filter(InspectionPlan.status.in_(["待执行", "进行中"])) \
            .order_by(InspectionPlan.planned_date).all()
        if not plans:
            return "当前没有待执行或进行中的巡检计划。"
        lines = [f"共有 {len(plans)} 个未完成的巡检计划："]
        for p in plans:
            pg = p.progress()
            lines.append(f"· {p.name}（{p.orchard.name}，计划 {p.planned_date}，{p.status}，"
                         f"已识别 {pg['recognized']}/{pg['total']} 张）")
        return "\n".join(lines)
    if intent == "yield":
        items = YieldEstimate.query.order_by(YieldEstimate.id.desc()).limit(5).all()
        if not items:
            return "数据库中还没有估产记录，可在“产量估算”页面基于巡检批次创建。"
        lines = ["最近的估产记录："]
        for y in items:
            tag = "【演示】" if y.is_demo else ""
            lines.append(f"· {tag}{y.orchard.name} {y.level}"
                         f"{'·' + y.plot.code if y.plot else ''}：预计 {y.est_fruit_count:.0f} 个果，"
                         f"约 {y.est_yield_kg:.1f} kg（{y.created_at:%Y-%m-%d}）")
        return "\n".join(lines)
    if intent == "recognition":
        s = stats.summarize(stats.latest_runs_query().all())
        if not s["images"]:
            return "还没有成功识别的影像。"
        cls = "，".join(f"{k} {v}" for k, v in s["class_counts"].items()) or "无"
        txt = (f"已识别影像 {s['images']} 张，模型检测目标 {s['model_total']} 个，"
               f"人工复核后合计 {s['effective_total']} 个。类别统计：{cls}。")
        if s["demo_images"]:
            txt += f"\n注意：其中 {s['demo_images']} 张为 OpenCV 演示模式结果，非深度学习模型输出。"
        return txt
    if intent == "abnormal":
        imgs = ImageRecord.query.filter_by(is_abnormal=True).all()
        if not imgs:
            return "当前没有被标记为异常的影像点位。"
        return "异常标记影像：\n" + "\n".join(f"· {i.original_name}（{i.plan.name}）{i.remark or ''}"
                                         for i in imgs)
    if intent == "overview":
        d = stats.dashboard_data()
        return (f"系统中共有果园 {d['orchards']} 个、地块 {d['plots']} 个、巡检计划 {d['plans']} 个"
                f"（未完成 {d['plans_open']} 个）、影像 {d['images']} 张（待识别 {d['images_pending']} 张）。")
    if intent == "disease":
        hits = [name for name in DISEASE_KB if name in q]
        if not hits:
            hits = [name for name, text in DISEASE_KB.items()
                    if any(k in q for k in ("病", "虫", "黄化", "斑点", "腐烂"))]
        if not hits:
            hits = list(DISEASE_KB)[:3]
        parts = [f"{name}：{DISEASE_KB[name]}" for name in hits[:3]]
        return "\n".join(parts) + "\n\n" + DISEASE_DISCLAIMER
    return None


def context_facts():
    """没有命中意图时，给模型一段总体上下文，避免它只能回答固定问法。"""
    d = stats.dashboard_data()
    s = d["summary"]
    lines = [f"系统概况：果园 {d['orchards']} 个，地块 {d['plots']} 个，巡检计划 {d['plans']} 个"
             f"（未完成 {d['plans_open']} 个），影像 {d['images']} 张（待识别/失败 {d['images_pending']} 张，"
             f"异常 {d['abnormal']} 张），识别目标 {s['effective_total']} 个（模型原始 {s['model_total']} 个）。"]
    plans = InspectionPlan.query.order_by(InspectionPlan.id.desc()).limit(5).all()
    if plans:
        lines.append("最近巡检计划：")
        for p in plans:
            pg = p.progress()
            lines.append(f"· {p.name}｜{p.orchard.name}｜{p.status}｜计划 {p.planned_date}｜"
                         f"识别 {pg['recognized']}/{pg['total']} 张")
    yields = YieldEstimate.query.order_by(YieldEstimate.id.desc()).limit(3).all()
    if yields:
        lines.append("最近估产：")
        for y in yields:
            lines.append(f"· {y.orchard.name} {y.level}：{y.est_yield_kg:.1f} kg"
                         f"（{y.created_at:%Y-%m-%d}）")
    if s["class_counts"]:
        lines.append("识别类别：" + "，".join(f"{k} {v}" for k, v in s["class_counts"].items()))
    return "\n".join(lines)


@bp.route("/")
def index():
    return render_template("assistant.html", llm_status=llm.status())


@bp.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()[:500]
    if not question:
        return jsonify({"error": "问题不能为空"}), 400

    facts = answer_from_db(question) or context_facts()
    result = {"facts": facts, "answer": None, "error": None, "source": "rules", "model": None}
    st = llm.status()
    result["model"] = st["model"] if st["enabled"] else None
    if not st["ready"]:
        result["error"] = st["detail"] or "模型未就绪"
        return jsonify(result)
    try:
        result["answer"] = llm.ask(question, facts)
        result["source"] = "ai"
    except llm.LLMError as e:
        result["error"] = str(e)
    return jsonify(result)


@bp.route("/warm", methods=["POST"])
def warm():
    """页面打开时在后台预热模型，避免第一次提问等太久。"""
    return jsonify(ok=llm.warm())
