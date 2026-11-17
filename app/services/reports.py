"""报表生成：巡检报告、果实分级统计报表、估产报告；导出 Excel / PDF（中文字体）。

所有数值直接取自数据库；涉及演示数据/演示识别模式时在报表中显式标注。
"""
import re
import uuid
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, HRFlowable, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from ..extensions import db
from ..models import ImageRecord, InspectionPlan, Orchard, YieldEstimate
from . import stats
from .storage import resolve

REPORT_TYPES = {"inspection": "巡检报告", "grading": "果实分级统计报表", "yield": "估产报告"}
PDF_FONT = "CNFont"
PDF_BODY = "CNSong"
_FONT_FILES = ["C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc",
               "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]


class ReportError(ValueError):
    pass


def _f(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.{digits}f}"
    return str(int(v)) if isinstance(v, float) else str(v)


# ---------------- 报表内容构建（与输出格式无关） ----------------

def build(report_type, orchard_id=None, plan_id=None, date_from=None, date_to=None):
    """返回 {title, meta: [(k,v)], sections: [{title, header, rows, note}], warnings: []}。"""
    if report_type not in REPORT_TYPES:
        raise ReportError("报表类型无效")
    orchard = db.session.get(Orchard, orchard_id) if orchard_id else None
    plan = db.session.get(InspectionPlan, plan_id) if plan_id else None
    if orchard_id and not orchard:
        raise ReportError("果园不存在")
    if plan_id and not plan:
        raise ReportError("巡检计划不存在")
    scope = plan.name if plan else (orchard.name if orchard else "全部果园")
    rep = {"title": f"{REPORT_TYPES[report_type]}——{scope}",
           "meta": [("统计范围", scope), ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M"))],
           "sections": [], "warnings": []}
    if date_from or date_to:
        rep["meta"].append(("识别时间区间", f"{date_from or '不限'} 至 {date_to or '不限'}"))
    rows = stats.latest_runs_query(orchard_id=orchard_id, plan_id=plan_id,
                                   date_from=date_from, date_to=date_to).all()
    summary = stats.summarize(rows)
    if summary["demo_images"]:
        rep["warnings"].append(f"其中 {summary['demo_images']} 张图片的识别结果来自 OpenCV 演示模式"
                               "（非深度学习模型），数值仅用于流程演示。")
    BUILDERS[report_type](rep, orchard_id, plan, rows, summary)
    return rep


class _Builders:
    @staticmethod
    def inspection(rep, orchard_id, plan, rows, summary):
        q = InspectionPlan.query
        if plan:
            q = q.filter_by(id=plan.id)
        elif orchard_id:
            q = q.filter_by(orchard_id=orchard_id)
        plans = q.order_by(InspectionPlan.planned_date).all()
        prow = []
        for p in plans:
            pg = p.progress()
            prow.append([p.name, p.orchard.name, p.plot.label if p.plot else "全园",
                         _f(p.planned_date), p.owner or "—", p.method, p.status,
                         pg["total"], pg["recognized"], f"{pg['percent']}%"])
        rep["sections"].append({"title": "一、巡检计划执行情况",
                                "header": ["计划", "果园", "地块", "计划日期", "负责人", "方式",
                                           "状态", "影像数", "已识别", "进度"], "rows": prow})
        rep["sections"].append({"title": "二、识别结果汇总", "header": ["指标", "数值"], "rows": [
            ["已识别影像数", summary["images"]], ["模型检测目标总数", summary["model_total"]],
            ["人工复核后目标总数", summary["effective_total"]],
            ["经人工复核影像数", summary["reviewed_images"]]]})
        ab = ImageRecord.query.join(InspectionPlan).filter(ImageRecord.is_abnormal.is_(True))
        if plan:
            ab = ab.filter(InspectionPlan.id == plan.id)
        elif orchard_id:
            ab = ab.filter(InspectionPlan.orchard_id == orchard_id)
        rep["sections"].append({"title": "三、异常点位标记", "header": ["影像", "所属计划", "备注"],
                                "rows": [[i.original_name, i.plan.name, i.remark or ""] for i in ab.all()],
                                "note": "无异常标记影像"})
        detail = [[img.original_name, p.name, run.mode_label, run.total_count,
                   _f(run.reviewed_count), _f(run.created_at)] for run, img, p in rows]
        rep["sections"].append({"title": "四、影像识别明细",
                                "header": ["影像", "计划", "识别方式", "模型数", "复核数", "识别时间"],
                                "rows": detail})

    @staticmethod
    def grading(rep, orchard_id, plan, rows, summary):
        total = sum(summary["class_counts"].values())
        rep["sections"].append({"title": "一、按模型类别统计（模型原始结果）",
                                "header": ["类别", "数量", "占比"],
                                "rows": [[k, v, f"{v * 100 / total:.1f}%"]
                                         for k, v in summary["class_counts"].items()],
                                "note": "暂无识别数据"})
        st = sum(summary["size_counts"].values())
        rep["sections"].append({"title": "二、相对大小等级统计", "header": ["等级", "数量", "占比"],
                                "rows": [[k, v, f"{v * 100 / st:.1f}%"]
                                         for k, v in summary["size_counts"].items()],
                                "note": "暂无识别数据"})
        rep["warnings"].append("大小等级按检测框像素面积占整幅图像的比例划分，属于相对大小，"
                               "不代表真实果径。")
        mt = sum(summary.get("maturity_counts", {}).values())
        rep["sections"].append({"title": "三、成熟度分布（颜色估算）",
                                "header": ["成熟度", "数量", "占比"],
                                "rows": [[k, v, f"{v * 100 / mt:.1f}%"]
                                         for k, v in summary.get("maturity_counts", {}).items()],
                                "note": "暂无识别数据"})
        rep["warnings"].append("成熟度按检测框内橙黄色/绿色像素比例估算（青/转色/成熟），"
                               "属于颜色判断，不是模型分类结果，仅供现场参考。")
        per_plan = {}
        for run, _img, p in rows:
            d = per_plan.setdefault(p.name, {})
            for k, v in (run.class_counts or {}).items():
                d[k] = d.get(k, 0) + v
        classes = list(summary["class_counts"])
        rep["sections"].append({"title": "四、按巡检批次分类统计", "header": ["批次"] + classes + ["合计"],
                                "rows": [[n] + [d.get(c, 0) for c in classes] + [sum(d.values())]
                                         for n, d in per_plan.items()], "note": "暂无识别数据"})

def _yield_builder(rep, orchard_id, plan, rows, summary):
    q = YieldEstimate.query
    if plan:
        q = q.filter_by(plan_id=plan.id)
    elif orchard_id:
        q = q.filter_by(orchard_id=orchard_id)
    items = q.order_by(YieldEstimate.id).all()
    rep["warnings"] = [w for w in rep["warnings"] if "演示模式" not in w]
    if any(y.is_demo for y in items):
        rep["warnings"].append("标记“演示”的估产记录基于演示数据或演示模式识别结果，仅供流程演示。")
    rep["sections"].append({"title": "一、估产记录", "header": [
        "编号", "层级", "果园", "地块", "批次", "样本果数", "样本树数", "株均可见果",
        "目标树数", "校正系数", "单果重(g)", "预计果数", "预计产量(kg)", "演示"], "rows": [
        [y.id, y.level, y.orchard.name, y.plot.label if y.plot else "—", y.plan.name if y.plan else "—",
         y.sample_fruit_count, y.sample_tree_count, _f(y.avg_fruit_per_tree), y.target_tree_count,
         _f(y.correction_factor), _f(y.avg_fruit_weight_g), _f(y.est_fruit_count, 0),
         _f(y.est_yield_kg), "是" if y.is_demo else ""] for y in items], "note": "暂无估产记录"})
    breakdown = {}
    for y in items:
        for k, v in (y.class_breakdown or {}).items():
            breakdown.setdefault(y.id, []).append(f"{k}:{v:.0f}")
    rep["sections"].append({"title": "二、分级产量拆分（按识别类别比例）", "header": ["估产编号", "各类别预计果数"],
                            "rows": [[k, "，".join(v)] for k, v in breakdown.items()],
                            "note": "无类别拆分数据"})
    from .yield_service import FORMULA
    rep["sections"].append({"title": "三、估产公式", "header": ["说明"], "rows": [[FORMULA]]})
    compare = stats.harvest_compare()
    rep["sections"].append({
        "title": "四、估产与实际采收对比（全部果园）",
        "header": ["年份", "全园估产(kg)", "实际采收(kg)", "估产偏差"],
        "rows": [[r["year"], _f(r["estimate"]), _f(r["actual"]),
                  "—" if r["diff"] is None else f"{r['diff']:+.1f}%"] for r in compare],
        "note": "暂无实际采收记录，可在「采收记录」登记后重新导出"})


BUILDERS = {"inspection": _Builders.inspection, "grading": _Builders.grading, "yield": _yield_builder}


# ---------------- 输出 ----------------

INK = colors.HexColor("#1D1D1F")
MUTED = colors.HexColor("#6E6E73")
GREEN = colors.HexColor("#24452A")
ORANGE = colors.HexColor("#E8851E")
LINE = colors.HexColor("#D9D9D2")
ZEBRA = colors.HexColor("#FAFAF7")
SOFT = colors.HexColor("#F5F6F2")
DANGER_BG = colors.HexColor("#FDEEF0")
DANGER_FG = colors.HexColor("#8F241D")


def _out_path(report_type, fmt):
    rel = f"reports/{datetime.now():%Y%m}/{report_type}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.{fmt}"
    full = resolve(rel)
    full.parent.mkdir(parents=True, exist_ok=True)
    return rel, full


def _numeric(value):
    s = str(value).strip()
    return bool(re.fullmatch(r"-?[\d,]+(\.\d+)?%?", s)) if s else False


# ---------------- Excel ----------------
def to_excel(rep, report_type):
    rel, full = _out_path(report_type, "xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "报表"
    thin = Side(style="thin", color="D9D9D2")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="24452A")
    section_fill = PatternFill("solid", fgColor="F5F6F2")

    ncols = max([len(s["header"]) for s in rep["sections"]] or [1])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(4, ncols))
    title_cell = ws.cell(1, 1, rep["title"])
    title_cell.font = Font(bold=True, size=14, color="1D1D1F")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24

    row = 2
    for k, v in rep["meta"]:
        ws.cell(row, 1, k).font = Font(bold=True, size=10.5, color="6E6E73")
        ws.cell(row, 2, v).font = Font(size=10.5)
        row += 1
    for w in rep["warnings"]:
        ws.cell(row, 1, "重要说明").font = Font(bold=True, color="C0392B")
        c = ws.cell(row, 2, w)
        c.font = Font(size=10.5, color="C0392B")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.row_dimensions[row].height = 30
        row += 1

    for sec in rep["sections"]:
        row += 1
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(2, len(sec["header"])))
        cell = ws.cell(row, 1, sec["title"])
        cell.font = Font(bold=True, size=11.5, color="24452A")
        cell.fill = section_fill
        row += 1
        for j, h in enumerate(sec["header"], 1):
            c = ws.cell(row, j, h)
            c.font = Font(bold=True, size=11, color="FFFFFF")
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = border
        row += 1
        if not sec["rows"]:
            ws.cell(row, 1, sec.get("note", "无数据")).font = Font(color="6E6E73", italic=True)
            row += 1
            continue
        for r in sec["rows"]:
            for j, v in enumerate(r, 1):
                c = ws.cell(row, j, v)
                c.font = Font(size=11)
                c.border = border
                c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            row += 1

    for j in range(1, ws.max_column + 1):
        longest = 0
        for row_cells in ws.iter_rows(min_col=j, max_col=j):
            for c in row_cells:
                if c.value is not None:
                    longest = max(longest, len(str(c.value)))
        ws.column_dimensions[get_column_letter(j)].width = min(44, max(10, longest * 1.35))
    ws.freeze_panes = "A4"
    ws.sheet_view.zoomScale = 100
    if ncols >= 10:
        ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    wb.save(full)
    return rel


