"""지금 많이 찾는 키워드 (Google 트렌드 한국 RSS - 로그인 필요 없음)."""
import re
import xml.etree.ElementTree as ET

import requests

RSS = "https://trends.google.com/trending/rss?geo=KR"
NS = {"ht": "https://trends.google.com/trending/rss"}


def traffic_num(s: str) -> int:
    """'2,000+' / '1만+' / '500+' -> int."""
    s = (s or "").replace(",", "").replace("+", "").strip()
    m = re.match(r"(\d+(?:\.\d+)?)\s*(만|천|K|M)?", s, re.I)
    if not m:
        return 0
    n = float(m.group(1))
    mult = {"만": 10000, "천": 1000, "k": 1000, "m": 1000000}.get((m.group(2) or "").lower(), 1)
    return int(n * mult)


def fetch_trends(limit: int = 20) -> list:
    """[{'keyword', 'traffic', 'traffic_n', 'news': [{'title','source','url'}]}]"""
    r = requests.get(RSS, timeout=15, headers={"User-Agent": "Mozilla/5.0 blog-helper"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for item in root.iter("item"):
        kw = (item.findtext("title") or "").strip()
        if not kw:
            continue
        traffic = (item.findtext("ht:approx_traffic", default="", namespaces=NS) or "").strip()
        news = [{
            "title": (n.findtext("ht:news_item_title", default="", namespaces=NS) or "").strip(),
            "source": (n.findtext("ht:news_item_source", default="", namespaces=NS) or "").strip(),
            "url": (n.findtext("ht:news_item_url", default="", namespaces=NS) or "").strip(),
        } for n in item.findall("ht:news_item", NS)]
        out.append({"keyword": kw, "traffic": traffic, "traffic_n": traffic_num(traffic), "news": news})
        if len(out) >= limit:
            break
    return out


if __name__ == "__main__":
    for t in fetch_trends():
        print(t["keyword"], t["traffic"], t["traffic_n"], len(t["news"]), t["news"][:1])
