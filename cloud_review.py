"""Cloud 내돈내산 review: photos posted as a GitHub issue -> review post with those photos.

The phone opens the GitHub app, makes a new issue in this repo with photos (title = product name,
body = short notes, both optional). GitHub Actions runs this, adds the post to the site and
sends the phone alert. Never touches Naver.

env: GEMINI_API_KEY, GH_TOKEN, ISSUE_TITLE, ISSUE_BODY, SITE_URL
"""
import os
import re
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


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    title = os.environ.get("ISSUE_TITLE", "").strip()
    body = os.environ.get("ISSUE_BODY", "") or ""
    token = os.environ.get("GH_TOKEN", "")
    urls = photo_urls(body)
    if not urls:
        sys.exit("사진이 없습니다. 이슈 본문에 물건 사진을 1장 이상 붙여 주세요.")

    work = HERE / "_review"
    work.mkdir(exist_ok=True)
    paths = []
    for i, u in enumerate(urls, 1):
        h = dict(images.UA)
        if token and re.match(r"https://(github\.com|[\w.-]*githubusercontent\.com)/", u):
            h["Authorization"] = f"token {token}"     # GitHub attachments only
        r = requests.get(u, timeout=60, headers=h)
        r.raise_for_status()
        out = work / f"p{i}.jpg"
        if images._save(r.content, out):
            paths.append(out)
    if not paths:
        sys.exit("사진을 읽지 못했습니다 (너무 작거나 이미지가 아님).")

    # title is required by GitHub, so anything short ("1", ".", "ㅎ", "후기") means "work it out from the photos"
    hint = "" if title.lower() in NO_NAME or len(title) <= 2 or title.isdigit() else title
    notes = notes_from(body)
    extra = f"사용자 메모(가격·구매처·써본 느낌): {notes}\n" if notes else ""
    if hint:   # the title may be a product name or just a note ("써보고말해요")
        extra += (f"사용자가 붙인 제목: '{hint}' - 제품 이름이면 그대로 쓰고, 제품 이름이 아니면 "
                  "메모로만 참고한다. 제품은 사진을 보고 파악한다.\n")
    product = ""
    style_f = HERE / "style_review.txt"
    style = style_f.read_text(encoding="utf-8") if style_f.exists() else ""
    print(f"후기 쓰는 중: {product or '(사진으로 파악)'} / 사진 {len(paths)}장 / 메모 {len(notes)}자", flush=True)
    post = writer.generate_post(key, product, "review", 1500, extra=extra, style=style,
                                own_photos=[p.read_bytes() for p in paths])
    name = post["title"].split(",")[0].split("…")[0][:20]
    url = cloud_build.publish(post, name, own=paths, kind="review")
    (HERE / "_issue_reply.txt").write_text(
        f"✅ 후기 글 완성: **{post['title']}**\n\n{url}\n\n열어서 [제목 복사] → [본문 복사] 후 네이버 앱에 붙여넣으세요.",
        encoding="utf-8")


if __name__ == "__main__":
    main()
