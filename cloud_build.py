"""Cloud version (GitHub Actions): write blog posts with real photos while the PC is off.

Runs on GitHub's server once a day (or by hand with a topic). It never touches Naver:
it only builds pages in docs/ that the phone opens, and the user pastes into Naver.

env: GEMINI_API_KEY (required), PIXABAY_KEY (optional), TOPIC (optional, manual run),
     THRESHOLD (default 1000), PHOTOS (default 3), LENGTH (default 1500)

Up to 3 auto posts a day (KST 8, 12, 19 h slots; a missed slot is caught up on the next run).
Each post aims at a narrower Naver autocomplete phrase ("이종석 아이유"), not the bare keyword.
"""
import datetime as dt
import html
import json
import os
import shutil
import sys
from pathlib import Path

import requests

import compose
import trends
import writer

HERE = Path(__file__).parent
DOCS = HERE / "docs"
POSTS = DOCS / "posts"
INDEX = DOCS / "posts.json"
KEEP = 40                                   # keep the newest N posts on the site
KST = dt.timezone(dt.timedelta(hours=9))


SLOTS = (8, 12, 19)                         # KST hours: one auto post per slot
SKIP = ("나무위키", "위키", "mbti", "인스타", "유튜브", "갤러리")


def related(keyword):
    """Naver search autocomplete phrases for the keyword (public, no login)."""
    try:
        r = requests.get("https://ac.search.naver.com/nx/ac", timeout=15, params={
            "q": keyword, "con": "1", "frm": "nv", "ans": "2", "r_format": "json",
            "r_enc": "UTF-8", "r_unicode": "0", "t_koreng": "1", "st": "100"})
        got = [x[0] for x in r.json()["items"][0]]
    except Exception as e:  # noqa: BLE001
        log("자동완성 읽기 실패:", e)
        return []
    return [g for g in got if g != keyword and not any(k in g.lower() for k in SKIP)][:8]


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
    hot = [t for t in hot if t["keyword"] not in seen]
    big = [t for t in hot if t["traffic_n"] >= threshold] or [t for t in hot if t["traffic_n"] >= 200]
    if not big:
        return None
    # among the 6 biggest, prefer the issue people search to *do* something about
    # (방법·신청·일정·조회…), not just gossip; ties go to the bigger search volume
    best = None
    for t in sorted(big, key=lambda x: -x["traffic_n"])[:6]:
        sub = related(t["keyword"])
        score = sum(any(w in s for w in HELP) for s in sub) + (2 if any(w in t["keyword"] for w in HELP) else 0)
        log(f"  후보 {t['keyword']} ({t['traffic']}) 도움 점수 {score}: {sub}")
        if best is None or score > best[0]:
            best = (score, t)
    t = best[1]
    return t["keyword"], "search", t["news"], t["traffic"]


HELP = ("방법", "신청", "조회", "일정", "대상", "기간", "지원", "환급", "요금", "가격", "시간", "운행",
        "파업", "중계", "날씨", "금리", "세금", "혜택", "뜻", "이유", "정리", "영향", "대처", "확인",
        "예약", "접수", "결과", "발표", "개정", "변경", "할인", "보상", "증상", "예방", "후기", "비교")


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        sys.exit("GEMINI_API_KEY 비밀값이 없습니다 (GitHub 저장소 Settings > Secrets).")
    manual = os.environ.get("TOPIC", "").strip()
    threshold = int(os.environ.get("THRESHOLD") or 1000)
    photos = int(os.environ.get("PHOTOS") or 3)
    length = int(os.environ.get("LENGTH") or 1500)
    style = (HERE / "style.txt").read_text(encoding="utf-8") if (HERE / "style.txt").exists() else ""

    items = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
    now = dt.datetime.now(KST)
    today = now.date().isoformat()
    passed = [h for h in SLOTS if now.hour >= h]
    # one post per slot; a missed slot is not piled up later (no 3 posts at night)
    start = f"{today} {passed[-1]:02d}:00" if passed else None
    if not manual and (not start or any(i.get("auto") and i["date"] >= start for i in items)):
        log(f"이번 시간대 글은 이미 있음 - 다음 시간대까지 기다립니다 ({'/'.join(map(str, SLOTS))}시).")
        return write_index(items)

    got = pick_topic(manual, threshold, {i["keyword"] for i in items})
    if not got:
        log(f"검색량 {threshold}+ 새 이슈가 없습니다.")
        return write_index(items)
    keyword, mode, news, traffic = got
    sub = related(keyword)
    log(f"주제: {keyword} ({traffic or '직접 입력'}) / 세부 키워드 후보: {sub} - 글 쓰는 중...")
    extra = ""
    if sub:
        extra = ("네이버 자동완성 검색어: " + ", ".join(sub) + "\n"
                 "이 중 뉴스 내용과 맞고, 검색하는 사람에게 실제 도움이 되는(방법·일정·대상·영향 등) 세부 키워드 1개를 골라 제목 맨 앞에 그대로 쓰고(띄어쓰기 그대로), "
                 "본문에 자연스럽게 3~4번 넣는다. 관련 있는 다른 검색어 1~2개는 소제목에 녹인다. "
                 "뉴스와 상관없는 검색어는 쓰지 않는다.\n")
    post = writer.generate_post(key, keyword, mode, length, extra=extra, news=news, photos=photos, style=style)

    publish(post, keyword, traffic, auto=not manual, items=items)


def publish(post, keyword, traffic="", auto=False, items=None, own=None, kind=""):
    """Build the post page into docs/, update the list and _notify.json. Returns the post url."""
    if items is None:
        items = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
    compose.ROOT = HERE / "_build"
    page = compose.build(post, keyword, "", os.environ.get("PIXABAY_KEY", ""), log=log, own=own)
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
                     "date": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "auto": auto,
                     "thumb": thumb.exists(), "kind": kind})
    for old in items[KEEP:]:
        shutil.rmtree(POSTS / old["slug"], ignore_errors=True)
    items = items[:KEEP]
    write_index(items)
    site = os.environ.get("SITE_URL", "").rstrip("/")
    url = f"{site}/posts/{slug}/" if site else ""
    (HERE / "_notify.json").write_text(json.dumps({
        "title": post["title"], "keyword": keyword, "traffic": traffic, "url": url,
        "kind": kind}, ensure_ascii=False), encoding="utf-8")
    log("완성:", post["title"])
    return url


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
        + (' · 🛍 내돈내산' if i.get("kind") == "review" else '' if i.get("auto") else ' · 직접 요청')
        + '</small></div></a>'
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
사진은 길게 눌러 저장할 수 있어요.</p>
<a href="up/" style="display:inline-block;margin-top:10px;background:#fff;color:#03a14a;font-weight:700;padding:8px 14px;border-radius:20px;text-decoration:none">📷 내돈내산 후기 올리기</a></header>
<main>{{ROWS}}</main>
</body></html>
"""

if __name__ == "__main__":
    main()
