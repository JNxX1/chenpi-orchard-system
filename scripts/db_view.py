"""查看 SQLite 数据库内容（只读，不会修改数据）。

用法：
    python scripts/db_view.py                     # 列出所有表和行数
    python scripts/db_view.py --table orchards    # 查看某张表的内容（默认最多 20 行）
    python scripts/db_view.py --table images --limit 5
    python scripts/db_view.py --sql "select id,name from orchards"

数据库文件：instance/orchard.db（可用 DATABASE_URL 环境变量改变位置）
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "instance" / "orchard.db"


def connect():
    db = Path(DEFAULT_DB)
    if not db.is_file():
        sys.exit(f"数据库不存在：{db}（先运行 python run.py 初始化）")
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True), db


def show_table(con, name, limit):
    exists = con.execute("select name from sqlite_master where type='table' and name=?",
                         (name,)).fetchone()
    if not exists:
        print(f"没有这张表：{name}")
        return
    cur = con.execute(f'select * from "{name}" limit ?', (limit,))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(" | ".join(cols))
    print("-" * 80)
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    total = con.execute(f'select count(*) from "{name}"').fetchone()[0]
    print(f"\n（共 {total} 行，显示 {len(rows)} 行）")


def main():
    ap = argparse.ArgumentParser(description="只读查看数据库")
    ap.add_argument("--table", help="表名，例如 orchards")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--sql", help="只读 SQL 查询，例如 select count(*) from images")
    args = ap.parse_args()

    con, db = connect()
    print(f"数据库：{db}（{db.stat().st_size / 1024:.1f} KB）\n")
    if args.sql:
        cur = con.execute(args.sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        if cols:
            print(" | ".join(cols))
        for row in cur.fetchall():
            print(" | ".join("" if v is None else str(v) for v in row))
    elif args.table:
        show_table(con, args.table, args.limit)
    else:
        rows = con.execute("select name from sqlite_master where type='table' order by name").fetchall()
        print(f"{'表名':<20}{'行数':>6}")
        for (name,) in rows:
            n = con.execute(f'select count(*) from "{name}"').fetchone()[0]
            print(f"{name:<20}{n:>6}")
        print("\n查看某张表： python scripts/db_view.py --table orchards")
    con.close()


if __name__ == "__main__":
    main()
