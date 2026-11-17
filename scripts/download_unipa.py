"""分块并行下载 UNIPA Oranges 数据集（Mendeley Data，CC BY-NC 3.0）。

单连接被限速到 ~25-70 KB/s，这里用多段 Range 请求并行下载，支持断点续传。
用法：
    python scripts/download_unipa.py --connections 16
完成后得到 datasets/unipa/unipa.zip，解压到 datasets/unipa/data/ 即可用于训练。
"""
import argparse
import os
import shutil
import threading
import time
from pathlib import Path

import requests

URL = "https://data.mendeley.com/public-api/zip/93f32zgkxz/download/1"
SIZE = 812649381
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OUT = Path(__file__).resolve().parent.parent / "datasets" / "unipa"

lock = threading.Lock()
done = 0


def worker(index, start, end, path):
    global done
    pos = path.stat().st_size if path.exists() else 0
    if pos >= end - start + 1:
        with lock:
            done += pos
        return
    for attempt in range(5):
        try:
            r = requests.get(URL, headers={**HEADERS, "Range": f"bytes={start + pos}-{end}"},
                             stream=True, timeout=60)
            if r.status_code not in (200, 206):
                raise RuntimeError(f"HTTP {r.status_code}")
            with open(path, "ab") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    pos += len(chunk)
                    with lock:
                        done += len(chunk)
            if pos >= end - start + 1:
                return
        except Exception as e:
            print(f"[{index}] retry {attempt + 1}: {e}", flush=True)
            time.sleep(3)
    raise RuntimeError(f"chunk {index} failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connections", type=int, default=16)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    parts = OUT / "parts"
    parts.mkdir(exist_ok=True)
    n = args.connections
    step = SIZE // n + 1
    ranges = [(i * step, min(SIZE - 1, (i + 1) * step - 1)) for i in range(n)]

    global done
    done = sum((parts / f"{i}.part").stat().st_size for i in range(n)
               if (parts / f"{i}.part").exists())
    print(f"start: {SIZE / 1024 / 1024:.0f} MB, already {done / 1024 / 1024:.1f} MB", flush=True)

    threads = [threading.Thread(target=worker, args=(i, s, e, parts / f"{i}.part"), daemon=True)
               for i, (s, e) in enumerate(ranges)]
    t0 = time.time()
    for t in threads:
        t.start()

    last = 0
    while any(t.is_alive() for t in threads):
        time.sleep(20)
        speed = (done - last) / 20 / 1024
        last = done
        pct = done * 100 / SIZE
        print(f"{pct:5.1f}%  {done / 1024 / 1024:7.1f} MB  {speed:6.0f} KB/s  "
              f"ETA {(SIZE - done) / max(speed * 1024, 1) / 60:5.1f} min", flush=True)

    with open(OUT / "unipa.zip", "wb") as f:
        for i in range(n):
            with open(parts / f"{i}.part", "rb") as pf:
                shutil.copyfileobj(pf, f)
    shutil.rmtree(parts, ignore_errors=True)
    print(f"done in {(time.time() - t0) / 60:.1f} min -> {OUT / 'unipa.zip'}", flush=True)


if __name__ == "__main__":
    main()
