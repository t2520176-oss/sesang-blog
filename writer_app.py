"""블로그 글쓰기 도우미 - 네이버에 로그인하지 않는 프로그램.

AI가 글 + 사진을 만들어 미리보기 페이지로 열어 줍니다.
사용자는 [복사] 버튼으로 복사해서 평소 브라우저의 네이버 에디터에 붙여넣고 직접 발행합니다.
"""
import datetime as dt
import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import compose
import trends
import writer

HERE = Path(__file__).parent
CONFIG = HERE / "config.json"
STATE = HERE / "writer_auto_state.json"


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("블로그 글쓰기 도우미 (네이버 로그인 없음)")
        self.geometry("1050x760")
        cfg = load_json(CONFIG, {})
        self.trend_news = {}
        self.busy = False
        self.auto_stop = None
        ttk.Style(self).configure("Big.TButton", font=("맑은 고딕", 12, "bold"), padding=8)

        left = ttk.Frame(self, padding=10)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self, padding=10)
        right.pack(side="left", fill="both", expand=True)

        # ---- 설정 ----
        box = ttk.LabelFrame(left, text="설정", padding=8)
        box.pack(fill="x")
        self.api_key = self._row(box, 0, "AI 키 (Gemini 무료)", cfg.get("api_key", ""), show="*")
        self.pixabay = self._row(box, 1, "Pixabay 키 (선택)", cfg.get("pixabay_key", ""), show="*")
        ttk.Label(box, text="내 사진 폴더 (선택)").grid(row=2, column=0, sticky="w")
        f = ttk.Frame(box)
        f.grid(row=2, column=1, sticky="w")
        self.img_folder = tk.StringVar(value=cfg.get("img_folder", ""))
        ttk.Entry(f, textvariable=self.img_folder, width=26).pack(side="left")
        ttk.Button(f, text="찾기", width=5, command=lambda: self.img_folder.set(
            filedialog.askdirectory() or self.img_folder.get())).pack(side="left", padx=2)
        ttk.Label(box, text="사진은 내 폴더 → Pixabay → 위키미디어(출처 자동 표기) 순서로 찾습니다",
                  foreground="#666").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.style_sample = cfg.get("style_sample", "")
        self.style_lbl = ttk.Label(box)
        self.style_lbl.grid(row=4, column=0, sticky="w", pady=(4, 0))
        self._style_label()
        bf = ttk.Frame(box)
        bf.grid(row=4, column=1, sticky="e", pady=(4, 0))
        ttk.Button(bf, text="내 말투 설정", command=self.edit_style).pack(side="left", padx=4)
        ttk.Button(bf, text="설정 저장", command=self.save_cfg).pack(side="left")

        # ---- 쓸거리 ----
        box = ttk.LabelFrame(left, text="① 쓸거리", padding=8)
        box.pack(fill="x", pady=8)
        self.mode = tk.StringVar(value=cfg.get("mode", "home"))
        mf = ttk.Frame(box)
        mf.pack(fill="x")
        for key, m in writer.MODES.items():
            ttk.Radiobutton(mf, text=f"{m['label']}\n{m['desc']}", value=key, variable=self.mode,
                            command=self._mode_changed).pack(side="left", padx=4)
        ttk.Label(box, text="무엇에 대해 쓸까요?").pack(anchor="w", pady=(8, 0))
        self.topic = tk.StringVar()
        ttk.Entry(box, textvariable=self.topic, width=50).pack(fill="x")
        ttk.Button(box, text="실시간 인기 주제 가져오기", command=self.load_trends).pack(anchor="w", pady=4)
        self.trend_list = tk.Listbox(box, height=5)
        self.trend_list.pack(fill="x")
        self.trend_list.bind("<<ListboxSelect>>", self._pick_trend)
        r = ttk.Frame(box)
        r.pack(fill="x", pady=(6, 0))
        ttk.Label(r, text="분량(자)").pack(side="left")
        self.length = tk.IntVar(value=cfg.get("length", 1500))
        ttk.Spinbox(r, from_=500, to=4000, increment=250, textvariable=self.length, width=6).pack(side="left", padx=4)
        ttk.Label(r, text="  사진 수").pack(side="left")
        self.photos = tk.IntVar(value=cfg.get("photos", 3))
        ttk.Spinbox(r, from_=0, to=8, textvariable=self.photos, width=3).pack(side="left", padx=4)
        self.brand_frame = ttk.Frame(box)
        ttk.Label(self.brand_frame, text="브랜드 정보 (상호, 상품, 강점, 연락처 등)").pack(anchor="w")
        self.brand = tk.Text(self.brand_frame, height=3, width=50)
        self.brand.insert("1.0", cfg.get("brand_info", ""))
        self.brand.pack(fill="x")
        ttk.Label(box, text="추가 요청 (선택)").pack(anchor="w", pady=(6, 0))
        self.extra = tk.Text(box, height=2, width=50)
        self.extra.pack(fill="x")
        self._mode_changed()

        self.make_btn = ttk.Button(left, text="② 글 만들기 (사진 포함)", style="Big.TButton", command=self.make)
        self.make_btn.pack(fill="x")

        # ---- 자동 ----
        box = ttk.LabelFrame(left, text="자동 모드 - 화제 이슈 글을 하루 1번 미리 써 두기", padding=8)
        box.pack(fill="x", pady=(8, 0))
        r = ttk.Frame(box)
        r.pack(fill="x")
        ttk.Label(r, text="검색량").pack(side="left")
        self.threshold = tk.IntVar(value=cfg.get("threshold", 1000))
        ttk.Spinbox(r, from_=100, to=100000, increment=500, textvariable=self.threshold, width=7).pack(side="left")
        ttk.Label(r, text="+ 이상 이슈를").pack(side="left")
        self.interval = tk.IntVar(value=cfg.get("interval_min", 10))
        ttk.Spinbox(r, from_=5, to=180, increment=5, textvariable=self.interval, width=4).pack(side="left", padx=2)
        ttk.Label(r, text="분마다 확인").pack(side="left")
        self.auto_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="자동 모드 켜기 (글이 완성되면 알림 + 미리보기가 열립니다)",
                        variable=self.auto_on, command=self.toggle_auto).pack(anchor="w", pady=(4, 0))

        # ---- 오른쪽: 만든 글 목록 + 기록 ----
        ttk.Label(right, text="③ 만든 글 (더블클릭하면 미리보기 → [복사] 버튼으로 네이버에 붙여넣기)",
                  font=("맑은 고딕", 11, "bold")).pack(anchor="w")
        self.posts = tk.Listbox(right, font=("맑은 고딕", 11))
        self.posts.pack(fill="both", expand=True)
        self.posts.bind("<Double-Button-1>", lambda e: self.open_selected())
        b = ttk.Frame(right)
        b.pack(fill="x", pady=6)
        ttk.Button(b, text="미리보기 열기", command=self.open_selected).pack(side="left")
        ttk.Button(b, text="글 폴더 열기 (사진 파일)", command=lambda: self.open_selected(folder=True)).pack(side="left", padx=6)
        ttk.Button(b, text="새로고침", command=self.refresh_posts).pack(side="left")
        ttk.Label(right, text="진행 기록").pack(anchor="w", pady=(6, 0))
        self.log_box = scrolledtext.ScrolledText(right, height=9, state="disabled")
        self.log_box.pack(fill="x")
        self.refresh_posts()

    # ---------- helpers ----------
    def _row(self, box, r, label, value, show=None):
        ttk.Label(box, text=label).grid(row=r, column=0, sticky="w")
        v = tk.StringVar(value=value)
        ttk.Entry(box, textvariable=v, width=32, show=show).grid(row=r, column=1, sticky="w")
        return v

    def log(self, msg):
        def _do():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"{dt.datetime.now():%H:%M} {msg}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _do)

    def cfg(self):
        old = load_json(CONFIG, {})
        old.update({
            "api_key": self.api_key.get().strip(), "pixabay_key": self.pixabay.get().strip(),
            "img_folder": self.img_folder.get().strip(), "mode": self.mode.get(),
            "length": self.length.get(), "photos": self.photos.get(),
            "brand_info": self.brand.get("1.0", "end").strip(),
            "threshold": self.threshold.get(), "interval_min": self.interval.get(),
            "style_sample": self.style_sample,
        })
        return old

    def save_cfg(self):
        CONFIG.write_text(json.dumps(self.cfg(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.log("설정 저장됨")

    def _style_label(self):
        self.style_lbl.config(text="말투: 내 블로그 글 따라 쓰기" if self.style_sample.strip()
                              else "말투: 기본", foreground="#03a14a" if self.style_sample.strip() else "#666")

    def edit_style(self):
        win = tk.Toplevel(self)
        win.title("내 말투 설정")
        win.geometry("640x520")
        ttk.Label(win, text="내 블로그 글 1~2개를 그대로 붙여넣으세요. AI가 말투·문단 끊기·제목 짓는 방식을 따라 씁니다.\n"
                            "(내용은 가져오지 않고 문체만 따라합니다. 비워 두면 기본 말투)",
                  padding=8).pack(anchor="w")
        t = scrolledtext.ScrolledText(win, wrap="word", font=("맑은 고딕", 10))
        t.pack(fill="both", expand=True, padx=8)
        t.insert("1.0", self.style_sample)

        def ok():
            self.style_sample = t.get("1.0", "end").strip()
            self._style_label()
            self.save_cfg()
            win.destroy()
        ttk.Button(win, text="저장", command=ok).pack(pady=8)

    def _mode_changed(self):
        if self.mode.get() == "brand":
            self.brand_frame.pack(fill="x", pady=(6, 0))
        else:
            self.brand_frame.pack_forget()

    def _pick_trend(self, _e):
        sel = self.trend_list.curselection()
        if sel:
            self.topic.set(self.trend_list.get(sel[0]).split("  (")[0])

    def refresh_posts(self):
        self.posts.delete(0, "end")
        self.post_dirs = sorted([d for d in compose.ROOT.glob("*") if (d / "미리보기.html").exists()],
                                reverse=True) if compose.ROOT.exists() else []
        for d in self.post_dirs:
            stamp, _, name = d.name.partition("_")
            self.posts.insert("end", f"{stamp[4:6]}/{stamp[6:8]}  {name.split('_', 1)[-1].replace('_', ' ')}")

    def open_selected(self, folder=False, path=None):
        if path is None:
            sel = self.posts.curselection()
            if not sel:
                if not self.post_dirs:
                    return
                sel = (0,)
            path = self.post_dirs[sel[0]]
        os.startfile(path if folder else path / "미리보기.html")

    # ---------- actions ----------
    def load_trends(self):
        self.log("실시간 인기 키워드 가져오는 중...")

        def job():
            try:
                items = trends.fetch_trends()
            except Exception as e:  # noqa: BLE001
                self.log(f"[오류] 트렌드: {e}")
                return

            def fill():
                self.trend_list.delete(0, "end")
                self.trend_news = {t["keyword"]: t["news"] for t in items}
                for t in items:
                    self.trend_list.insert("end", f"{t['keyword']}  ({t['traffic']})")
                self.log(f"키워드 {len(items)}개")
            self.after(0, fill)
        threading.Thread(target=job, daemon=True).start()

    def produce(self, c, topic, mode, news, extra="", brand=""):
        """AI 글 + 사진 -> 미리보기 경로. (worker thread)"""
        self.log(f"'{topic}' 글 쓰는 중... (30초~1분)")
        post = writer.generate_post(c["api_key"], topic, mode, int(c["length"]), brand, extra,
                                    news=news, photos=int(c["photos"]),
                                    style=c.get("style_sample", ""))
        return compose.build(post, topic, c["img_folder"], c["pixabay_key"], log=self.log)

    def make(self):
        topic = self.topic.get().strip()
        if not topic:
            messagebox.showwarning("주제", "무엇에 대해 쓸지 입력하거나 인기 주제를 고르세요.")
            return
        if self.busy:
            return
        c = self.cfg()
        if not c["api_key"]:
            messagebox.showwarning("AI 키", "AI 키를 넣고 [설정 저장]을 누르세요.")
            return
        self.busy = True
        self.make_btn.state(["disabled"])
        news, mode = self.trend_news.get(topic), self.mode.get()
        extra, brand = self.extra.get("1.0", "end"), self.brand.get("1.0", "end")

        def job():
            try:
                page = self.produce(c, topic, mode, news, extra, brand)
                self.after(0, self._done, page, False)
            except Exception as e:  # noqa: BLE001
                self.log(f"[오류] {e}")
            finally:
                self.busy = False
                self.after(0, lambda: self.make_btn.state(["!disabled"]))
        threading.Thread(target=job, daemon=True).start()

    def _done(self, page, auto):
        self.refresh_posts()
        if auto:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(500, lambda: self.attributes("-topmost", False))
            self.bell()
        os.startfile(page)

    # ---------- auto mode (no Naver access at all) ----------
    def toggle_auto(self):
        if not self.auto_on.get():
            if self.auto_stop:
                self.auto_stop.set()
                self.log("자동 모드 중지")
            return
        c = self.cfg()
        if not c["api_key"]:
            messagebox.showwarning("자동 모드", "AI 키를 먼저 넣으세요.")
            self.auto_on.set(False)
            return
        self.save_cfg()
        stop = self.auto_stop = threading.Event()
        self.log(f"자동 모드 시작 - 검색량 {c['threshold']}+ 이슈를 하루 1번 글로 써 둡니다")
        threading.Thread(target=self._auto_loop, args=(c, stop), daemon=True).start()

    def _auto_loop(self, c, stop):
        while not stop.is_set():
            try:
                self._auto_tick(c)
            except Exception as e:  # noqa: BLE001
                self.log(f"[자동 오류] {e}")
            stop.wait(max(5, int(c["interval_min"])) * 60)

    def _auto_tick(self, c):
        st = load_json(STATE, {"last_date": "", "seen": []})
        today = dt.date.today().isoformat()
        if st["last_date"] == today:
            return
        hot = [t for t in trends.fetch_trends(30)
               if t["traffic_n"] >= int(c["threshold"]) and t["keyword"] not in st["seen"]]
        if not hot:
            self.log(f"검색량 {c['threshold']}+ 새 이슈 없음")
            return
        t = max(hot, key=lambda x: x["traffic_n"])
        self.log(f"이슈 발견: {t['keyword']} ({t['traffic']})")
        page = self.produce(c, t["keyword"], "search", t["news"])
        st["seen"] = (st["seen"] + [t["keyword"]])[-300:]
        st["last_date"] = today
        STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        self.log("자동 글 완성 (오늘 자동 작업 끝) - 미리보기를 확인하세요")
        self.after(0, self._done, page, True)


if __name__ == "__main__":
    App().mainloop()
