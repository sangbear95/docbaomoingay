#!/usr/bin/env python3
"""Đọc RSS của các báo và tạo trang tin tổng hợp tĩnh: site/index.html.

Chỉ dùng thư viện chuẩn của Python, không cần cài thêm gì.
Chạy: python3 build.py
"""

from __future__ import annotations

import html
import re
import urllib.parse
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import summarize

# Danh sách nguồn: (tên hiển thị, mã ngắn, link RSS, màu nhận diện)
SOURCES = [
    ("VnExpress", "vnexpress", "https://vnexpress.net/rss/tin-moi-nhat.rss", "#9f224e"),
    ("Tuổi Trẻ", "tuoitre", "https://tuoitre.vn/rss/tin-moi-nhat.rss", "#ed1c24"),
    ("Thanh Niên", "thanhnien", "https://thanhnien.vn/rss/home.rss", "#0b5ea8"),
]

MAX_PER_SOURCE = 50
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; docbaomoingay/1.0; +https://github.com/sangbear95/docbaomoingay)"
VN_TZ = timezone(timedelta(hours=7))
OUT_DIR = Path(__file__).parent / "site"


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


def parse_feed(data: bytes, source_name: str, source_id: str, domain: str) -> list[dict]:
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
        })
    if rejected:
        print(f"  {source_name}: bỏ {rejected} bài có link không thuộc {domain}", file=sys.stderr)
    return articles[:MAX_PER_SOURCE]


def collect() -> tuple[list[dict], list[str]]:
    def load(source):
        name, sid, url, _ = source
        domain = urllib.parse.urlsplit(url).hostname.removeprefix("www.")
        return parse_feed(fetch(url), name, sid, domain)

    articles, errors = [], []
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = {pool.submit(load, s): s for s in SOURCES}
        for future, source in futures.items():
            try:
                items = future.result()
                print(f"  {source[0]}: {len(items)} bài")
                articles.extend(items)
            except Exception as exc:  # một nguồn lỗi thì vẫn chạy các nguồn khác
                print(f"  {source[0]}: LỖI - {exc}", file=sys.stderr)
                errors.append(source[0])

    seen, unique = set(), []
    for a in articles:
        key = a["link"].split("?")[0]
        if key not in seen:
            seen.add(key)
            unique.append(a)
    oldest = datetime(1970, 1, 1, tzinfo=VN_TZ)
    unique.sort(key=lambda a: a["published"] or oldest, reverse=True)
    return unique, errors


def render(articles: list[dict], errors: list[str]) -> str:
    e = html.escape
    now = datetime.now(VN_TZ)
    colors = {sid: color for _, sid, _, color in SOURCES}

    tabs = ['<button class="tab active" data-filter="all">Tất cả</button>']
    for name, sid, _, _ in SOURCES:
        count = sum(1 for a in articles if a["source_id"] == sid)
        tabs.append(f'<button class="tab" data-filter="{sid}">{e(name)} <span>{count}</span></button>')

    cards = []
    for a in articles:
        pub = a["published"]
        iso = pub.isoformat() if pub else ""
        label = pub.strftime("%H:%M %d/%m") if pub else ""
        img = (
            f'<img src="{e(a["image"])}" alt="" loading="lazy" referrerpolicy="no-referrer" '
            f'onerror="this.remove()">' if a["image"] else ""
        )
        prompt = ASK_PROMPT.format(title=a["title"], link=a["link"])
        ask_url = "https://claude.ai/new?q=" + urllib.parse.quote(prompt)
        quick = a.get("quick") or []
        quick_btn = '<button class="tool-btn quick-btn" type="button">Tóm tắt nhanh</button>' if quick else ""
        quick_box = (
            '<ul class="quick" hidden>' + "".join(f"<li>{e(q)}</li>" for q in quick) + "</ul>"
            if quick else ""
        )
        cards.append(f"""
    <article class="card" data-source="{a['source_id']}">
      <a href="{e(a['link'])}" target="_blank" rel="noopener">
        {img}
        <div class="body">
          <div class="meta"><span class="badge" style="--c:{colors[a['source_id']]}">{e(a['source'])}</span>
            <time datetime="{iso}" title="{label}">{label}</time></div>
          <h2>{e(a['title'])}</h2>
          <p>{e(a['summary'])}</p>
        </div>
      </a>
      <div class="tools">{quick_btn}<a class="tool-btn ask" href="{e(ask_url)}" target="_blank" rel="noopener" data-prompt="{e(prompt)}">Hỏi Claude ↗</a></div>
      {quick_box}
    </article>""")

    warning = (
        f'<p class="warn">Không tải được tin từ: {e(", ".join(errors))}. Sẽ thử lại ở lần cập nhật sau.</p>'
        if errors else ""
    )

    return TEMPLATE.format(
        updated_iso=now.isoformat(),
        updated=now.strftime("%H:%M ngày %d/%m/%Y"),
        tabs="\n      ".join(tabs),
        warning=warning,
        cards="".join(cards) or '<p class="empty">Chưa có tin nào.</p>',
    )


