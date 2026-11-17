"""端到端自检：通过真实 HTTP 请求走完业务闭环。

用法：
    python scripts/smoke_e2e.py                 # 默认 http://127.0.0.1:5000
    BASE_URL=http://127.0.0.1:5001 python scripts/smoke_e2e.py

脚本会新建一个“验证”果园及其地块/计划，上传 2 张自动生成的合成图片并识别，
创建估产记录，导出 Excel/PDF，最后查询助手。失败时以非 0 退出码结束。
"""
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import cv2
import numpy as np
import requests

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
TAG = os.environ.get("SMOKE_TAG", "E2E")
today = date.today().isoformat()

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  -> " + detail) if detail and not cond else ""))
    return cond


def make_image(path, seed):
    """生成一张合成果园图（绿色背景 + 橙色圆形果实），用于验证识别链路。"""
    rng = np.random.default_rng(seed)
    h, w = 720, 960
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :] = (40, 90, 40)
    for _ in range(400):
        x, y = rng.integers(0, w), rng.integers(0, h)
        cv2.circle(img, (int(x), int(y)), int(rng.integers(8, 30)),
                   tuple(int(v) for v in rng.integers(30, 110, 3)), -1)
    for i in range(28):
        cx, cy = int(rng.integers(60, w - 60)), int(rng.integers(80, h - 60))
        r = int(rng.integers(18, 42))
        cv2.circle(img, (cx, cy), r, (18, 120, 235), -1)
        cv2.circle(img, (cx - r // 3, cy - r // 3), max(3, r // 4), (120, 220, 255), -1)
    cv2.imwrite(str(path), img)


def login(s):
    """先尝试访问首页；若被重定向到登录页，则用管理员账号登录。"""
    r = s.get(BASE + "/dashboard", timeout=30, allow_redirects=False)
    if r.status_code == 200:
        print("  [PASS] 已处于登录状态")
        return True
    user = os.environ.get("SMOKE_USER", "admin")
    pwd = os.environ.get("SMOKE_PASS", "admin123")
    r = s.post(BASE + "/login", data={"username": user, "password": pwd}, timeout=30,
               allow_redirects=False)
    ok = r.status_code in (301, 302, 303) and "/login" not in r.headers.get("Location", "")
    check(f"登录（{user}）", ok, f"状态码 {r.status_code}，请检查 SMOKE_USER / SMOKE_PASS")
    return ok


def main():
    s = requests.Session()
    print(f"目标服务：{BASE}\n")

    print("[0] 登录")
    if not login(s):
        print("登录失败，后续检查没有意义。")
        return 1

    print("\n[1] 页面可访问性")
    for path in ["/", "/dashboard", "/orchards/", "/plots/", "/plans/", "/images/",
                 "/images/upload", "/live/", "/results/", "/yields/", "/yields/new",
                 "/reports/", "/assistant/", "/database/", "/api/charts", "/api/model-status"]:
        r = s.get(BASE + path, timeout=30)
        check(f"GET {path} -> 200", r.status_code == 200, str(r.status_code))

    print("\n[2] 建档：果园 / 地块 / 巡检计划")
    oc = s.post(BASE + "/orchards/new", data={
        "code": f"{TAG}-{date.today():%Y%m%d}-01", "name": f"{TAG} 验证果园",
        "region": "广东省江门市新会区", "area_mu": "30", "variety": "茶枝柑",
        "planting_date": "2019-03-01", "density": "55", "expected_trees": "1650",
        "remark": "端到端自检自动创建"}, timeout=30)
    check("创建果园", oc.status_code == 200 and "验证果园" in oc.text, str(oc.status_code))
    oid = int(oc.url.rstrip("/").split("/")[-1])

    r = s.post(BASE + "/plots/new", data={
        "orchard_id": oid, "code": "A-01", "name": "东坡地块", "area_mu": "12",
        "tree_count": "660", "variety": "茶枝柑", "remark": "自检"}, timeout=30)
    check("创建地块", r.status_code == 200, str(r.status_code))

    r = s.post(BASE + "/plans/new", data={
        "name": f"{TAG} 巡检批次", "orchard_id": oid, "plot_id": "",
        "planned_date": today, "owner": "自检", "method": "手持拍摄",
        "status": "待执行", "remark": "自检"}, timeout=30)
    check("创建巡检计划", r.status_code == 200 and "巡检批次" in r.text, str(r.status_code))
    plan_id = int(r.url.rstrip("/").split("/")[-1])

    print("\n[3] 上传影像并自动识别")
    tmp = Path(tempfile.mkdtemp(prefix="smoke_"))
    files = []
    for i in range(2):
        p = tmp / f"orchard_{i}.png"
        make_image(p, i + 1)
        files.append(("files", (p.name, p.read_bytes(), "image/png")))
    r = s.post(BASE + "/images/upload",
               data={"plan_id": plan_id, "sample_trees": "4", "auto_recognize": "1"},
               files=files, timeout=120)
    check("上传并自动识别", r.status_code == 200 and "自动识别完成" in r.text, str(r.status_code))
    check("识别结果已写入", "已识别" in r.text)

    plan_page = s.get(BASE + f"/plans/{plan_id}", timeout=30).text
    check("计划页面显示识别数量", ("目标" in plan_page) or ("已识别" in plan_page))

    print("\n[4] 结果查询与人工复核")
    res = s.get(BASE + "/results/", timeout=30)
    check("结果汇总页包含本批次", "巡检批次" in res.text)
    import re
    m = re.search(r"/images/(\d+)", res.text)
    img_id = int(m.group(1)) if m else None
    check("结果页可跳转影像详情", img_id is not None)
    if img_id:
        d = s.get(BASE + f"/images/{img_id}", timeout=30)
        check("影像详情页可打开", d.status_code == 200)
        rid = re.search(r"/results/run/(\d+)/review", d.text)
        if rid:
            rv = s.post(BASE + f"/results/run/{rid.group(1)}/review",
                        data={"reviewed_count": "25", "review_note": "自检人工复核"}, timeout=30)
            check("保存人工复核", rv.status_code == 200 and "人工复核" in rv.text)
        else:
            check("详情页含复核表单", False, "未找到复核表单")

    print("\n[5] 估产")
    r = s.post(BASE + "/yields/new", data={
        "level": "地块", "plan_id": plan_id, "plot_id": "", "count_source": "reviewed",
        "sample_fruit_count": "100", "sample_tree_count": "10", "target_tree_count": "",
        "correction_factor": "0.85", "avg_fruit_weight_g": "12.5",
        "remark": "端到端自检"}, timeout=60)
    check("创建地块级估产", r.status_code == 200 and "kg" in r.text, str(r.status_code))
    check("估产页面含公式", "公式" in r.text)

    print("\n[6] 报表导出")
    for fmt, magic in (("xlsx", b"PK"), ("pdf", b"%PDF")):
        r = s.post(BASE + "/reports/export",
                   data={"report_type": "yield", "orchard_id": oid, "fmt": fmt}, timeout=120)
        ok = r.status_code == 200 and r.content[:4].startswith(magic)
        check(f"导出 {fmt.upper()}（{len(r.content)} 字节）", ok, str(r.status_code))

    print("\n[7] 图表与助手")
    charts = s.get(BASE + "/api/charts", timeout=30).json()
    check("图表接口返回数据库数据", isinstance(charts, dict) and "class_counts" in charts)
    a = s.post(BASE + "/assistant/ask", json={"question": "系统概况"}, timeout=30)
    check("助手回答系统概况", a.status_code == 200 and "果园" in a.json().get("facts", ""))
    a2 = s.post(BASE + "/assistant/ask", json={"question": "未完成的任务"}, timeout=30)
    check("助手回答未完成任务", a2.status_code == 200 and a2.json().get("facts"))

    import base64
    sample = tmp / "live.png"
    make_image(sample, 9)
    live = s.post(BASE + "/live/detect",
                  json={"image": "data:image/png;base64," + base64.b64encode(sample.read_bytes()).decode()},
                  timeout=60)
    lj = live.json() if live.status_code == 200 else {}
    check(f"实时识别接口（{lj.get('count')} 个目标）", live.status_code == 200 and lj.get("ok") is True)

    print(f"\n结果：通过 {len(passed)} 项，失败 {len(failed)} 项")
    if failed:
        print("失败项：" + "、".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
