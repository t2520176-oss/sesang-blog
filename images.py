"""Photos for a post, in this order:
1) 내 사진 폴더 (file name contains the keyword)
2) Pixabay (free key, no credit needed)
3) Wikimedia Commons (no key; credit line added under the photo)
All photos are downloaded and resized locally (no hotlinking).
"""
import io
import random
import re
from pathlib import Path

import requests
from PIL import Image

UA = {"User-Agent": "blog-writer-helper/1.0 (personal blog tool)"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_W = 960


def _save(img_bytes_or_path, out: Path) -> bool:
    try:
        im = Image.open(img_bytes_or_path if isinstance(img_bytes_or_path, (str, Path))
                        else io.BytesIO(img_bytes_or_path))
        im = im.convert("RGB")
        if im.width < 300 or im.height < 200:
            return False
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
        im.save(out, "JPEG", quality=86)
        return True
    except Exception:  # noqa: BLE001
        return False


def from_folder(folder, keyword, used):
    if not folder or not Path(folder).is_dir():
        return []
    files = [f for f in Path(folder).iterdir() if f.suffix.lower() in IMG_EXT and str(f) not in used]
    k = keyword.replace(" ", "")
    match = [f for f in files if k and k in f.stem.replace(" ", "")]
    rest = [f for f in files if f not in match]
    random.shuffle(rest)
    return [{"src": str(f), "credit": ""} for f in match + rest]


def from_pixabay(key, query, used):
    if not key:
        return []
    r = requests.get("https://pixabay.com/api/", timeout=20, headers=UA, params={
        "key": key, "q": query[:100], "image_type": "photo", "safesearch": "true", "per_page": 10})
    if r.status_code != 200:
        return []
    return [{"url": h["largeImageURL"], "credit": ""} for h in r.json().get("hits", [])
            if h["largeImageURL"] not in used]


def _strip(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


def from_wikimedia(query, used):
    r = requests.get("https://commons.wikimedia.org/w/api.php", timeout=20, headers=UA, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": 12, "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime", "iiurlwidth": MAX_W})
    if r.status_code != 200:
        return []
    out = []
    pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        m = ii.get("extmetadata", {})
        lic = _strip(m.get("LicenseShortName", {}).get("value"))
        if not re.search(r"CC0|Public domain|CC BY", lic, re.I) or re.search(r"\bND\b|NC", lic):
            continue                               # 상업/변경 금지 라이선스 제외
        url = ii.get("thumburl") or ii.get("url")
        if url in used:
            continue
        artist = _strip(m.get("Artist", {}).get("value"))[:40] or "Unknown"
        credit = "" if re.search(r"CC0|Public domain", lic, re.I) else \
            f"사진: {artist} / {lic} / Wikimedia Commons"
        out.append({"url": url, "credit": credit})
    return out


def find_photo(query_en, keyword_ko, out: Path, folder="", pixabay_key="", used=None):
    """Save one photo to `out`. Returns {'path', 'credit'} or None.
    No hit -> retry with a shorter query ('traveler suitcase passport' -> 'traveler suitcase' -> ...)."""
    words = query_en.split()
    for n in range(len(words), 0, -1):
        got = _find_one(" ".join(words[:n]), keyword_ko, out, folder if n == len(words) else "",
                        pixabay_key, used if used is not None else set())
        if got:
            return got
    return None


def _find_one(query_en, keyword_ko, out, folder, pixabay_key, used):
    cands = from_folder(folder, keyword_ko, used)
    for fn in (lambda: from_pixabay(pixabay_key, query_en, used),
               lambda: from_wikimedia(query_en, used)):
        if cands:
            break
        try:
            cands = fn()
        except Exception:  # noqa: BLE001
            cands = []
    for c in cands[:6]:
        if "src" in c:
            ok = _save(c["src"], out)
            key = c["src"]
        else:
            try:
                r = requests.get(c["url"], timeout=30, headers=UA)
                ok = r.status_code == 200 and _save(r.content, out)
            except Exception:  # noqa: BLE001
                ok = False
            key = c["url"]
        if ok:
            used.add(key)
            return {"path": str(out), "credit": c["credit"]}
    return None