ASK_PROMPT = (
    "Tóm tắt bài báo sau bằng tiếng Việt: một câu nêu ý chính, rồi 3-5 gạch đầu dòng "
    "về các chi tiết quan trọng (ai, việc gì, khi nào, ở đâu, số liệu).\n\n{title}\n{link}"
)

TEMPLATE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Đọc báo mỗi ngày</title>
<meta name="description" content="Tin mới nhất từ VnExpress, Tuổi Trẻ, Thanh Niên">
<meta name="robots" content="noindex, nofollow">
<style>
  :root {{
    --bg: #f4f4f1; --card: #ffffff; --text: #1d1d1b; --muted: #6b6b66;
    --line: #e3e3de; --accent: #1d1d1b;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #141413; --card: #1f1f1d; --text: #ececea; --muted: #9a9a94;
      --line: #2e2e2b; --accent: #ececea;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  }}
  header {{
    position: sticky; top: 0; z-index: 10; background: var(--bg);
    border-bottom: 1px solid var(--line); padding: 12px 16px 0;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  .top {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
  h1 {{ font-size: 22px; margin: 0; letter-spacing: -0.01em; }}
  .updated {{ color: var(--muted); font-size: 13px; }}
  .search {{
    width: 100%; margin: 10px 0 0; padding: 9px 12px; font: inherit; font-size: 15px;
    color: var(--text); background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  }}
  .tabs {{ display: flex; gap: 4px; overflow-x: auto; margin-top: 8px; scrollbar-width: none; }}
  .tab {{
    flex: none; font: inherit; font-size: 14px; color: var(--muted); background: none; border: 0;
    border-bottom: 2px solid transparent; padding: 8px 10px; cursor: pointer;
  }}
  .tab span {{ font-size: 12px; opacity: .7; }}
  .tab.active {{ color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }}
  main {{ padding: 12px 16px 40px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; margin-bottom: 10px; overflow: hidden; }}
  .card > a {{ display: flex; gap: 14px; padding: 12px; color: inherit; text-decoration: none; }}
  .card > a:hover h2 {{ text-decoration: underline; }}
  .card > a:visited h2 {{ color: var(--muted); }}
  .card img {{ flex: none; width: 128px; height: 86px; object-fit: cover; border-radius: 6px; background: var(--line); }}
  .body {{ flex: 1; min-width: 0; }}
  .meta {{ display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); }}
  .badge {{ color: var(--c); font-weight: 700; text-transform: uppercase; letter-spacing: .03em; font-size: 11px; }}
  @media (prefers-color-scheme: dark) {{ .badge {{ filter: brightness(1.6); }} }}
  h2 {{ font-size: 16px; line-height: 1.35; margin: 4px 0; }}
  p {{ margin: 0; font-size: 14px; color: var(--muted);
       display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
  .warn {{ background: #fff4d6; color: #6b4d00; margin: 0 0 10px; padding: 10px 12px; border-radius: 8px; font-size: 14px; }}
  @media (prefers-color-scheme: dark) {{ .warn {{ background: #3a2f12; color: #f3d98b; }} }}
  .empty {{ text-align: center; color: var(--muted); padding: 40px 0; }}
  .hidden {{ display: none; }}
  .tools {{ display: flex; gap: 8px; padding: 0 12px 10px; }}
  .tool-btn {{
    font: inherit; font-size: 13px; line-height: 1.4; color: var(--muted); background: none; cursor: pointer;
    border: 1px solid var(--line); border-radius: 999px; padding: 3px 10px; text-decoration: none;
  }}
  .tool-btn:hover {{ color: var(--text); border-color: var(--muted); }}
  .quick-btn[aria-expanded="true"] {{ color: var(--text); border-color: var(--muted); }}
  .quick {{
    margin: 0 12px 12px; padding: 10px 12px 10px 30px; border-radius: 8px; background: var(--bg);
    font-size: 15px; line-height: 1.55;
  }}
  .quick li + li {{ margin-top: 6px; }}
  .toast {{
    position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); z-index: 20;
    width: max-content; max-width: calc(100% - 32px); padding: 10px 14px; border-radius: 8px;
    background: var(--text); color: var(--bg); font-size: 14px; box-shadow: 0 4px 16px rgb(0 0 0 / .2);
  }}
  @media (max-width: 520px) {{
    .card > a {{ gap: 10px; }}
    .card img {{ order: 2; }}
    .card img {{ width: 96px; height: 72px; }}
    h2 {{ font-size: 15px; }}
    .card p {{ display: none; }}
  }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="top">
      <h1>Đọc báo mỗi ngày</h1>
      <span class="updated">Cập nhật <time id="updated" datetime="{updated_iso}">{updated}</time></span>
    </div>
    <input class="search" id="q" type="search" placeholder="Tìm tin…" autocomplete="off">
    <nav class="tabs">
      {tabs}
    </nav>
  </div>
</header>
<main class="wrap">
  {warning}
  {cards}
  <p class="empty hidden" id="none">Không có tin phù hợp.</p>
</main>
<div class="toast" id="toast" hidden></div>
<script>
  const cards = [...document.querySelectorAll('.card')];
  const tabs = [...document.querySelectorAll('.tab')];
  const q = document.getElementById('q');
  let filter = 'all';
  try {{ filter = localStorage.getItem('filter') || 'all'; }} catch (e) {{}}
  // Xóa khóa API và tóm tắt AI do bản cũ (đã gỡ) để lại trong trình duyệt.
  try {{ localStorage.removeItem('anthropic_api_key'); localStorage.removeItem('ai_summaries'); }} catch (e) {{}}

  const norm = s => s.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/đ/g, 'd');
  cards.forEach(c => c._text = norm(c.querySelector('a').textContent));

  function apply() {{
    const term = norm(q.value.trim());
    let shown = 0;
    tabs.forEach(t => t.classList.toggle('active', t.dataset.filter === filter));
    cards.forEach(c => {{
      const ok = (filter === 'all' || c.dataset.source === filter) && (!term || c._text.includes(term));
      c.classList.toggle('hidden', !ok);
      if (ok) shown++;
    }});
    document.getElementById('none').classList.toggle('hidden', shown > 0 || !cards.length);
  }}
  tabs.forEach(t => t.addEventListener('click', () => {{
    filter = t.dataset.filter;
    try {{ localStorage.setItem('filter', filter); }} catch (e) {{}}
    apply();
  }}));
  q.addEventListener('input', apply);
  if (!tabs.some(t => t.dataset.filter === filter)) filter = 'all';
  apply();

  let toastTimer;
  function toast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, 5000);
  }}
  document.querySelector('main').addEventListener('click', ev => {{
    const quick = ev.target.closest('.quick-btn');
    if (quick) {{
      const box = quick.closest('.card').querySelector('.quick');
      box.hidden = !box.hidden;
      quick.setAttribute('aria-expanded', String(!box.hidden));
      quick.textContent = box.hidden ? 'Tóm tắt nhanh' : 'Ẩn tóm tắt';
      return;
    }}
    const ask = ev.target.closest('.ask');
    if (ask && navigator.clipboard) {{
      navigator.clipboard.writeText(ask.dataset.prompt)
        .then(() => toast('Đã chép câu hỏi. Nếu ô chat trên Claude còn trống, chỉ cần dán vào rồi gửi.'))
        .catch(() => {{}});
    }}
  }});

  function ago(iso) {{
    if (!iso) return '';
    const m = Math.round((Date.now() - new Date(iso)) / 60000);
    if (m < 1) return 'vừa xong';
    if (m < 60) return m + ' phút trước';
    if (m < 1440) return Math.round(m / 60) + ' giờ trước';
    return Math.round(m / 1440) + ' ngày trước';
  }}
  function tick() {{
    document.querySelectorAll('time[datetime]').forEach(t => {{
      const s = ago(t.getAttribute('datetime'));
      if (s) t.textContent = s;
    }});
  }}
  tick();
  setInterval(tick, 60000);
</script>
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
    print(f"Đã ghi {len(articles)} bài vào {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
