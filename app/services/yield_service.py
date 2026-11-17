"""估产服务：基于样本的可解释估产公式。

样本平均可见果数 = 样本检测果数 ÷ 样本树数
预计总果数     = 样本平均可见果数 × 目标树数 × 校正系数
预计产量(kg)   = 预计总果数 × 平均单果重(g) ÷ 1000

“样本树数”指样本影像实际覆盖的树木数量（上传时按图填写），因此不会把整地块
统计结果再乘以树数而重复计算。校正系数用于补偿遮挡/背面不可见果实（实测可见率的倒数）。
"""
from ..models import ImageRecord
from .stats import latest_runs_query

FORMULA = ("样本平均可见果数 = 样本检测果数 ÷ 样本树数；"
           "预计总果数 = 样本平均可见果数 × 目标树数 × 校正系数；"
           "预计产量(kg) = 预计总果数 × 平均单果重(g) ÷ 1000")


class YieldError(ValueError):
    pass


def compute(sample_fruit_count, sample_tree_count, target_tree_count,
            correction_factor, avg_fruit_weight_g):
    if sample_fruit_count is None or sample_fruit_count < 0:
        raise YieldError("样本检测果数无效")
    if not sample_tree_count or sample_tree_count <= 0:
        raise YieldError("样本树数必须大于 0（请在影像中填写每图覆盖的样本树数，或手动输入）")
    if not target_tree_count or target_tree_count <= 0:
        raise YieldError("目标树数必须大于 0（请完善地块株数或果园预计株数）")
    if correction_factor is None or correction_factor <= 0:
        raise YieldError("校正系数必须大于 0")
    if not avg_fruit_weight_g or avg_fruit_weight_g <= 0:
        raise YieldError("平均单果重必须大于 0")
    avg = sample_fruit_count / sample_tree_count
    est_count = avg * target_tree_count * correction_factor
    return {"avg_fruit_per_tree": round(avg, 4), "est_fruit_count": round(est_count, 2),
            "est_yield_kg": round(est_count * avg_fruit_weight_g / 1000, 3)}


def collect_samples(plan_id, source="reviewed"):
    """汇总某巡检批次每张图片最新一次成功识别结果。

    source=reviewed：有人工复核数时用复核数，否则用模型数；source=model：只用模型原始数。
    只有填写了 sample_trees 的图片才计入样本。
    """
    rows = latest_runs_query(plan_id=plan_id).all()
    fruit = trees = used = demo = 0
    skipped, classes = [], {}
    for run, img, _plan in rows:
        if not img.sample_trees:
            skipped.append(img.original_name)
            continue
        fruit += run.effective_count if source == "reviewed" else run.total_count
        trees += img.sample_trees
        used += 1
        demo += run.mode != "yolo"
        for k, v in (run.class_counts or {}).items():
            classes[k] = classes.get(k, 0) + v
    total_images = ImageRecord.query.filter_by(plan_id=plan_id).count()
    return {"fruit": fruit, "trees": trees, "images": used, "skipped": skipped,
            "unrecognized": total_images - len(rows), "demo_images": demo,
            "class_counts": classes}


def class_breakdown(class_counts, est_fruit_count):
    total = sum(class_counts.values())
    if not total:
        return {}
    return {k: round(est_fruit_count * v / total, 2) for k, v in class_counts.items()}


def target_trees_for(level, orchard, plot):
    if level == "单株":
        return 1
    if level == "地块":
        return plot.tree_count if plot else None
    return orchard.expected_trees or orchard.plot_tree_total or None
