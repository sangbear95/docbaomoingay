#!/usr/bin/env python3
"""Đọc RSS của các báo và tạo trang tin tổng hợp tĩnh: site/index.html.

Chỉ dùng thư viện chuẩn của Python, không cần cài thêm gì.
Chạy: python3 build.py
"""

from __future__ import annotations

import html
import re
import shutil
import urllib.parse
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import summarize

# Chuyên mục chung cho cả ba báo: (mã, tên hiển thị)
CATEGORIES = [
    ("thoi-su", "Thời sự"),
    ("the-gioi", "Thế giới"),
    ("kinh-te", "Kinh tế"),
    ("the-thao", "Thể thao"),
    ("giai-tri", "Giải trí"),
    ("phap-luat", "Pháp luật"),
    ("giao-duc", "Giáo dục"),
    ("suc-khoe", "Sức khỏe"),
    ("cong-nghe", "Công nghệ"),
]

# Mỗi báo: tin mới nhất + RSS từng chuyên mục. Một chuyên mục có thể ghi nhiều
# link dự phòng (báo hay đổi tên mục); script dùng link đầu tiên đọc được.
SOURCES = [
    {
        "name": "VnExpress", "id": "vnexpress", "color": "#9f224e", "color_dark": "#ec7aa6",
        "base": "https://vnexpress.net/rss/",
        "latest": ["tin-moi-nhat.rss"],
        "categories": {
            "thoi-su": ["thoi-su.rss"],
            "the-gioi": ["the-gioi.rss"],
            "kinh-te": ["kinh-doanh.rss"],
            "the-thao": ["the-thao.rss"],
            "giai-tri": ["giai-tri.rss"],
            "phap-luat": ["phap-luat.rss"],
            "giao-duc": ["giao-duc.rss"],
            "suc-khoe": ["suc-khoe.rss"],
            "cong-nghe": ["khoa-hoc-cong-nghe.rss", "so-hoa.rss", "khoa-hoc.rss"],
        },
    },
    {
        "name": "Tuổi Trẻ", "id": "tuoitre", "color": "#d71920", "color_dark": "#ff7a74",
        "base": "https://tuoitre.vn/rss/",
        "latest": ["tin-moi-nhat.rss"],
        "categories": {
            "thoi-su": ["thoi-su.rss"],
            "the-gioi": ["the-gioi.rss"],
            "kinh-te": ["kinh-doanh.rss"],
            "the-thao": ["the-thao.rss"],
            "giai-tri": ["giai-tri.rss", "van-hoa.rss"],
            "phap-luat": ["phap-luat.rss"],
            "giao-duc": ["giao-duc.rss"],
            "suc-khoe": ["suc-khoe.rss"],
            "cong-nghe": ["cong-nghe.rss", "nhip-song-so.rss", "khoa-hoc.rss"],
        },
    },
    {
        "name": "Thanh Niên", "id": "thanhnien", "color": "#0b5ea8", "color_dark": "#6cb0ff",
        "base": "https://thanhnien.vn/rss/",
        "latest": ["home.rss"],
        "categories": {
            "thoi-su": ["thoi-su.rss"],
            "the-gioi": ["the-gioi.rss"],
            "kinh-te": ["kinh-te.rss"],
            "the-thao": ["the-thao.rss"],
            "giai-tri": ["giai-tri.rss", "van-hoa.rss"],
            "phap-luat": ["thoi-su/phap-luat.rss", "phap-luat.rss"],
            "giao-duc": ["giao-duc.rss"],
            "suc-khoe": ["suc-khoe.rss"],
            "cong-nghe": ["cong-nghe.rss", "cong-nghe-game.rss"],
        },
    },
]

MAX_LATEST = 50        # số bài lấy từ RSS "tin mới nhất" của mỗi báo
MAX_PER_CATEGORY = 20  # số bài lấy từ mỗi chuyên mục của mỗi báo
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; docbaomoingay/1.0; +https://github.com/sangbear95/docbaomoingay)"
VN_TZ = timezone(timedelta(hours=7))
OUT_DIR = Path(__file__).parent / "site"
STATIC_DIR = Path(__file__).parent / "static"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    # Một số báo ghi múi giờ dạng "GMT+7" -> đổi thành "+0700"
    value = re.sub(r"GMT\s*([+-])(\d{1,2})$", lambda m: f"{m.group(1)}{int(m.group(2)):02d}00", value)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ)


