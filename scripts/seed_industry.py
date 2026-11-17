"""生成产业级演示数据（会清空现有业务数据，请先备份）。

用法：
    python scripts/seed_industry.py
"""
import random
import shutil
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import extract, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.extensions import db
from app.models import (Detection, HarvestRecord, ImageRecord, InspectionPlan, Orchard, Plot,
                        RecognitionRun, ReportRecord, YieldEstimate)
from app.services import detector
from app.services.storage import storage_root
from app.services.yield_service import FORMULA

random.seed(20261027)
BASE = Path(__file__).resolve().parent.parent
SOURCE_IMAGES = sorted((BASE / "素材" / "检测样张").glob("*.jpg"))
SOURCE_CACHE = {}

OWNERS = ["陈志强", "李美玲", "黄伟", "周敏", "梁海峰"]
SEASONS = [
    (date(2025, 3, 10), "春梢期"),
    (date(2025, 8, 15), "膨果期"),
    (date(2026, 5, 20), "保果期"),
    (date(2026, 10, 15), "成熟期"),
    (date(2026, 12, 10), "越冬期"),
]


def backup_db():
    uri = db.engine.url.database
    src = Path(uri)
    if not src.is_absolute():
        src = BASE / src
    if not src.exists():
        return None
    dst_dir = BASE / "instance" / "backups"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"orchard_before_industry_{datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(src, dst)
    return dst


