# datasets/ 数据目录

| 目录/文件 | 内容 | 说明 |
|---|---|---|
| orange_orchard/ | 训练用 YOLO 数据集 | 2000 训练 / 400 验证（按果树分组），来自 UNIPA |
| unipa/ | 原始数据 | `data/Oranges in the field`，9 个环境共 5025 张；CC BY-NC 3.0，仅非商业使用 |
| orange_coco/ | 历史对比数据 | COCO orange 76 张（已不再用于线上模型） |
| chenpigan/ | 空模板 | `data.yaml` + 目录说明，用于将来放本地陈皮柑标注 |
| coco_val_instances.json | COCO 标注文件 | 约 20 MB，构建 orange_coco 时使用 |

图片与标注体积较大，已在 `.gitignore` 中忽略；换电脑时按需复制或重新运行 `scripts/download_unipa.py`。

## 数据引用

LUCAS B, CARELLA A, EL GHAZOUALI S, 等. Oranges in the field[DS/OL]. Mendeley Data, 2025, v1. https://doi.org/10.17632/93f32zgkxz.1. CC BY-NC 3.0.
