"""把 UNIPA Oranges 数据集整理成可直接训练的 YOLO 目录（按果树分组划分，避免同树泄漏）。

数据来源：LUCAS et al. (2025), "Oranges in the field", Mendeley Data, CC BY-NC 3.0
https://doi.org/10.17632/93f32zgkxz.1

用法：python scripts/build_unipa_dataset.py --max-train 2000 --max-val 400
"""
import argparse
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "datasets/unipa/data/Oranges in the field"
OUT = ROOT / "datasets/orange_orchard"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-train", type=int, default=2000)
    ap.add_argument("--max-val", type=int, default=400)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    groups = defaultdict(list)  # 果树编号 -> [(img, label)]
    for env in sorted(SRC.iterdir()):
        if not env.is_dir():
            continue
        for img in (env / "images").glob("*.jpg"):
            lab = env / "labels" / (img.stem + ".txt")
            if lab.is_file() and lab.stat().st_size > 0:
                groups[img.stem.split("_")[0]].append((img, lab, env.name))
    print("果树分组", len(groups), "图片", sum(len(v) for v in groups.values()))

    keys = sorted(groups)
    random.Random(args.seed).shuffle(keys)
    val, train = [], []
    for k in keys:
        if len(val) < args.max_val:
            val.extend(groups[k])
        elif len(train) < args.max_train:
            train.extend(groups[k])
    train, val = train[: args.max_train], val[: args.max_val]
    print("训练", len(train), "验证", len(val))

    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        d = OUT / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*"):
            f.unlink()

    manifest = []
    for split, items in (("train", train), ("val", val)):
        for img, lab, env in items:
            shutil.copy2(img, OUT / "images" / split / img.name)
            shutil.copy2(lab, OUT / "labels" / split / lab.name)
            manifest.append({"file": img.name, "split": split, "env": env})

    (OUT / "data.yaml").write_text(
        f"path: {OUT.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: orange\n",
        encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    (OUT / "SOURCE.txt").write_text(
        "Oranges in the field (UNIPA Oranges Dataset)\n"
        "LUCAS, B. et al. (2025), Mendeley Data, v1, doi:10.17632/93f32zgkxz.1\n"
        "License: CC BY-NC 3.0 — 仅用于非商业的教学/毕业设计\n", encoding="utf-8")
    print("完成 ->", OUT)


if __name__ == "__main__":
    main()
