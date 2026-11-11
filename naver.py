"""Naver blog SmartEditor ONE automation (Playwright + installed Edge).

Login is never automated: the user signs in by hand once in the opened window,
and the session is kept in ./browser_profile.
All Playwright calls run on one worker thread (sync API is thread-bound).
"""
import datetime as dt
import json
import queue
import random
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PROFILE = Path(__file__).with_name("browser_profile")
LOGIN_URL = "https://nid.naver.com/nidlogin.login"
USAGE = Path(__file__).with_name("usage.json")

# ---- account-safety limits (네이버 계정 보호) ----------------------------
LIMITS = {
    "draft": 3,          # 하루 최대 임시저장 수
    "gap_min": 30,       # 글 작업 사이 최소 간격(분)
}


class SafetyStop(RuntimeError):
    """Raised instead of doing something that could look like abuse."""


def _usage():
    today = dt.date.today().isoformat()
    u = json.loads(USAGE.read_text(encoding="utf-8")) if USAGE.exists() else {}
    if u.get("date") != today:
        u = {"date": today, "draft": 0, "last_ts": u.get("last_ts", 0)}
    return u


def check_limits(action):
    if action == "fill":
        return
    u = _usage()
    if u[action] >= LIMITS[action]:
        raise SafetyStop(f"오늘 임시저장 한도({LIMITS[action]}개)에 "
                         "도달했습니다. 계정 보호를 위해 내일 다시 하세요.")
    wait = LIMITS["gap_min"] * 60 - (time.time() - u["last_ts"])
    if wait > 0:
        raise SafetyStop(f"직전 글 작업 후 {LIMITS['gap_min']}분이 지나야 합니다 "
                         f"(약 {int(wait // 60) + 1}분 남음). 계정 보호용 제한입니다.")


def record(action):
    u = _usage()
    u[action] += 1
    u["last_ts"] = time.time()
    USAGE.write_text(json.dumps(u), encoding="utf-8")


