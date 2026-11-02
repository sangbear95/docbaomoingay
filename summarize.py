"""Tóm tắt nhanh không dùng AI.

Tải trang bài báo, tìm phần thân bài, rồi chọn ra vài câu quan trọng nhất
(câu chứa nhiều từ hay lặp lại trong bài, ưu tiên phần đầu bài và câu có số liệu).
Kết quả được lưu vào cache/summaries.json để lần sau không phải tải lại bài cũ.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

CACHE_FILE = Path(__file__).parent / "cache" / "summaries.json"
RETRY_FAILED_AFTER = 3 * 3600   # bài lỗi thì 3 tiếng sau mới thử lại
MAX_FETCH_PER_RUN = 500
WORKERS = 6
SENTENCES = 3

SKIP_TAGS = {
    "script", "style", "noscript", "figure", "figcaption", "table", "aside", "nav",
    "footer", "header", "form", "button", "iframe", "svg", "select", "template",
}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "source", "track", "wbr",
}

# Những âm tiết rất phổ biến, không mang nhiều nghĩa khi chấm điểm câu.
STOPWORDS = set("""
và của là có được trong cho với các những này đã không người một để khi từ theo đến cũng
như thì về sẽ ra lại nhưng tại vào năm ngày nhiều hơn rất đó nào hay còn đang bị do nên
mà vì sau trước trên dưới nếu thể bằng làm đây đều chỉ phải cùng việc nhà ông bà anh chị
họ chúng tôi ta mình em sự cách lúc rằng thêm vẫn đi nói cho biết hiện nay qua giữa mỗi
tháng giờ lần số này kia ấy thế nhất hơn khoảng gần
""".split())

ABBREVIATIONS = {"tp", "ths", "ts", "pgs", "gs", "bs", "q", "p", "st", "mr", "mrs", "dr", "ubnd", "tw"}


class _ParagraphCollector(HTMLParser):
    """Gom chữ của từng thẻ <p>, ghi nhớ thẻ cha để đoán đâu là thân bài."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.next_id = 0
        self.skip = 0
        self.p_parent: int | None = None
        self.buf: list[str] = []
        self.paragraphs: list[tuple[int, str]] = []

    def _close_p(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if text:
            self.paragraphs.append((self.p_parent, text))
        self.p_parent = None
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        if tag == "p":
            if self.p_parent is not None:   # <p> chưa đóng thì tự đóng
                self._close_p()
            if not self.skip:
                self.p_parent = self.stack[-1][1] if self.stack else -1
                self.buf = []
        if tag in SKIP_TAGS:
            self.skip += 1
        self.stack.append((tag, self.next_id))
        self.next_id += 1

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for t, _ in reversed(self.stack[i:]):
                    if t in SKIP_TAGS:
                        self.skip -= 1
                    if t == "p" and self.p_parent is not None:
                        self._close_p()
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.p_parent is not None and not self.skip:
            self.buf.append(data)


def extract_body(page_html: str) -> list[str]:
    """Trả về các đoạn văn của thân bài: nhóm <p> chung thẻ cha có nhiều chữ nhất."""
    parser = _ParagraphCollector()
    try:
        parser.feed(page_html)
        parser.close()
    except Exception:
        pass
    groups: dict[int, list[str]] = {}
    for parent, text in parser.paragraphs:
        if len(text) >= 40:
            groups.setdefault(parent, []).append(text)
    if not groups:
        return []
    best = max(groups.values(), key=lambda ps: sum(len(p) for p in ps))
    return best if sum(len(p) for p in best) >= 400 else []


def split_sentences(paragraph: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", paragraph)
    sentences: list[str] = []
    for part in parts:
        if sentences:
            prev = sentences[-1]
            last_word = re.sub(r"\W", "", prev.rsplit(" ", 1)[-1]).lower()
            # Không cắt sau chữ viết tắt ("TP. HCM") hoặc khi câu sau viết thường.
            if last_word in ABBREVIATIONS or len(last_word) == 1 or not part[:1].isupper() and not part[:1].isdigit() and part[:1] not in "\"“'(":
                sentences[-1] = prev + " " + part
                continue
        sentences.append(part)
    return [s.strip() for s in sentences if s.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, min(len(a), len(b)))


def pick_sentences(paragraphs: list[str], description: str = "", count: int = SENTENCES) -> list[str]:
    sentences = []
    for pi, para in enumerate(paragraphs):
        for s in split_sentences(para):
            n = len(_words(s))
            if 8 <= n <= 70:
                sentences.append((pi, s))
    if not sentences:
        return []

    freq = Counter(w for _, s in sentences for w in _words(s) if w not in STOPWORDS and len(w) > 1)
    desc_words = set(_words(description))
    scored = []
    for idx, (pi, s) in enumerate(sentences):
        words = _words(s)
        content = {w for w in words if w in freq}
        score = sum(freq[w] for w in content) / (len(words) ** 0.6)
        if pi == 0:
            score *= 1.25          # tin tức thường nêu ý chính ở đầu bài
        elif pi <= 2:
            score *= 1.1
        if re.search(r"\d", s):
            score *= 1.1           # câu có số liệu thường đáng giữ
        if desc_words and _overlap(set(words), desc_words) > 0.6:
            score *= 0.3           # trùng phần mô tả đã hiện sẵn trên trang
        scored.append((score, idx, s))

    chosen: list[tuple[int, str]] = []
    for score, idx, s in sorted(scored, reverse=True):
        words = set(_words(s))
        if any(_overlap(words, set(_words(c))) > 0.6 for _, c in chosen):
            continue
        chosen.append((idx, s))
        if len(chosen) == count:
            break
    return [s for _, s in sorted(chosen)]


def summarize_html(page_html: str, description: str = "") -> list[str]:
    return pick_sentences(extract_body(page_html), description)


# ---------------- cache + tải bài ----------------

def load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def add_summaries(articles: list[dict], fetch: Callable[[str], bytes]) -> None:
    """Gắn article["quick"] (danh sách câu) cho từng bài, chỉ tải những bài chưa có trong cache."""
    cache = load_cache()
    now = time.time()
    todo = []
    for a in articles:
        entry = cache.get(a["link"])
        if entry is None or (not entry["s"] and now - entry["t"] > RETRY_FAILED_AFTER):
            todo.append(a)
    todo = todo[:MAX_FETCH_PER_RUN]

    def work(article):
        try:
            page = fetch(article["link"]).decode("utf-8", errors="replace")
            return article["link"], summarize_html(page, article["summary"])
        except Exception:
            return article["link"], []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for link, sentences in pool.map(work, todo):
            cache[link] = {"s": sentences, "t": now}

    current = {a["link"] for a in articles}
    cache = {k: v for k, v in cache.items() if k in current}   # bỏ bài đã trôi khỏi trang
    save_cache(cache)

    for a in articles:
        a["quick"] = cache.get(a["link"], {}).get("s", [])
    ok = sum(1 for a in articles if a["quick"])
    print(f"  Tóm tắt nhanh: tải mới {len(todo)} bài, có tóm tắt {ok}/{len(articles)} bài")
    sample = next((a for a in articles if a["quick"]), None)
    if sample:
        print(f"  Ví dụ [{sample['source']}] {sample['title']}")
        for s in sample["quick"]:
            print(f"    • {s}")
