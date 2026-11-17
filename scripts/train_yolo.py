"""YOLOv8 陈皮柑检测模型训练 / 验证脚本。

用法（在项目根目录）：
    python scripts/train_yolo.py --data datasets/chenpigan/data.yaml --epochs 100
    python scripts/train_yolo.py --val-only --weights models/chenpigan_best.pt

训练完成后，脚本打印 runs 目录下 best.pt 的位置与验证集真实指标；
确认效果后，手动复制到 models/chenpigan_best.pt（脚本不会自动覆盖已有模型）。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_dataset(data_yaml):
    import yaml
    cfg = yaml.safe_load(Path(data_yaml).read_text(encoding="utf-8"))
    base = (ROOT / cfg["path"]) if not Path(cfg["path"]).is_absolute() else Path(cfg["path"])
    counts = {}
    for split in ("train", "val"):
        imgs = [p for p in (base / cfg[split]).glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
        labels = list((base / cfg[split].replace("images", "labels")).glob("*.txt"))
        counts[split] = (len(imgs), len(labels))
    print("数据集统计（图片数, 标注文件数）：", counts)
    if counts["train"][0] == 0 or counts["val"][0] == 0:
        sys.exit("训练集或验证集为空，请先准备标注数据（见 docs/模型接入说明.md）")
    # Ultralytics 会把相对 path 解析到其全局 datasets 目录，这里改写为绝对路径
    cfg["path"] = str(base.resolve())
    resolved = ROOT / "runs" / "data_resolved.yaml"
    resolved.parent.mkdir(exist_ok=True)
    resolved.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return str(resolved)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "datasets/chenpigan/data.yaml"))
    ap.add_argument("--model", default="yolov8n.pt", help="预训练起点，如 yolov8n.pt / yolov8s.pt")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="")
    ap.add_argument("--val-only", action="store_true")
    ap.add_argument("--weights", default=str(ROOT / "models/chenpigan_best.pt"))
    args = ap.parse_args()

    from ultralytics import YOLO
    data = check_dataset(args.data)
    if args.val_only:
        model = YOLO(args.weights)
    else:
        model = YOLO(args.model)
        model.train(data=data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                    device=args.device or None, project=str(ROOT / "runs"), name="chenpigan")
        best = Path(model.trainer.best)
        print("训练完成，最佳权重：", best)
        model = YOLO(str(best))
    m = model.val(data=data, imgsz=args.imgsz, device=args.device or None)
    metrics = {"precision": float(m.box.mp), "recall": float(m.box.mr),
               "mAP50": float(m.box.map50), "mAP50-95": float(m.box.map)}
    print("验证集真实指标：", json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