def reset_data():
    # 先删子表，再删主表
    for model in (Detection, RecognitionRun, ImageRecord, YieldEstimate, HarvestRecord,
                  ReportRecord, InspectionPlan, Plot, Orchard):
        db.session.query(model).delete()
    db.session.commit()
    try:
        names = ",".join(f"'{m.__tablename__}'" for m in
                         (Detection, RecognitionRun, ImageRecord, YieldEstimate, HarvestRecord,
                          ReportRecord, InspectionPlan, Plot, Orchard))
        db.session.execute(text(f"DELETE FROM sqlite_sequence WHERE name IN ({names})"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    for sub in ("originals", "results", "reports"):
        folder = storage_root() / sub
        if folder.exists():
            for p in folder.rglob("*"):
                if p.is_file():
                    p.unlink()


def make_orchards():
    core = Orchard(code="XH-CORE", name="新会陈皮柑现代农业产业园（核心区）",
                   region="广东省江门市新会区双水镇", area_mu=680, variety="茶枝柑",
                   planting_date=date(2016, 3, 1), density=55, expected_trees=37400,
                   remark="产业级演示数据：水肥一体化核心种植区", is_demo=True)
    base = Orchard(code="XH-SS", name="新会柑标准化种植示范基地",
                   region="广东省江门市新会区三江镇", area_mu=320, variety="茶枝柑",
                   planting_date=date(2018, 2, 1), density=50, expected_trees=16000,
                   remark="产业级演示数据：标准化示范园", is_demo=True)
    db.session.add_all([core, base])
    db.session.flush()

    core_areas = [36] + [28] * 23
    base_areas = [34] + [26] * 11
    plots = []
    for i, area in enumerate(core_areas, 1):
        plots.append(Plot(orchard_id=core.id, code=f"A{i:02d}", name=f"A{i:02d} 片区",
                          area_mu=area, tree_count=round(area * core.density),
                          variety="茶枝柑", latitude=22.46 + i * 0.0005,
                          longitude=113.03 + i * 0.0006, is_demo=True))
    for i, area in enumerate(base_areas, 1):
        plots.append(Plot(orchard_id=base.id, code=f"B{i:02d}", name=f"B{i:02d} 片区",
                          area_mu=area, tree_count=round(area * base.density),
                          variety="茶枝柑", latitude=22.41 + i * 0.0005,
                          longitude=113.08 + i * 0.0006, is_demo=True))
    db.session.add_all(plots)
    db.session.commit()
    return [core, base], plots


def prepare_sources():
    """对每张真实图片跑一次模型，缓存检测框；后续图片复用同一批框。"""
    for p in SOURCE_IMAGES:
        result = detector.detect(str(p), "yolo")
        SOURCE_CACHE[p] = {
            "dets": result["detections"],
            "img": result["image"],
            "w": result["image"].shape[1],
            "h": result["image"].shape[0],
            "model": result["model_name"],
            "device": result["device"],
            "duration": result["duration_ms"],
        }
        print(f"  样张 {p.name}: {len(result['detections'])} 个目标")


def make_plans(orchards, plots):
    for oi, season in enumerate(SEASONS):
        planned, label = season
        for plot in plots:
            orchard = next(o for o in orchards if o.id == plot.orchard_id)
            canceled = random.random() < 0.04
            if planned <= date(2026, 9, 30):
                status = "已取消" if canceled else "已完成"
            elif planned <= date(2026, 10, 20):
                status = "已取消" if canceled else random.choice(["已完成", "进行中"])
            else:
                status = "待执行"
            plan = InspectionPlan(name=f"{plot.code} {label}巡检", orchard_id=orchard.id,
                                  plot_id=plot.id, planned_date=planned,
                                  executed_date=planned if status == "已完成" else None,
                                  owner=random.choice(OWNERS),
                                  method="无人机航拍" if random.random() < 0.55 else "手持拍摄",
                                  status=status, remark="产业级演示数据", is_demo=True)
            db.session.add(plan)
            db.session.flush()
            if status in ("已完成", "进行中"):
                n_images = random.randint(2, 3) if status == "已完成" else random.randint(1, 2)
                for k in range(n_images):
                    add_image(plan, orchard, plot, planned, k)
            if oi == 0 and plot.id % 10 == 0:
                db.session.commit()
    db.session.commit()


def add_image(plan, orchard, plot, planned, k):
    src, meta = random.choice(list(SOURCE_CACHE.items()))
    uid = uuid.uuid4().hex
    folder = f"{planned.year}/{planned.month:02d}"
    orig_rel = f"originals/{folder}/{uid}.jpg"
    result_rel = f"results/{folder}/{uid}.jpg"
    orig = storage_root() / orig_rel
    result = storage_root() / result_rel
    orig.parent.mkdir(parents=True, exist_ok=True)
    result.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, orig)
    dets = meta["dets"]
    detector.draw_result(meta["img"], dets, result)
    captured = datetime.combine(planned, datetime.min.time()) + timedelta(hours=8 + k)
    img = ImageRecord(plan_id=plan.id, original_name=f"{plot.code}_{planned:%Y%m%d}_{k+1}.jpg",
                      stored_path=orig_rel, file_size=orig.stat().st_size,
                      width=meta["w"], height=meta["h"],
                      captured_at=captured, sample_trees=random.randint(6, 10),
                      latitude=plot.latitude, longitude=plot.longitude,
                      status="已识别", archived=random.random() < 0.12,
                      is_abnormal=random.random() < 0.03,
                      remark="演示数据：检测框由当前 YOLO 模型实际推理生成",
                      is_demo=True,
                      source="无人机航拍" if plan.method == "无人机航拍" else "手持拍摄")
    db.session.add(img)
    db.session.flush()

    class_counts = {}
    size_counts = {}
    maturity_counts = {}
    for d in dets:
        class_counts[d["class_name"]] = class_counts.get(d["class_name"], 0) + 1
        size_counts[d["size_grade"]] = size_counts.get(d["size_grade"], 0) + 1
        maturity_counts[d["maturity"]] = maturity_counts.get(d["maturity"], 0) + 1
    total = len(dets)
    reviewed = max(1, total + random.randint(-4, 4)) if random.random() < 0.35 else None
    run = RecognitionRun(image_id=img.id, mode="yolo", model_name=meta["model"],
                         conf_threshold=0.25, device=meta["device"], status="成功",
                         total_count=total, class_counts=class_counts,
                         size_counts=size_counts, maturity_counts=maturity_counts,
                         result_path=result_rel, duration_ms=meta["duration"],
                         reviewed_count=reviewed,
                         review_note="人工复核：与模型计数基本一致" if reviewed else None,
                         reviewed_at=captured + timedelta(hours=2) if reviewed else None,
                         created_at=captured)
    db.session.add(run)
    db.session.flush()
    for d in dets:
        db.session.add(Detection(run_id=run.id, class_id=d["class_id"],
                                 class_name=d["class_name"], confidence=d["confidence"],
                                 x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"],
                                 area_ratio=d["area_ratio"], size_grade=d["size_grade"],
                                 maturity=d["maturity"]))


def add_yields(orchards, plots):
    for orchard in orchards:
        for year in (2024, 2025, 2026):
            target = orchard.expected_trees
            trees = 8
            per_tree = random.randint(560, 640)
            fruit = per_tree * trees
            weight = random.uniform(58, 62)
            est_fruit = fruit / trees * target * 1.0
            kg = est_fruit * weight / 1000
            db.session.add(YieldEstimate(
                level="全园", orchard_id=orchard.id, count_source="reviewed",
                sample_images=8, sample_fruit_count=fruit, sample_tree_count=trees,
                avg_fruit_per_tree=per_tree, target_tree_count=target, correction_factor=1.0,
                avg_fruit_weight_g=round(weight, 1), est_fruit_count=round(est_fruit),
                est_yield_kg=round(kg, 1), class_breakdown={"orange": round(est_fruit)},
                formula=FORMULA, remark="产业级演示数据", is_demo=True,
                created_at=datetime(year, 10, 15, 9, 0)))
            for plot in random.sample([p for p in plots if p.orchard_id == orchard.id], 8):
                trees2 = 8
                per_tree2 = random.randint(560, 640)
                fruit2 = per_tree2 * trees2
                est2 = fruit2 / trees2 * plot.tree_count * 1.0
                kg2 = est2 * weight / 1000
                db.session.add(YieldEstimate(
                    level="地块", orchard_id=orchard.id, plot_id=plot.id,
                    count_source="reviewed", sample_images=3, sample_fruit_count=fruit2,
                    sample_tree_count=trees2, avg_fruit_per_tree=per_tree2,
                    target_tree_count=plot.tree_count, correction_factor=1.0,
                    avg_fruit_weight_g=round(weight, 1), est_fruit_count=round(est2),
                    est_yield_kg=round(kg2, 1), class_breakdown={"orange": round(est2)},
                    formula=FORMULA, remark="产业级演示数据", is_demo=True,
                    created_at=datetime(year, 10, 15, 10, 0)))
    db.session.commit()


def add_harvest(orchards):
    for orchard in orchards:
        for year, ratio in ((2024, 0.94), (2025, 1.03)):
            est = (YieldEstimate.query.filter_by(orchard_id=orchard.id, level="全园", is_demo=True)
                   .filter(extract("year", YieldEstimate.created_at) == year).first())
            if not est:
                continue
            db.session.add(HarvestRecord(orchard_id=orchard.id, year=year,
                                         actual_yield_kg=round(est.est_yield_kg * ratio, 1),
                                         avg_price=round(random.uniform(20, 26), 1),
                                         note="产业级演示数据：实际采收", is_demo=True,
                                         created_at=datetime(year, 12, 20, 10, 0)))
    db.session.commit()


def main():
    app = create_app()
    with app.app_context():
        backup = backup_db()
        reset_data()
        orchards, plots = make_orchards()
        print("真实图片推理：")
        prepare_sources()
        make_plans(orchards, plots)
        add_yields(orchards, plots)
        add_harvest(orchards)
        try:
            db.session.execute(text("PRAGMA journal_mode=WAL"))
            db.session.execute(text("PRAGMA optimize"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        counts = {
            "果园": Orchard.query.count(), "地块": Plot.query.count(),
            "巡检计划": InspectionPlan.query.count(), "影像": ImageRecord.query.count(),
            "识别记录": RecognitionRun.query.count(), "检测框": Detection.query.count(),
            "估产": YieldEstimate.query.count(), "采收": HarvestRecord.query.count(),
        }
        print("已生成产业级演示数据：")
        for k, v in counts.items():
            print(f"  {k}: {v}")
        if backup:
            print(f"旧数据库备份：{backup}")


if __name__ == "__main__":
    main()