# ---------------- PDF ----------------
def _register_font():
    if PDF_BODY in pdfmetrics.getRegisteredFontNames():
        return
    head = next((f for f in _FONT_FILES if Path(f).exists()), None)
    if not head:
        raise ReportError("未找到可用的中文字体（需要 simhei.ttf 或 simsun.ttc）")
    pdfmetrics.registerFont(TTFont(PDF_FONT, head))
    song = "C:/Windows/Fonts/simsun.ttc"
    if Path(song).exists():
        try:
            pdfmetrics.registerFont(TTFont(PDF_BODY, song, subfontIndex=0))
            return
        except Exception:
            pass
    pdfmetrics.registerFont(TTFont(PDF_BODY, head))


def _styles():
    base = dict(fontName=PDF_BODY)
    return {
        "title": ParagraphStyle("title", fontName=PDF_FONT, fontSize=19, textColor=INK,
                                leading=25, alignment=TA_LEFT, spaceBefore=0, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", fontName=PDF_BODY, fontSize=9.5, textColor=MUTED,
                                   leading=15, alignment=TA_LEFT),
        "h2": ParagraphStyle("h2", fontName=PDF_FONT, fontSize=12, textColor=colors.white,
                             leading=17, backColor=GREEN, borderPadding=(5, 8, 5, 8),
                             spaceBefore=9, spaceAfter=7),
        "body": ParagraphStyle("body", parent=ParagraphStyle("b", **base), fontSize=10.5,
                               leading=16, textColor=INK),
        "note": ParagraphStyle("note", parent=ParagraphStyle("n", **base), fontSize=9,
                               leading=14, textColor=MUTED, spaceBefore=4),
        "warn": ParagraphStyle("warn", parent=ParagraphStyle("w", **base), fontSize=9.5,
                               leading=15, textColor=DANGER_FG),
    }


