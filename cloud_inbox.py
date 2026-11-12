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
    made = 0
    for _ in range(4):                      # oldest group first, up to 4 posts per run
        if not msgs:
            break
        batch = [msgs[0]]
        for m in msgs[1:]:
            if m["time"] - batch[-1]["time"] > GAP:
                break
            batch.append(m)
        if len(batch) == len(msgs) and time.time() - batch[-1]["time"] < SETTLE:
            print("사진을 받는 중 - 다음 확인 때 글을 씁니다")
            break
        msgs = msgs[len(batch):]
        if not process(batch, st):
            break                            # AI busy: keep this batch for the next run
        made += 1
    print(f"이번에 만든 후기: {made}개")


def process(batch, st):
    """One group of photos -> one post. Returns False only when it should be retried later."""
    seen = st.setdefault("seen", [])         # photo sizes already used: a re-sent photo is skipped
    atts = [m["attachment"] for m in batch if m.get("attachment")]
    new = [a for a in atts if a.get("size") not in seen]
    urls = [a["url"] for a in new]
    notes = " ".join(m.get("message", "") for m in batch if not m.get("attachment")
                     and m.get("message", "").strip()).strip()

    def done():
        st.update(since=batch[-1]["id"], tries=0, seen=(seen + [a.get("size") for a in new])[-80:])
        STATE.write_text(json.dumps(st), encoding="utf-8")

    if not urls:
        print("새 사진 없음 (메모만 왔거나 이미 쓴 사진을 다시 보냄) - 건너뜀")
        done()
        return True
    print(f"받은 사진/동영상 {len(urls)}개, 메모 {len(notes)}자")
    try:
        title, url = cloud_review.make_review(cloud_review.download(urls), "", notes)
    except BaseException as e:  # noqa: BLE001
        print("실패:", e)
        busy = "바쁩니다" in str(e) or "Timeout" in str(e)
        st["tries"] = st.get("tries", 0) + 1
        if busy and st["tries"] < 8:          # free AI busy: try again on the next run
            STATE.write_text(json.dumps(st), encoding="utf-8")
            print(f"AI 서버가 바빠서 다음에 다시 시도 ({st['tries']}/8)")
            return False
        done()                                # give up on this batch so it can't loop forever
        alert("후기 글 만들기 실패", f"사진을 다시 보내 주세요. ({str(e)[:100]})")
        return True
    done()
    print("완성:", title, url)
    return True


if __name__ == "__main__":
    main()
