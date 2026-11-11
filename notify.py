"""Send a phone push (ntfy app) when cloud_build made a new post. No account needed.

The phone subscribes to the secret topic name (GitHub secret NTFY_TOPIC) in the ntfy app.
Waits until the GitHub Pages page is live, so tapping the alert opens the post.
"""
import json
import os
import time
from pathlib import Path

import requests

info_file = Path(__file__).with_name("_notify.json")
topic = os.environ.get("NTFY_TOPIC", "").strip()
if not topic or not info_file.exists():
    print("알림 없음 (새 글 없음 또는 NTFY_TOPIC 미설정)")
    raise SystemExit
info = json.loads(info_file.read_text(encoding="utf-8"))
url = info.get("url", "")
for _ in range(30):                      # up to ~5 min for Pages to deploy
    if not url or requests.get(url, timeout=15).status_code == 200:
        break
    time.sleep(10)
traffic = f" (검색 {info['traffic']})" if info.get("traffic") else ""
r = requests.post("https://ntfy.sh/", timeout=20, json={
    "topic": topic,
    "title": (f"후기 글 완성: {info['keyword']}" if info.get("kind") == "review"
              else f"새 블로그 글: {info['keyword']}{traffic}"),
    "message": info["title"] + "\n눌러서 열고 네이버에 붙여넣으세요.",
    "click": url, "tags": ["memo"], "priority": 4})
print("알림 전송:", r.status_code)