def _draw_page(cv, doc, with_header):
    cv.saveState()
    if with_header:
        cv.setFillColor(MUTED)
        cv.setFont(PDF_FONT, 8)
        cv.drawString(18 * mm, doc.pagesize[1] - 12 * mm, "陈皮柑果园智慧管理系统 · 自动生成报表")
        cv.setStrokeColor(LINE)
        cv.setLineWidth(0.6)
        cv.line(18 * mm, doc.pagesize[1] - 14 * mm, doc.pagesize[0] - 18 * mm, doc.pagesize[1] - 14 * mm)
    cv.setStrokeColor(LINE)
    cv.setLineWidth(0.6)
    cv.line(18 * mm, 15 * mm, doc.pagesize[0] - 18 * mm, 15 * mm)
    cv.setFillColor(MUTED)
    cv.setFont(PDF_BODY, 8)
    cv.drawString(18 * mm, 9.5 * mm, "广东交通职业技术学院 · 人工智能技术应用专业 · 毕业设计")
    cv.drawRightString(doc.pagesize[0] - 18 * mm, 9.5 * mm, f"第 {doc.page} 页")
    cv.restoreState()


def _col_widths(header, rows, width):
    n = len(header)
    weights = []
    for i in range(n):
        vals = [str(r[i]) for r in rows[:25] if i < len(r)]
        longest = max((len(v) for v in vals), default=6)
        header_w = len(str(header[i])) * 1.25
        weights.append(max(6, min(26, max(header_w, longest * 0.95))))
    total = sum(weights) or 1
    return [width * w / total for w in weights]


