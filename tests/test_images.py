import io

from app.extensions import db
from app.models import ImageRecord, RecognitionRun
from app.services import detector
from tests.conftest import make_image


def upload(client, files, **extra):
    data = {"plan_id": "1", **extra}
    data["files"] = files
    return client.post("/images/upload", data=data, content_type="multipart/form-data",
                       follow_redirects=True)


def test_upload_multiple_and_storage(client, app, seeded):
    r = upload(client, [(make_image(), "a.jpg"), (make_image(".png"), "b.png")])
    assert "成功上传 2 张图片" in r.get_data(as_text=True)
    with app.app_context():
        imgs = ImageRecord.query.all()
        assert len(imgs) == 2
        assert all(i.stored_path.startswith("originals/") for i in imgs)
        assert imgs[0].stored_path != imgs[1].stored_path
        assert (app.config["STORAGE_DIR"] / imgs[0].stored_path).is_file()
        assert imgs[0].plan.status == "进行中"
    assert client.get("/images/file/1/original").status_code == 200


def test_upload_rejects_bad_files(client, app, seeded):
    r = upload(client, [(io.BytesIO(b"hello"), "x.txt")])
    assert "仅支持 JPG/JPEG/PNG" in r.get_data(as_text=True)
    r = upload(client, [(io.BytesIO(b"not an image"), "fake.jpg")])
    assert "不是有效的图片文件" in r.get_data(as_text=True)
    r = upload(client, [(make_image(".png"), "mismatch.jpg")])
    assert "文件内容与扩展名不符" in r.get_data(as_text=True)
    with app.app_context():
        assert ImageRecord.query.count() == 0


def test_upload_size_limit(client, app, seeded):
    app.config["MAX_IMAGE_SIZE"] = 1000
    r = upload(client, [(make_image(), "big.jpg")])
    assert "超过" in r.get_data(as_text=True)


def test_path_traversal_filename_is_ignored(client, app, seeded):
    upload(client, [(make_image(), "../../evil.jpg")])
    with app.app_context():
        img = ImageRecord.query.one()
        assert img.original_name == "evil.jpg"
        assert ".." not in img.stored_path


def test_model_missing_falls_back_to_demo(client, app, seeded):
    with app.app_context():
        st = detector.detector_status()
        assert not st["model_exists"] and not st["yolo_ready"]
    r = upload(client, [(make_image(n_fruits=3), "f.jpg")], auto_recognize="1")
    assert "自动识别完成：成功 1 张" in r.get_data(as_text=True)
    with app.app_context():
        run = RecognitionRun.query.one()
        assert run.mode == "opencv_demo" and run.status == "成功"
        assert run.total_count == 3 and run.detections.count() == 3
        assert run.image.status == "已识别"
        assert (app.config["STORAGE_DIR"] / run.result_path).is_file()
    html = client.get("/images/1").get_data(as_text=True)
    assert "演示模式" in html and "未配置陈皮柑专用 YOLO 模型" in html


def test_yolo_only_mode_fails_cleanly_without_model(client, app, seeded):
    upload(client, [(make_image(), "f.jpg")])
    r = client.post("/images/1/recognize", data={"mode": "yolo"}, follow_redirects=True)
    assert "识别失败" in r.get_data(as_text=True)
    with app.app_context():
        run = RecognitionRun.query.one()
        assert run.status == "失败" and "模型权重" in run.error_message
        assert run.image.status == "识别失败"


def test_demo_disabled_without_model(client, app, seeded):
    app.config["ALLOW_DEMO_DETECTOR"] = False
    upload(client, [(make_image(), "f.jpg")])
    client.post("/images/1/recognize", data={"mode": "auto"})
    with app.app_context():
        assert RecognitionRun.query.one().status == "失败"


def test_rerecognize_keeps_history_and_review(client, app, seeded):
    upload(client, [(make_image(n_fruits=2), "f.jpg")], auto_recognize="1")
    client.post("/images/1/recognize", data={"mode": "opencv_demo"})
    client.post("/results/run/2/review", data={"reviewed_count": "5", "review_note": "人工数果"})
    with app.app_context():
        runs = RecognitionRun.query.order_by(RecognitionRun.id).all()
        assert len(runs) == 2
        assert runs[1].total_count == 2 and runs[1].reviewed_count == 5
        assert runs[1].effective_count == 5
    s = client.get("/results/").get_data(as_text=True)
    assert "复核后总数" in s


def test_archive_blocks_delete(client, app, seeded):
    upload(client, [(make_image(), "f.jpg")], auto_recognize="1")
    client.post("/images/1/toggle/archived")
    r = client.post("/images/1/delete", follow_redirects=True)
    assert "已归档的影像不能删除" in r.get_data(as_text=True)
    client.post("/images/1/toggle/archived")
    with app.app_context():
        paths = [ImageRecord.query.one().stored_path, RecognitionRun.query.one().result_path]
    client.post("/images/1/delete")
    with app.app_context():
        assert ImageRecord.query.count() == 0 and RecognitionRun.query.count() == 0
    assert not any((app.config["STORAGE_DIR"] / p).exists() for p in paths)


def test_batch_recognize_plan(client, app, seeded):
    upload(client, [(make_image(), "a.jpg"), (make_image(), "b.jpg")])
    r = client.post("/images/plan/1/recognize", data={"scope": "pending"}, follow_redirects=True)
    assert "批量识别完成：成功 2 张" in r.get_data(as_text=True)
    with app.app_context():
        from app.models import InspectionPlan
        assert db.session.get(InspectionPlan, 1).progress() == {"total": 2, "recognized": 2, "percent": 100}
