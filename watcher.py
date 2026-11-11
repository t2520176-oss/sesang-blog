"""Auto mode: a hot issue (Google Trends KR, search volume >= threshold) -> AI post -> 임시저장.

At most ONE auto draft per day. Never publishes.
"""
import datetime as dt
import json
import random
import threading
from pathlib import Path

import trends
import writer
from naver import SafetyStop, check_limits

STATE = Path(__file__).with_name("auto_state.json")
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"last_date": "", "seen": []}


def save_state(st):
    st["seen"] = st["seen"][-300:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def pick_images(folder: str, keyword: str, n: int) -> list:
    """Photos from the user's own folder: filenames containing the keyword first, then random."""
    if not folder or n <= 0 or not Path(folder).is_dir():
        return []
    files = [f for f in Path(folder).iterdir() if f.suffix.lower() in IMG_EXT]
    match = [f for f in files if keyword.replace(" ", "") in f.stem.replace(" ", "")]
    rest = [f for f in files if f not in match]
    random.shuffle(rest)
    return [str(f) for f in (match + rest)[:n]]


class AutoWatcher(threading.Thread):
    """get_cfg() -> dict with api_key, blog_id, mode, length, threshold, interval_min,
    img_folder, img_count. naver = NaverWorker."""

    def __init__(self, get_cfg, naver, log, on_post=None, on_stop=None):
        super().__init__(daemon=True)
        self.get_cfg, self.naver, self.log = get_cfg, naver, log
        self.on_post, self.on_stop = on_post, on_stop   # GUI callbacks
        self.stop_ev = threading.Event()

    def stop(self):
        self.stop_ev.set()

    def _on_worker(self, fn, *args, timeout=600):
        done, res = threading.Event(), {}
        self.naver.submit(fn, *args, on_done=lambda r, e: (res.update(r=r, e=e), done.set()))
        done.wait(timeout)
        return res.get("r"), res.get("e")

    def _halt(self, msg):
        self.log(msg)
        self.stop()
        if self.on_stop:
            self.on_stop()

    def run(self):
        self.log("자동 모드 시작 (하루 1번, 임시저장까지만)")
        while not self.stop_ev.is_set():
            cfg = self.get_cfg()
            try:
                self.tick(cfg)
            except Exception as e:  # noqa: BLE001
                self.log(f"[자동 오류] {e}")
            self.stop_ev.wait(max(1, int(cfg.get("interval_min", 10))) * 60)
        self.log("자동 모드 중지")

    def tick(self, cfg):
        st = load_state()
        today = dt.date.today().isoformat()
        if st["last_date"] == today:
            return  # 오늘은 이미 1개 저장함
        try:
            check_limits("draft")
        except SafetyStop:
            return  # 한도/간격에 걸리면 AI 호출도 하지 않음
        ok, _ = self._on_worker(self.naver.logged_in, timeout=120)
        if not ok:   # 로그인부터 확인: AI 사용량 낭비 없음, 다시 로그인 시도도 안 함
            self._halt("[자동] 네이버 로그인이 안 되어 있어 자동 모드를 멈춥니다. "
                       "[네이버 로그인 창 열기]로 로그인('로그인 상태 유지' 체크) 후 다시 켜세요.")
            return
        thr = int(cfg.get("threshold", 1000))
        hot = [t for t in trends.fetch_trends(30)
               if t["traffic_n"] >= thr and t["keyword"] not in st["seen"]]
        now = dt.datetime.now().strftime("%H:%M")
        if not hot:
            self.log(f"{now} 검색량 {thr}+ 새 이슈 없음")
            return
        t = max(hot, key=lambda x: x["traffic_n"])
        self.log(f"{now} 이슈 발견: {t['keyword']} ({t['traffic']}) -> 글 작성 중...")
        st["seen"].append(t["keyword"])
        save_state(st)

        post = writer.generate_post(cfg["api_key"], t["keyword"], cfg.get("mode", "search"),
                                    int(cfg.get("length", 1500)), news=t["news"])
        imgs = pick_images(cfg.get("img_folder", ""), t["keyword"], int(cfg.get("img_count", 2)))

        r, e = self._on_worker(self.naver.write_post, cfg["blog_id"], post["title"],
                               post["blocks"], "draft", imgs)
        if r == "draft":
            st["last_date"] = today
            save_state(st)
            self.log(f"자동 임시저장 완료: {post['title']} (오늘 자동 작업 끝)")
            return
        # 실패해도 쓴 글은 버리지 않고 화면에 넣어 둠
        if self.on_post:
            self.on_post(post)
        if isinstance(e, SafetyStop) and "로그인" in str(e):
            self._halt("[자동] 로그인이 풀려 자동 모드를 멈춥니다. 쓴 글은 오른쪽 칸에 넣어 두었습니다.")
        else:
            self.log(f"[자동] 임시저장 안 됨: {e} - 쓴 글은 오른쪽 칸에 넣어 두었습니다.")