class NaverWorker(threading.Thread):
    def __init__(self, log):
        super().__init__(daemon=True)
        self.log = log
        self.q = queue.Queue()
        self.ctx = None
        self.start()

    # ---- thread plumbing -------------------------------------------------
    def submit(self, fn, *args, on_done=None):
        self.q.put((fn, args, on_done))

    def run(self):
        pw = sync_playwright().start()
        while True:
            fn, args, on_done = self.q.get()
            try:
                if self.ctx is None or not self._ctx_alive():
                    if self.ctx is not None:
                        try:
                            self.ctx.close()
                        except Exception:  # noqa: BLE001
                            pass
                    self.ctx =pw.chromium.launch_persistent_context(
                        str(PROFILE), channel="msedge", headless=False,
                        viewport=None, args=["--start-maximized"], locale="ko-KR")
                res, err = fn(*args), None
            except Exception as e:  # noqa: BLE001
                res, err = None, e
                self.log(f"[오류] {e}")
            if on_done:
                on_done(res, err)

    def _ctx_alive(self):
        """False once the user has closed the browser window."""
        try:
            return len(self.ctx.pages) > 0
        except Exception:  # noqa: BLE001
            return False

    def _page(self):
        pages = self.ctx.pages
        return pages[0] if pages else self.ctx.new_page()

    # ---- actions ----------------------------------------------------------
    def open_login(self):
        p = self._page()
        p.goto(LOGIN_URL)
        p.bring_to_front()
        self.log("열린 창에서 네이버에 직접 로그인하세요 (로그인 상태 유지 체크 권장).")

    def logged_in(self):
        return any(c["name"] == "NID_AUT" for c in self.ctx.cookies("https://naver.com"))

    def check_login(self):
        p = self._page()
        p.goto("https://section.blog.naver.com/BlogHome.naver")
        p.wait_for_load_state("domcontentloaded")
        ok = any(c["name"] == "NID_AUT" for c in self.ctx.cookies("https://naver.com"))
        self.log("로그인 확인됨" if ok else "로그인이 안 되어 있습니다.")
        return ok

    def write_post(self, blog_id, title, blocks, action="fill", images=None):
        """action: 'fill' (에디터에 채우기만) | 'draft' (임시저장). 발행은 항상 사용자가 직접."""
        if action not in ("fill", "draft"):
            raise SafetyStop("자동 발행은 꺼져 있습니다. 에디터에서 직접 [발행]을 누르세요.")
        check_limits(action)
        if not self.logged_in():
            # never auto-retry logins: repeated logins trigger Naver's 보호조치
            raise SafetyStop("네이버 로그인이 풀려 있습니다. 직접 [네이버 로그인 창 열기]로 로그인하세요. "
                             "(자동으로 다시 로그인하지 않습니다)")
        p = self._page()
        p.bring_to_front()
        p.goto(f"https://blog.naver.com/{blog_id}/postwrite")
        ed = self._editor_frame(p)
        self._dismiss_popups(ed)

        # title
        ed.locator(".se-documentTitle .se-text-paragraph").first.click()
        self._type(p, title)
        self.log("제목 입력 완료")

        # body: typed block by block; images go in before headings
        ed.locator(".se-component.se-text .se-text-paragraph").first.click()
        time.sleep(0.4)
        imgs = [str(i) for i in (images or []) if Path(i).is_file()]
        if imgs:
            self._upload_image(p, ed, imgs.pop(0))      # 대표 사진: 맨 위
        for i, b in enumerate(blocks):
            if b["type"] == "heading" and i > 0 and imgs:
                self._upload_image(p, ed, imgs.pop(0))
            if b["type"] == "heading":
                p.keyboard.press("Control+b")
                self._type(p, b["text"])
                p.keyboard.press("Control+b")
            elif b["type"] == "quote":
                self._type(p, f"“{b['text']}”")
            else:
                self._type(p, b["text"])
            p.keyboard.press("Enter")
            if b["type"] != "heading":
                p.keyboard.press("Enter")
        for img in imgs:                                  # 남은 사진: 맨 아래
            self._upload_image(p, ed, img)
        self.log(f"본문 입력 완료 ({self._count(ed)})")

        if action == "fill":
            self.log("에디터에 글을 채워 두었습니다. 내용 확인 후 직접 [발행]을 누르세요 "
                     "(태그는 [태그 복사] 후 발행 창에 붙여넣기).")
            return "fill"
        if action == "draft":
            ed.locator("button[class*='save_btn']").first.click()
            time.sleep(2.5)
            record("draft")
            self.log(f"임시저장 완료: {title}")
            return "draft"

        # 발행은 프로그램이 하지 않음 (계정 보호): 사용자가 직접 [발행]
        raise SafetyStop("자동 발행은 꺼져 있습니다. 에디터에서 직접 [발행]을 누르세요.")

    # ---- helpers ----------------------------------------------------------
    def _editor_frame(self, p):
        """Editor lives either in the page or in iframe#mainFrame."""
        sel = ".se-documentTitle"
        for _ in range(40):
            if "nid.naver.com" in p.url:
                raise RuntimeError("네이버 로그인이 풀렸습니다. [네이버 로그인 창 열기]로 다시 로그인하세요 "
                                   "('로그인 상태 유지' 체크).")
            for fr in [p.main_frame] + p.frames:
                try:
                    if fr.locator(sel).count():
                        return fr
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.5)
        raise RuntimeError("글쓰기 에디터를 찾지 못했습니다. 로그인/블로그 아이디를 확인하세요.")

    def _dismiss_popups(self, ed):
        time.sleep(1.5)
        # "작성 중인 글이 있습니다" -> 취소 (start fresh)
        for sel in (".se-popup-button-cancel", ".se-help-panel-close-button"):
            try:
                loc = ed.locator(sel)
                if loc.count() and loc.first.is_visible():
                    loc.first.click()
                    time.sleep(0.5)
            except PWTimeout:
                pass

    def _count(self, ed):
        return ed.evaluate("""() => {
            const c = [...document.querySelectorAll('.se-component')];
            return `text ${c.filter(e => e.classList.contains('se-text')).length}, `
                 + `image ${c.filter(e => e.classList.contains('se-image')).length}`;
        }""")

    def _upload_image(self, p, ed, path):
        """Toolbar [사진] -> file chooser; then put the caret on a text line below the image."""
        n = ed.locator(".se-component.se-image").count()
        with p.expect_file_chooser(timeout=10000) as fc:
            ed.locator("button.se-image-toolbar-button, button[data-name='image']").first.click()
        fc.value.set_files(path)
        for _ in range(40):                        # wait for the upload to finish
            if ed.locator(".se-component.se-image").count() > n:
                break
            time.sleep(0.5)
        else:
            self.log(f"[경고] 사진 업로드 확인 안 됨: {Path(path).name}")
            return
        time.sleep(1.0)
        # caret: the text paragraph right after the new image, else make one
        img = ed.locator(".se-component.se-image").nth(n)
        nxt = img.locator("xpath=following-sibling::div[contains(@class,'se-text')][1]")
        if nxt.count():
            nxt.locator(".se-text-paragraph").last.click()
            p.keyboard.press("End")
        else:
            img.click()
            p.keyboard.press("Enter")
        time.sleep(0.3)
        self.log(f"사진 첨부: {Path(path).name}")

    def _type(self, p, text):
        """Paste-sized chunks with human-ish pauses (no burst input)."""
        for i in range(0, len(text), 40):
            p.keyboard.insert_text(text[i:i + 40])
            time.sleep(random.uniform(0.15, 0.45))
        time.sleep(random.uniform(0.5, 1.2))