def _table(sec, width, styles):
    ncols = len(sec["header"])
    small = ncols >= 9
    fs = 8.8 if small else 10
    cell = ParagraphStyle("c", fontName=PDF_BODY, fontSize=fs, leading=fs + 3.2,
                          textColor=INK, alignment=TA_CENTER)
    head = ParagraphStyle("h", fontName=PDF_FONT, fontSize=fs + 0.2, leading=fs + 3.6,
                          textColor=colors.white, alignment=TA_CENTER)
    data = [[Paragraph(_esc(h), head) for h in sec["header"]]]
    for r in sec["rows"]:
        data.append([Paragraph(_esc(c), cell) for c in r])
    table = Table(data, colWidths=_col_widths(sec["header"], sec["rows"], width), repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, GREEN),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    table.setStyle(TableStyle(style))
    return table


def to_pdf(rep, report_type):
    _register_font()
    styles = _styles()
    maxcols = max([len(s["header"]) for s in rep["sections"]] or [1])
    pagesize = landscape(A4) if maxcols >= 10 else A4
    rel, full = _out_path(report_type, "pdf")
    doc = SimpleDocTemplate(str(full), pagesize=pagesize,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=18 * mm,
                            title=rep["title"], author="陈皮柑果园智慧管理系统",
                            subject=rep["title"])
    width = pagesize[0] - 32 * mm

    meta_parts = [f"{k}：{v}" for k, v in rep["meta"]
                  if not (k == "统计范围" and v in rep["title"])]
    story = [Paragraph(rep["title"], styles["title"]),
             Paragraph(_esc("　·　".join(meta_parts)), styles["subtitle"]),
             Spacer(1, 2 * mm),
             HRFlowable(width="100%", thickness=1.2, color=ORANGE,
                        spaceBefore=0, spaceAfter=5 * mm)]

    if rep["warnings"]:
        warn_cells = [[Paragraph("重要说明", ParagraphStyle(
            "wt", fontName=PDF_FONT, fontSize=9, leading=14, textColor=DANGER_FG))]]
        for w in rep["warnings"]:
            warn_cells.append([Paragraph(_esc(w), styles["warn"])])
        wt = Table(warn_cells, colWidths=[width])
        wt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), DANGER_BG),
            ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#C0392B")),
            ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#F2C4C9")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story += [wt, Spacer(1, 4 * mm)]

    for sec in rep["sections"]:
        story.append(CondPageBreak(34 * mm))
        story.append(Paragraph(sec["title"], styles["h2"]))
        if sec["rows"]:
            story.append(_table(sec, width, styles))
        else:
            story.append(Paragraph(sec.get("note", "暂无数据"), styles["note"]))
        story.append(Spacer(1, 3 * mm))

    doc.build(story, onFirstPage=lambda c, d: _draw_page(c, d, False),
              onLaterPages=lambda c, d: _draw_page(c, d, True))
    return rel

def _esc(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")