"""Phone gallery -> Share -> ntfy -> review post. Checked every few minutes by GitHub Actions.

Photos (or videos) shared to the upload topic within a few minutes of each other become ONE
review post. Text messages sent with them are used as notes. Never touches Naver.

env: GEMINI_API_KEY, NTFY_UPLOAD_TOPIC, NTFY_TOPIC (alerts), SITE_URL
"""
import json
import os
import time
from pathlib import Path

import requests

import cloud_review

HERE = Path(__file__).parent
STATE = HERE / "inbox_state.json"
GAP = 180          # photos sent within 3 min of each other = one post
SETTLE = 90        # wait until the newest photo is this old (user may still be sending)


def fetch(topic, since):
    r = requests.get(f"https://ntfy.sh/{topic}/json", params={"poll": "1", "since": since}, timeout=30)
    r.raise_for_status()
    msgs = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    return sorted((m for m in msgs if m.get("event") == "message"), key=lambda m: m["time"])


def alert(title, message, click=""):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        requests.post("https://ntfy.sh/", timeout=20, json={
            "topic": topic, "title": title, "message": message, "click": click, "tags": ["memo"]})


def main():
    topic = os.environ.get("NTFY_UPLOAD_TOPIC", "").strip()
    if not topic:
        raise SystemExit("NTFY_UPLOAD_TOPIC 비밀값이 없습니다.")
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"since": "12h"}
    msgs = fetch(topic, st["since"])
    if not msgs:
        print("새로 받은 사진 없음")
        return
    batch = [msgs[0]]                       # oldest group first, one post per run
    for m in msgs[1:]:
        if m["time"] - batch[-1]["time"] > GAP:
            break
        batch.append(m)
    if len(batch) == len(msgs) and time.time() - batch[-1]["time"] < SETTLE:
        print("사진을 받는 중 - 다음 확인 때 글을 씁니다")
        return
    urls = [m["attachment"]["url"] for m in batch if m.get("attachment")]
    notes = " ".join(m.get("message", "") for m in batch if not m.get("attachment")
                     and m.get("message", "").strip()).strip()
    st["since"] = batch[-1]["id"]           # mark done first: a bad photo must not loop forever
    STATE.write_text(json.dumps(st), encoding="utf-8")
    if not urls:
        print("사진 없는 메모만 받음 - 건너뜀")
        return
    print(f"받은 사진/동영상 {len(urls)}개, 메모 {len(notes)}자")
    try:
        title, url = cloud_review.make_review(cloud_review.download(urls), "", notes)
    except BaseException as e:  # noqa: BLE001
        alert("후기 글 만들기 실패", f"다시 공유해 주세요. ({str(e)[:120]})")
        print("실패:", e)
        return
    print("완성:", title, url)


if __name__ == "__main__":
    main()
