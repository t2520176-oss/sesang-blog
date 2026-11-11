"""네이버 블로그 자동 글쓰기 - GUI.

순서: ① 쓸거리(주제) → ② 글 만들기(AI) → ③ 에디터에 채우기 / 발행
"""
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import trends
import writer
from naver import NaverWorker
from watcher import AutoWatcher

CONFIG = Path(__file__).with_name("config.json")


def load_cfg():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    return {}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("네이버 블로그 자동 글쓰기")
        self.geometry("1150x780")
        cfg = load_cfg()
        self.naver = None
        self.auto = None
        self.images = []
        self.trend_news = {}   # keyword -> news headlines (AI가 사실만 쓰도록)

        style = ttk.Style(self)
        style.configure("Big.TButton", font=("맑은 고딕", 11, "bold"), padding=6)

        # ---------- left column ----------
        left = ttk.Frame(self, padding=10)
        left.pack(side="left", fill="y")

        box = ttk.LabelFrame(left, text="설정", padding=8)
        box.pack(fill="x")
        ttk.Label(box, text="AI 키 (Gemini 무료)").grid(row=0, column=0, sticky="w")
        self.api_key = tk.StringVar(value=cfg.get("api_key", ""))
        ttk.Entry(box, textvariable=self.api_key, show="*", width=34).grid(row=0, column=1)
        ttk.Label(box, text="블로그 아이디").grid(row=1, column=0, sticky="w")
        self.blog_id = tk.StringVar(value=cfg.get("blog_id", ""))
        ttk.Entry(box, textvariable=self.blog_id, width=34).grid(row=1, column=1)
        bb = ttk.Frame(box)
        bb.grid(row=2, column=0, columnspan=2, pady=(6, 0), sticky="we")
        ttk.Button(bb, text="네이버 로그인 창 열기", command=self.open_login).pack(side="left")
        ttk.Button(bb, text="로그인 확인", command=self.check_login).pack(side="left", padx=4)
        ttk.Button(bb, text="설정 저장", command=self.save_cfg).pack(side="right")

        box = ttk.LabelFrame(left, text="자동 모드 - 화제 이슈를 하루 1번 임시저장 (발행 안 함)", padding=8)
        box.pack(fill="x", pady=(8, 0))
        r1 = ttk.Frame(box)
        r1.pack(fill="x")
        ttk.Label(r1, text="검색량").pack(side="left")
        self.threshold = tk.IntVar(value=cfg.get("threshold", 1000))
        ttk.Spinbox(r1, from_=100, to=100000, increment=500, textvariable=self.threshold, width=7).pack(side="left")
        ttk.Label(r1, text="+ 이상, ").pack(side="left")
        self.interval = tk.IntVar(value=cfg.get("interval_min", 10))
        ttk.Spinbox(r1, from_=5, to=180, increment=5, textvariable=self.interval, width=4).pack(side="left")
        ttk.Label(r1, text="분마다 확인").pack(side="left")
        r2 = ttk.Frame(box)
        r2.pack(fill="x", pady=(4, 0))
        ttk.Label(r2, text="사진 폴더").pack(side="left")
        self.img_folder = tk.StringVar(value=cfg.get("img_folder", ""))
        ttk.Entry(r2, textvariable=self.img_folder, width=22).pack(side="left", padx=2)
        ttk.Button(r2, text="찾기", width=4,
                   command=lambda: self.img_folder.set(filedialog.askdirectory() or self.img_folder.get())).pack(side="left")
        ttk.Label(r2, text=" 사진 수").pack(side="left")
        self.img_count = tk.IntVar(value=cfg.get("img_count", 2))
        ttk.Spinbox(r2, from_=0, to=10, textvariable=self.img_count, width=3).pack(side="left")
        self.auto_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="자동 모드 켜기 (프로그램을 켜 둔 동안 동작)", variable=self.auto_on,
                        command=self.toggle_auto).pack(anchor="w", pady=(4, 0))

        box = ttk.LabelFrame(left, text="① 쓸거리", padding=8)
        box.pack(fill="x", pady=8)
        self.mode = tk.StringVar(value=cfg.get("mode", "home"))
        mf = ttk.Frame(box)
        mf.pack(fill="x")
        for key, m in writer.MODES.items():
            ttk.Radiobutton(mf, text=f"{m['label']}\n{m['desc']}", value=key,
                            variable=self.mode, command=self._mode_changed).pack(side="left", padx=4)
        ttk.Label(box, text="무엇에 대해 쓸까요?").pack(anchor="w", pady=(8, 0))
        self.topic = tk.StringVar()
        ttk.Entry(box, textvariable=self.topic, width=48).pack(fill="x")
        ttk.Button(box, text="실시간 인기 주제 가져오기", command=self.load_trends).pack(anchor="w", pady=4)
        self.trend_list = tk.Listbox(box, height=5)
        self.trend_list.pack(fill="x")
        self.trend_list.bind("<<ListboxSelect>>", self._pick_trend)

        lf = ttk.Frame(box)
        lf.pack(fill="x", pady=(6, 0))
        ttk.Label(lf, text="분량(자)").pack(side="left")
        self.length = tk.IntVar(value=cfg.get("length", 1500))
        ttk.Spinbox(lf, from_=500, to=4000, increment=250, textvariable=self.length, width=7).pack(side="left", padx=4)

        self.brand_frame = ttk.Frame(box)
        ttk.Label(self.brand_frame, text="브랜드 정보 (상호, 상품, 강점, 연락처 등)").pack(anchor="w")
        self.brand = tk.Text(self.brand_frame, height=4, width=48)
        self.brand.insert("1.0", cfg.get("brand_info", ""))
        self.brand.pack(fill="x")
        ttk.Label(box, text="추가 요청 (선택)").pack(anchor="w", pady=(6, 0))
        self.extra = tk.Text(box, height=2, width=48)
        self.extra.pack(fill="x")
        self._mode_changed()

        ttk.Button(left, text="② 글 만들기 (AI)", style="Big.TButton",
                   command=self.generate).pack(fill="x")

        self.log_box = scrolledtext.ScrolledText(left, height=6, width=52, state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(8, 0))

        # ---------- right column ----------
        right = ttk.Frame(self, padding=10)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="제목").pack(anchor="w")
        self.title_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.title_var, font=("맑은 고딕", 13)).pack(fill="x")
        ttk.Label(right, text="본문  ([소제목] 줄은 굵은 소제목, > 줄은 인용으로 들어갑니다. 문단은 빈 줄로 구분)").pack(anchor="w", pady=(8, 0))
        self.body = scrolledtext.ScrolledText(right, wrap="word", font=("맑은 고딕", 11))
        self.body.pack(fill="both", expand=True)
        ttk.Label(right, text="태그 (쉼표로 구분)").pack(anchor="w", pady=(8, 0))
        self.tags = tk.StringVar()
        ttk.Entry(right, textvariable=self.tags).pack(fill="x")

        pf = ttk.Frame(right)
        pf.pack(fill="x", pady=(8, 0))
        ttk.Button(pf, text="사진 추가", command=self.add_images).pack(side="left")
        ttk.Button(pf, text="사진 비우기", command=self.clear_images).pack(side="left", padx=4)
        self.img_lbl = ttk.Label(pf, text="사진 없음 (첫 사진은 맨 위, 나머지는 소제목 앞에 들어갑니다)")
        self.img_lbl.pack(side="left", padx=6)

        bf = ttk.Frame(right)
        bf.pack(fill="x", pady=8)
        ttk.Button(bf, text="태그 복사", command=self.copy_tags).pack(side="left")
        ttk.Label(bf, text="발행은 에디터에서 직접 누르세요 (계정 보호)").pack(side="left", padx=10)
        ttk.Button(bf, text="임시저장", command=lambda: self.send("draft")).pack(side="right", padx=6)
        ttk.Button(bf, text="③ 에디터에 채우기", style="Big.TButton",
                   command=lambda: self.send("fill")).pack(side="right")

    # ---------- helpers ----------
    def log(self, msg):
        def _do():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _do)

    def worker(self):
        if self.naver is None:
            self.naver = NaverWorker(self.log)
        return self.naver

    def save_cfg(self):
        CONFIG.write_text(json.dumps({
            "api_key": self.api_key.get().strip(),
            "blog_id": self.blog_id.get().strip(),
            "mode": self.mode.get(),
            "length": self.length.get(),
            "brand_info": self.brand.get("1.0", "end").strip(),
            **self.auto_cfg(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log("설정을 저장했습니다 (config.json)")

    def auto_cfg(self):
        return {"threshold": self.threshold.get(), "interval_min": self.interval.get(),
                "img_folder": self.img_folder.get().strip(), "img_count": self.img_count.get()}

    def snapshot_cfg(self):
        """Read on the Tk thread; handed to the watcher thread."""
        return {"api_key": self.api_key.get().strip(), "blog_id": self.blog_id.get().strip(),
                "mode": self.mode.get() if self.mode.get() != "brand" else "search",
                "length": self.length.get(), **self.auto_cfg()}

    def toggle_auto(self):
        if self.auto_on.get():
            c = self.snapshot_cfg()
            if not c["api_key"] or not c["blog_id"]:
                messagebox.showwarning("자동 모드", "AI 키와 블로그 아이디를 먼저 넣으세요.")
                self.auto_on.set(False)
                return
            self.save_cfg()
            self._cfg_cache = c
            self.auto = AutoWatcher(lambda: self._cfg_cache, self.worker(), self.log,
                                    on_post=lambda p: self.after(0, self._show_post, p),
                                    on_stop=lambda: self.after(0, self.auto_on.set, False))
            self.auto.start()
        elif self.auto:
            self.auto.stop()
            self.auto = None

    def _show_post(self, post):
        self.title_var.set(post["title"])
        self.body.delete("1.0", "end")
        self.body.insert("1.0", writer.post_to_text(post))
        self.tags.set(", ".join(post["tags"]))

    def add_images(self):
        files = filedialog.askopenfilenames(
            title="사진 선택", filetypes=[("사진", "*.jpg *.jpeg *.png *.gif *.webp *.bmp")])
        self.images += list(files)
        self._img_label()

    def clear_images(self):
        self.images = []
        self._img_label()

    def _img_label(self):
        from pathlib import Path as _P
        names = ", ".join(_P(f).name for f in self.images)
        self.img_lbl.config(text=f"사진 {len(self.images)}장: {names[:80]}" if self.images else "사진 없음")

    def _mode_changed(self):
        if self.mode.get() == "brand":
            self.brand_frame.pack(fill="x", pady=(6, 0))
        else:
            self.brand_frame.pack_forget()

    def _pick_trend(self, _e):
        sel = self.trend_list.curselection()
        if sel:
            self.topic.set(self.trend_list.get(sel[0]).split("  (")[0])

    # ---------- actions ----------
    def open_login(self):
        self.worker().submit(self.worker().open_login)

    def check_login(self):
        self.worker().submit(self.worker().check_login)

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

    def generate(self):
        topic = self.topic.get().strip()
        if not topic:
            messagebox.showwarning("주제", "무엇에 대해 쓸지 입력하세요.")
            return
        news = self.trend_news.get(topic)
        mode, length = self.mode.get(), self.length.get()
        brand, extra = self.brand.get("1.0", "end"), self.extra.get("1.0", "end")
        key = self.api_key.get().strip()
        self.log(f"AI가 '{topic}' 글을 쓰는 중... (30초~2분)")

        def job():
            try:
                post = writer.generate_post(key, topic, mode, length, brand, extra, news=news)
            except Exception as e:  # noqa: BLE001
                self.log(f"[오류] 글 생성: {e}")
                return

            def fill():
                self.title_var.set(post["title"])
                self.body.delete("1.0", "end")
                self.body.insert("1.0", writer.post_to_text(post))
                self.tags.set(", ".join(post["tags"]))
                self.log("글 완성! 내용을 확인/수정한 뒤 ③을 누르세요.")
            self.after(0, fill)
        threading.Thread(target=job, daemon=True).start()

    def send(self, action):
        blog_id = self.blog_id.get().strip()
        title = self.title_var.get().strip()
        blocks = writer.text_to_blocks(self.body.get("1.0", "end"))
        if not blog_id or not title or not blocks:
            messagebox.showwarning("확인", "블로그 아이디, 제목, 본문이 필요합니다.")
            return
        w = self.worker()
        w.submit(w.write_post, blog_id, title, blocks, action, list(self.images))

    def copy_tags(self):
        tags = [t.strip().lstrip("#") for t in self.tags.get().split(",") if t.strip()]
        self.clipboard_clear()
        self.clipboard_append(" ".join(f"#{t}" for t in tags))
        self.log(f"태그 {len(tags)}개 복사됨 - 발행 창의 태그 칸에 붙여넣으세요")


if __name__ == "__main__":
    App().mainloop()