def child_text(item: ET.Element, name: str) -> str:
    for child in item:
        if child.tag.rsplit("}", 1)[-1] == name and child.text:
            return child.text.strip()
    return ""


def find_image(item: ET.Element, description: str) -> str:
    for child in item:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in ("enclosure", "content", "thumbnail"):
            url = child.get("url", "")
            if url and (tag != "enclosure" or child.get("type", "image").startswith("image")):
                return url
    m = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", description or "", re.I)
    return html.unescape(m.group(1)) if m else ""


def link_allowed(link: str, domain: str) -> bool:
    """Chỉ nhận link http(s) thuộc đúng tên miền của báo (kể cả tên miền con)."""
    try:
        url = urllib.parse.urlsplit(link)
    except ValueError:
        return False
    host = (url.hostname or "").lower()
    return url.scheme in ("http", "https") and (host == domain or host.endswith("." + domain))


def parse_feed(data: bytes, source_name: str, source_id: str, domain: str, limit: int) -> list[dict]:
    root = ET.fromstring(data)
    articles = []
    rejected = 0
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        title = strip_tags(child_text(item, "title"))
        link = child_text(item, "link")
        if not title:
            continue
        if not link_allowed(link, domain):
            rejected += 1
            continue
        description = child_text(item, "description")
        summary = strip_tags(description)
        if len(summary) > 220:
            summary = summary[:220].rsplit(" ", 1)[0] + "…"
        articles.append({
            "source": source_name,
            "source_id": source_id,
            "title": title,
            "link": link,
            "summary": summary,
            "image": find_image(item, description),
            "published": parse_date(child_text(item, "pubDate")),
            "cats": set(),
        })
    if rejected:
        print(f"  {source_name}: bỏ {rejected} bài có link không thuộc {domain}", file=sys.stderr)
    return articles[:limit]


def load_feed(source: dict, paths: list[str], limit: int) -> list[dict]:
    """Thử lần lượt các link RSS dự phòng, trả về bài của link đầu tiên đọc được."""
    domain = urllib.parse.urlsplit(source["base"]).hostname.removeprefix("www.")
    last_error = None
    for path in paths:
        try:
            items = parse_feed(fetch(source["base"] + path), source["name"], source["id"], domain, limit)
            if items:
                return items
            last_error = "RSS không có bài nào"
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"{', '.join(paths)}: {last_error}")


def collect() -> tuple[list[dict], list[str]]:
    jobs = []  # (báo, mã chuyên mục hoặc None nếu là tin mới nhất, các link, giới hạn)
    for src in SOURCES:
        jobs.append((src, None, src["latest"], MAX_LATEST))
        for cat, paths in src["categories"].items():
            jobs.append((src, cat, paths, MAX_PER_CATEGORY))

    cat_names = dict(CATEGORIES)
    by_link: dict[str, dict] = {}
    ok_feeds = {src["id"]: 0 for src in SOURCES}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [(pool.submit(load_feed, src, paths, limit), src, cat) for src, cat, paths, limit in jobs]
        for future, src, cat in futures:
            label = f"{src['name']} / {cat_names.get(cat, 'Tin mới nhất')}"
            try:
                items = future.result()
            except Exception as exc:  # một chuyên mục lỗi thì vẫn chạy phần còn lại
                print(f"  {label}: LỖI - {exc}", file=sys.stderr)
                continue
            ok_feeds[src["id"]] += 1
            for a in items:
                key = a["link"].split("?")[0].split("#")[0]
                kept = by_link.setdefault(key, a)   # bài trùng giữa các chuyên mục chỉ giữ một
                if cat:
                    kept["cats"].add(cat)

    articles = list(by_link.values())
    for src in SOURCES:
        n = sum(1 for a in articles if a["source_id"] == src["id"])
        print(f"  {src['name']}: đọc được {ok_feeds[src['id']]}/{len(src['categories']) + 1} RSS, {n} bài")
    errors = [src["name"] for src in SOURCES if ok_feeds[src["id"]] == 0]

    oldest = datetime(1970, 1, 1, tzinfo=VN_TZ)
    articles.sort(key=lambda a: a["published"] or oldest, reverse=True)
    return articles, errors


