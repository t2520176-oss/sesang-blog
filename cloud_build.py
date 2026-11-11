"""Cloud version (GitHub Actions): write blog posts with real photos while the PC is off.

Runs on GitHub's server once a day (or by hand with a topic). It never touches Naver:
it only builds pages in docs/ that the phone opens, and the user pastes into Naver.

env: GEMINI_API_KEY (required), PIXABAY_KEY (optional), TOPIC (optional, manual run),
     THRESHOLD (default 5000), PHOTOS (default 3), LENGTH (default 1500)
"""
import datetime as dt
import html
import json
import os
import shutil
import sys
from pathlib import Path

import compose
import trends
import writer

HERE = Path(__file__).parent
DOCS = HERE / "docs"
POSTS = DOCS / "posts"
INDEX = DOCS / "posts.json"
KEEP = 40                                   # keep the newest N posts on the site
KST = dt.timezone(dt.timedelta(hours=9))


def log(*a):
    print(*a, flush=True)


def pick_topic(manual, threshold, seen):
    """-> (keyword, mode, news, traffic) or None"""
    try:
        hot = trends.fetch_trends(30)
    except Exception as e:  # noqa: BLE001
        log("트렌드 읽기 실패:", e)
        hot = []
    if manual:
        t = next((t for t in hot if t["keyword"] == manual), None)
        return manual, ("search" if t else "home"), (t["news"] if t else None), (t["traffic"] if t else "")
    hot = [t for t in hot if t["traffic_n"] >= threshold and t["keyword"] not in seen]
    if not hot:
        return None
    t = max(hot, key=lambda x: x["traffic_n"])
    return t["keyword"], "search", t["news"], t["traffic"]


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        sys.exit("GEMINI_API_KEY 비밀값이 없습니다 (GitHub 저장소 Settings > Secrets).")
    manual = os.environ.get("TOPIC", "").strip()
    threshold = int(os.environ.get("THRESHOLD") or 5000)
    photos = int(os.environ.get("PHOTOS") or 3)
    length = int(os.environ.get("LENGTH") or 1500)
    style = (HERE / "style.txt").read_text(encoding="utf-8") if (HERE / "style.txt").exists() else ""

    items = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
    today = dt.datetime.now(KST).date().isoformat()
    if not manual and any(i["date"].startswith(today) and i.get("auto") for i in items):
        log("오늘 자동 글은 이미 만들었습니다.")
        return write_index(items)

    got = pick_topic(manual, threshold, {i["keyword"] for i in items})
    if not got:
        log(f"검색량 {threshold}+ 새 이슈가 없습니다.")
        return write_index(items)
    keyword, mode, news, traffic = got
    log(f"주제: {keyword} ({traffic or '직접 입력'}) - 글 쓰는 중...")
    post = writer.generate_post(key, keyword, mode, length, news=news, photos=photos, style=style)

    compose.ROOT = HERE / "_build"
    page = compose.build(post, keyword, "", os.environ.get("PIXABAY_KEY", ""), log=log)
    slug, n = page.parent.name[:13], 1          # ascii url: 20261111_2228
    while (POSTS / slug).exists():
        n += 1
        slug = f"{page.parent.name[:13]}_{n}"
    dest = POSTS / slug
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(page, dest / "index.html")          # photos are inside the html already
    thumb = page.parent / "사진1.jpg"
    if thumb.exists():
        shutil.copy(thumb, dest / "thumb.jpg")
    items.insert(0, {"title": post["title"], "keyword": keyword, "traffic": traffic, "slug": slug,
                     "date": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "auto": not manual,
                     "thumb": thumb.exists()})
    for old in items[KEEP:]:
        shutil.rmtree(POSTS / old["slug"], ignore_errors=True)
    items = items[:KEEP]
    write_index(items)
    site = os.environ.get("SITE_URL", "").rstrip("/")
    (HERE / "_notify.json").write_text(json.dumps({
        "title": post["title"], "keyword": keyword, "traffic": traffic,
        "url": f"{site}/posts/{slug}/" if site else ""}, ensure_ascii=False), encoding="utf-8")
    log("완성:", post["title"])


def write_index(items):
    DOCS.mkdir(exist_ok=True)
    INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    (DOCS / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    e = html.escape
    rows = "".join(
        f'<a class="card" href="posts/{e(i["slug"])}/">'
        + (f'<img src="posts/{e(i["slug"])}/thumb.jpg" alt="">' if i.get("thumb") else '<div class="noimg">📝</div>')
        + f'<div><b>{e(i["title"])}</b><small>{e(i["date"])} · {e(i["keyword"])}'
        + (f' · 검색 {e(i["traffic"])}' if i.get("traffic") else "")
        + ('' if i.get("auto") else ' · 직접 요청') + '</small></div></a>'
        for i in items) or '<p class="empty">아직 만든 글이 없습니다. 첫 자동 실행을 기다리거나 [글 새로 만들기]를 누르세요.</p>'
    (DOCS / "index.html").write_text(INDEX_PAGE.replace("{{ROWS}}", rows), encoding="utf-8")


INDEX_PAGE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>세상관찰자 글 창고</title>
<style>
 body{margin:0;background:#f4f5f7;font-family:-apple-system,'Malgun Gothic',sans-serif;color:#222}
 header{background:#03c75a;color:#fff;padding:16px}
 header h1{margin:0;font-size:20px}header p{margin:6px 0 0;font-size:13px;opacity:.95;line-height:1.5}
 main{max-width:720px;margin:0 auto;padding:12px}
 .card{display:flex;gap:12px;align-items:center;background:#fff;border-radius:10px;padding:10px;margin-bottom:10px;
   text-decoration:none;color:inherit;box-shadow:0 1px 3px #0001}
 .card img,.noimg{width:84px;height:84px;object-fit:cover;border-radius:8px;flex:none;background:#eef;display:grid;place-items:center;font-size:30px}
 .card b{display:block;font-size:15px;line-height:1.4}.card small{color:#888;font-size:12px}
 .card>div{min-width:0;word-break:keep-all;overflow-wrap:anywhere}
 .empty{text-align:center;color:#888;padding:40px 0}
</style></head><body>
<header><h1>📝 세상관찰자 글 창고</h1>
<p>매일 화제 이슈로 사진 포함 글이 자동으로 쌓입니다. 글을 열어 [제목 복사] → [본문 복사] 후 네이버 앱에 붙여넣으세요.
사진은 길게 눌러 저장할 수 있어요.</p></header>
<main>{{ROWS}}</main>
</body></html>
"""

if __name__ == "__main__":
    main()
