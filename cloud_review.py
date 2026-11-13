"""Cloud 내돈내산 review: photos posted as a GitHub issue -> review post with those photos.

The phone opens the GitHub app, makes a new issue in this repo with photos (title = product name,
body = short notes, both optional). GitHub Actions runs this, adds the post to the site and
sends the phone alert. Never touches Naver.

env: GEMINI_API_KEY, GH_TOKEN, ISSUE_TITLE, ISSUE_BODY, SITE_URL
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests

import cloud_build
import images
import writer

HERE = Path(__file__).parent
NO_NAME = {"", "후기", "리뷰", "내돈내산", "review", "사진", "new issue"}


def photo_urls(body):
    urls = re.findall(r'!\[[^\]]*\]\((https?://[^)\s]+)\)', body)
    urls += re.findall(r'<img[^>]+src="(https?://[^"]+)"', body)
    urls += re.findall(r'https://github\.com/user-attachments/assets/[\w-]+', body)   # phone app: bare links
    return list(dict.fromkeys(urls))[:8]


def notes_from(body):
    t = re.sub(r'!\[[^\]]*\]\([^)]*\)|<img[^>]*>', " ", body)
    t = re.sub(r'https?://github\.com/user-attachments/\S+', " ", t)
    t = re.sub(r'^###.*$|_No response_', " ", t, flags=re.M)      # issue-form headings
    return re.sub(r'[ \t]+', " ", t).strip()


def video_frames(data, work, i, n=3):
    """Take n sharp-ish stills from a video (ffmpeg) -> list of jpg Paths."""
    src = work / f"v{i}.mp4"
    src.write_bytes(data)
    try:                                     # pip imageio-ffmpeg ships its own ffmpeg (no apt-get)
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ff = shutil.which("ffmpeg") or "ffmpeg"
    try:
        info = subprocess.run([ff, "-i", str(src)], capture_output=True, text=True).stderr
    except OSError:
        return []
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0
    out = []
    if dur < 4:            # Galaxy "motion photo" clips are ~1.5 s: one still is enough
        n = 1
    for k in range(n):
        t = dur * (k + 1) / (n + 1)
        raw, jpg = work / f"v{i}_{k}_raw.jpg", work / f"v{i}_{k}.jpg"
        subprocess.run([ff, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src),
                        "-frames:v", "1", "-q:v", "2", str(raw)])
        if raw.exists() and images._save(raw.read_bytes(), jpg):
            out.append(jpg)
    print(f"동영상 {i}: {dur:.1f}초 -> 사진 {len(out)}장", flush=True)
    return out


def download(urls, token=""):
    """urls (photos or videos) -> list of jpg Paths (videos give 3 stills each)."""
    work = HERE / "_review"
    work.mkdir(exist_ok=True)
    paths = []
    for i, u in enumerate(urls, 1):
        h = dict(images.UA)
        if token and re.match(r"https://(github\.com|[\w.-]*githubusercontent\.com)/", u):
            h["Authorization"] = f"token {token}"     # GitHub attachments only
        r = requests.get(u, timeout=120, headers=h)
        r.raise_for_status()
        if r.headers.get("content-type", "").startswith("video"):
            paths += video_frames(r.content, work, i)    # videos -> a few still photos
            continue
        out = work / f"p{i}.jpg"
        if images._save(r.content, out):
            paths.append(out)
    return paths[:8]


SHOP_NOTICE = ("이 포스팅은 네이버 쇼핑 커넥트 활동의 일환으로, 판매 발생 시 수수료를 제공받습니다. "
               "제품은 제 돈으로 직접 구매해 사용했습니다.")


def shop_links(notes):
    """Pull shopping links out of the memo -> (links, notes without them)."""
    links = [u.rstrip(".,)") for u in re.findall(r"https?://[^\s<>\"']+", notes)
             if not re.match(r"https?://(github\.com|[\w.-]*githubusercontent\.com|ntfy\.sh)/", u)]
    for u in links:
        notes = notes.replace(u, " ")
    notes = re.sub(r"(구매|쇼핑|상품)?\s*링크\s*[:：]?\s*(?=\s|$)", " ", notes)
    return list(dict.fromkeys(links))[:3], re.sub(r"\s+", " ", notes).strip()


def add_shop_links(post, links):
    """Disclosure line at the top (공정위 rule) + link card(s) at the end."""
    if not links:
        return post
    blocks = [{"type": "notice", "text": SHOP_NOTICE}] + post["blocks"]
    for i, u in enumerate(links):
        blocks.append({"type": "link", "text": "🛒 제가 산 제품 보러 가기" + (f" {i + 1}" if len(links) > 1 else ""),
                       "url": u})
    blocks.append({"type": "notice", "text": SHOP_NOTICE})
    return {**post, "blocks": blocks}


def make_review(paths, hint="", notes=""):
    """Write the review from photo Paths, publish it. Returns (title, url)."""
    if not paths:
        raise SystemExit("사진을 읽지 못했습니다 (너무 작거나 이미지가 아님).")
    links, notes = shop_links(notes)
    if links:
        print(f"쇼핑 링크 {len(links)}개", flush=True)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    extra = f"사용자 메모(가격·구매처·써본 느낌): {notes}\n" if notes else ""
    if hint:   # may be a product name or just a note ("써보고말해요")
        extra += (f"사용자가 붙인 제목: '{hint}' - 제품 이름이면 그대로 쓰고, 제품 이름이 아니면 "
                  "메모로만 참고한다. 제품은 사진을 보고 파악한다.\n")
    style_f = HERE / "style_review.txt"
    style = style_f.read_text(encoding="utf-8") if style_f.exists() else ""
    print(f"후기 쓰는 중: 사진 {len(paths)}장 / 메모 {len(notes)}자", flush=True)
    post = writer.generate_post(key, "", "review", 2200, extra=extra, style=style,
                                own_photos=[p.read_bytes() for p in paths])
    post = add_shop_links(post, links)
    name = post["title"].split(",")[0].split("…")[0][:20]
    return post["title"], cloud_build.publish(post, name, own=paths, kind="review")


def main():
    title = os.environ.get("ISSUE_TITLE", "").strip()
    body = os.environ.get("ISSUE_BODY", "") or ""
    urls = photo_urls(body)
    if not urls:
        sys.exit("사진이 없습니다. 이슈 본문에 물건 사진을 1장 이상 붙여 주세요.")
    paths = download(urls, os.environ.get("GH_TOKEN", ""))
    # GitHub needs a title, so short ones ("1", "후기") mean "work it out from the photos"
    hint = "" if title.lower() in NO_NAME or len(title) <= 2 or title.isdigit() else title
    t, url = make_review(paths, hint, notes_from(body))
    (HERE / "_issue_reply.txt").write_text(
        f"✅ 후기 글 완성: **{t}**\n\n{url}\n\n열어서 [제목 복사] → [본문 복사] 후 네이버 앱에 붙여넣으세요.",
        encoding="utf-8")


if __name__ == "__main__":
    main()
