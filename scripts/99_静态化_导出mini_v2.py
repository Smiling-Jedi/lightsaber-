"""
静态化导出 v2 — 把小光剑 /mini-v2/ 子系统冻结为 HTML 静态站点

用法:
    cd lightsaber && python scripts/99_静态化_导出mini_v2.py

输出:
    docs/mini-v2/
      ├── index.html              # 首页
      ├── stock/                  # 30 个详情页
      │   ├── HK_00700.html
      │   ├── ...
      └── (无 static 资源,模板里 CSS 都是 inline)

链接重写规则:
- index.html 里: /mini/v2/stock/HK:00700  → stock/HK_00700.html
- stock/X.html 里: /mini/v2/              → ../index.html
"""
import os
import re
import sys
import shutil
from pathlib import Path

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from starlette.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models.position import Position

# 输出目录
OUT_DIR = Path(project_root) / "docs" / "mini-v2"


def symbol_to_filename(symbol: str) -> str:
    """HK:00700 → HK_00700"""
    return symbol.replace(":", "_")


def rewrite_home_links(html: str) -> str:
    """首页里的详情页链接 /mini/v2/stock/HK:00700 → stock/HK_00700.html"""
    def replace(m):
        market, code = m.group(1), m.group(2)
        return f'stock/{market}_{code}.html'
    return re.sub(
        r'/mini/v2/stock/([A-Z]+):(\w+)',
        replace,
        html,
    )


def rewrite_detail_links(html: str) -> str:
    """详情页里的返回链接 /mini/v2/ → ../index.html"""
    html = html.replace('href="/mini/v2/"', 'href="../index.html"')
    html = html.replace("href='/mini/v2/'", "href='../index.html'")
    return html


def main():
    print("=" * 60)
    print("小光剑 /mini-v2/ → 静态 HTML 导出")
    print("=" * 60)

    # 清理旧输出
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    (OUT_DIR / "stock").mkdir()

    client = TestClient(app)

    # 1. 导出首页
    print("\n[1/2] 导出首页...")
    resp = client.get("/mini/v2/")
    if resp.status_code != 200:
        print(f"❌ 首页 GET 失败: status={resp.status_code}")
        return
    home_html = rewrite_home_links(resp.text)
    (OUT_DIR / "index.html").write_text(home_html, encoding="utf-8")
    print(f"  ✅ index.html ({len(home_html)} chars)")

    # 2. 导出所有详情页
    db = SessionLocal()
    try:
        positions = (
            db.query(Position)
            .filter(Position.total_shares > 0)
            .order_by(Position.stock_symbol)
            .all()
        )
        symbols = [p.stock_symbol for p in positions]
    finally:
        db.close()

    print(f"\n[2/2] 导出 {len(symbols)} 个详情页...")
    success = 0
    failed = []
    for symbol in symbols:
        try:
            resp = client.get(f"/mini/v2/stock/{symbol}")
            if resp.status_code != 200:
                failed.append(f"{symbol} (status={resp.status_code})")
                continue
            html = rewrite_detail_links(resp.text)
            filename = f"{symbol_to_filename(symbol)}.html"
            (OUT_DIR / "stock" / filename).write_text(html, encoding="utf-8")
            print(f"  ✅ stock/{filename}")
            success += 1
        except Exception as e:
            failed.append(f"{symbol}: {e}")
            print(f"  ❌ {symbol}: {e}")

    print(f"\n{'=' * 60}")
    print(f"导出完成: {success}/{len(symbols)} 个详情页")
    if failed:
        print(f"失败: {failed}")
    print(f"输出目录: {OUT_DIR}")
    print(f"本地预览: python -m http.server 8000 --directory {OUT_DIR}")
    print(f"线上地址: https://smiling-jedi.github.io/lightsaber-/mini-v2/")


if __name__ == "__main__":
    main()