ICONS = {
    "search": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    "moon": '<svg class="icon moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
    "sun": '<svg class="icon sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    "list": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h9M3.5 6h.01M3.5 12h.01M3.5 18h.01"/></svg>',
    "chev": '<svg class="icon chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
    "spark": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.8 4.6L18.5 9.5l-4.7 1.9L12 16l-1.8-4.6L5.5 9.5l4.7-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>',
    "up": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
    "alert": '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
}


def render(articles: list[dict], errors: list[str]) -> str:
    e = html.escape
    now = datetime.now(VN_TZ)
    cat_names = dict(CATEGORIES)
    sources = {src["id"]: src for src in SOURCES}

    tabs = [f'<button class="tab" role="tab" data-cat="all">Tất cả<span class="count">{len(articles)}</span></button>']
    for cid, name in CATEGORIES:
        count = sum(1 for a in articles if cid in a["cats"])
        if count:
            tabs.append(f'<button class="tab" role="tab" data-cat="{cid}">{e(name)}<span class="count">{count}</span></button>')

    chips = ['<button class="chip" data-src="all">Mọi báo</button>']
    for src in SOURCES:
        chips.append(
            f'<button class="chip" data-src="{src["id"]}" style="--c:{src["color"]}">'
            f'<span class="dot" aria-hidden="true"></span>{e(src["name"])}</button>'
        )

    cards = []
    for a in articles:
        src = sources[a["source_id"]]
        pub = a["published"]
        iso = pub.isoformat() if pub else ""
        label = pub.strftime("%H:%M %d/%m") if pub else ""
        cats = [cat_names[c] for c, _ in CATEGORIES if c in a["cats"]]
        cat_html = f'<span class="cat">{e(" · ".join(cats[:2]))}</span>' if cats else ""
        time_html = f'<time datetime="{iso}" title="{label}">{label}</time>' if iso else ""
        thumb = (
            f'<div class="thumb"><img src="{e(a["image"])}" alt="" loading="lazy" decoding="async" '
            f'referrerpolicy="no-referrer" onerror="this.closest(\'.card\').classList.remove(\'has-img\');'
            f'this.parentNode.remove();window.dispatchEvent(new Event(\'imgfail\'))"></div>' if a["image"] else ""
        )
        desc = f'<p class="desc">{e(a["summary"])}</p>' if a["summary"] else ""
        # Không ngắt dòng giữa tỉ số / khoảng số như "2-0", "2026-2027".
        title_html = re.sub(r"\d+(?:[-–/:]\d+)+", lambda m: f'<span class="nb">{m.group(0)}</span>', e(a["title"]))
        prompt = ASK_PROMPT.format(title=a["title"], link=a["link"])
        ask_url = "https://claude.ai/new?q=" + urllib.parse.quote(prompt)
        quick = a.get("quick") or []
        quick_btn = (
            f'<button class="act quick-btn" type="button" aria-expanded="false">{ICONS["list"]}'
            f'<span class="label">Tóm tắt nhanh</span>{ICONS["chev"]}</button>' if quick else ""
        )
        quick_box = (
            '<div class="quick" hidden><p class="quick-label">Ý chính</p><ul>'
            + "".join(f"<li>{e(s)}</li>" for s in quick) + "</ul></div>" if quick else ""
        )
        cards.append(f"""
<article class="card{' has-img' if a['image'] else ''}" data-source="{src['id']}" data-cats="{' '.join(sorted(a['cats']))}" style="--c:{src['color']};--cd:{src['color_dark']}">
  <a class="card-link" href="{e(a['link'])}" target="_blank" rel="noopener">
    {thumb}
    <div class="card-body">
      <div class="meta"><span class="src">{e(src['name'])}</span>{cat_html}{time_html}</div>
      <h2 class="title">{title_html}</h2>
      {desc}
    </div>
  </a>
  <div class="actions">{quick_btn}<a class="act ask" href="{e(ask_url)}" target="_blank" rel="noopener" data-prompt="{e(prompt)}">{ICONS['spark']}<span>Hỏi Claude</span></a></div>
  {quick_box}
</article>""")

    notice = (
        f'<p class="notice">{ICONS["alert"]}<span>Chưa tải được tin từ {e(", ".join(errors))}. '
        f'Trang sẽ thử lại ở lần cập nhật sau.</span></p>' if errors else ""
    )
    source_names = ", ".join(src["name"] for src in SOURCES[:-1]) + " và " + SOURCES[-1]["name"]

    page = TEMPLATE
    for key, value in {
        "UPDATED_ISO": now.isoformat(),
        "UPDATED": now.strftime("%H:%M %d/%m"),
        "TODAY": now.strftime("%d/%m/%Y"),
        "SOURCES": e(source_names),
        "TABS": "\n      ".join(tabs),
        "CHIPS": "\n      ".join(chips),
        "NOTICE": notice,
        "CARDS": "".join(cards),
        "ICON_SEARCH": ICONS["search"],
        "ICON_THEME": ICONS["moon"] + ICONS["sun"],
        "ICON_UP": ICONS["up"],
        "VERSION": now.strftime("%Y%m%d%H%M"),
    }.items():
        page = page.replace("%%" + key + "%%", value)
    return page


