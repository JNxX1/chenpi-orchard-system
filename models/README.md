# models/ 模型目录

| 文件 | 用途 | 说明 |
|---|---|---|
| orange_orchard_best.pt | **当前线上模型** | YOLOv8n，UNIPA 果园数据 2000/400 训练；P 0.807 / R 0.736 / mAP50 0.801 |
| orange_coco_best.pt | 历史对比 | COCO orange 76 张训练，mAP50 0.321，果园实拍基本检不出 |
| yolov8n.pt | COCO 预训练基线 | 只用于测试推理接口与作为训练起点，不是业务模型 |

`.gitignore` 已忽略 `*.pt`，权重不随 Git 分发。切换模型改 `.env` 的 `MODEL_PATH` 与 `MODEL_NOTE` 即可，代码不用动。