ASK_PROMPT = (
    "Tóm tắt bài báo sau bằng tiếng Việt: một câu nêu ý chính, rồi 3-5 gạch đầu dòng "
    "về các chi tiết quan trọng (ai, việc gì, khi nào, ở đâu, số liệu).\n\n{title}\n{link}"
)

TEMPLATE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Đọc báo mỗi ngày</title>
<meta name="description" content="Tin mới từ %%SOURCES%%, chia theo chuyên mục.">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#f5f3ee" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#121210" media="(prefers-color-scheme: dark)">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%23b42318'/%3E%3Ctext x='32' y='45' font-family='Georgia,serif' font-size='38' font-weight='700' text-anchor='middle' fill='%23fff'%3EĐ%3C/text%3E%3C/svg%3E">
<script>try{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t}catch(e){}</script>
<link rel="preload" href="fonts/BeVietnamPro-400-vietnamese.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="fonts.css?v=%%VERSION%%">
<link rel="stylesheet" href="style.css?v=%%VERSION%%">
</head>
<body>
<header class="masthead">
  <div class="wrap">
    <div class="mast-top">
      <p class="dateline" id="dateline">%%TODAY%%</p>
      <div class="mast-actions">
        <span class="updated">Cập nhật <time datetime="%%UPDATED_ISO%%">%%UPDATED%%</time></span>
        <button class="icon-btn theme-toggle" id="theme-toggle" type="button" aria-label="Đổi chế độ sáng/tối">%%ICON_THEME%%</button>
      </div>
    </div>
    <h1 class="brand">Đọc báo <span>mỗi ngày</span></h1>
    <p class="tagline">Tin mới từ %%SOURCES%%, tự cập nhật mỗi 30 phút.</p>
    <label class="search">%%ICON_SEARCH%%<input id="q" type="search" placeholder="Tìm tin theo từ khóa…" autocomplete="off" aria-label="Tìm tin"></label>
  </div>
</header>

<div class="filters">
  <div class="wrap">
    <nav class="tabs" role="tablist" aria-label="Chuyên mục">
      %%TABS%%
    </nav>
    <div class="sources" role="group" aria-label="Báo">
      %%CHIPS%%
    </div>
  </div>
</div>

<main class="wrap">
  %%NOTICE%%
  <div class="grid" id="grid">%%CARDS%%
  </div>
  <p class="empty" id="empty" hidden>Không có tin phù hợp. Thử chọn chuyên mục khác hoặc đổi từ khóa.</p>
  <div class="more" id="more" hidden><button class="more-btn" id="more-btn" type="button">Xem thêm tin <span></span></button></div>
</main>

<footer class="site-footer">
  <div class="wrap">
    <p>Tin tổng hợp từ RSS của %%SOURCES%%. Bấm vào tin để đọc bài gốc trên trang báo.</p>
    <p>Tóm tắt nhanh là các câu trích từ bài, không phải do AI viết.</p>
  </div>
</footer>

<button class="icon-btn to-top" id="to-top" type="button" aria-label="Lên đầu trang" hidden>%%ICON_UP%%</button>
<div class="toast" id="toast" role="status" hidden></div>
<script src="app.js?v=%%VERSION%%" defer></script>
</body>
</html>
"""


def main() -> int:
    print("Đang tải tin…")
    articles, errors = collect()
    if not articles:
        print("Không lấy được bài nào từ mọi nguồn, giữ nguyên trang cũ.", file=sys.stderr)
        return 1
    summarize.add_summaries(articles, fetch)
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "index.html"
    out.write_text(render(articles, errors), encoding="utf-8")
    shutil.copytree(STATIC_DIR, OUT_DIR, dirs_exist_ok=True)
    print(f"Đã ghi {len(articles)} bài vào {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
