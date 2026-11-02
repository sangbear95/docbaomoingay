// Đọc báo mỗi ngày — dựng danh sách tin từ dữ liệu, lọc, tóm tắt nhanh, chế độ sáng/tối.
// Trang chỉ dựng những tin đang hiển thị (mỗi lần PAGE tin) để nhẹ và nhanh.
(() => {
  const PAGE = 30;
  const ASK_PROMPT = "Tóm tắt bài báo sau bằng tiếng Việt: một câu nêu ý chính, rồi 3-5 gạch đầu dòng " +
    "về các chi tiết quan trọng (ai, việc gì, khi nào, ở đâu, số liệu).\n\n";

  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch {} },
  };
  // Dọn khóa API / tóm tắt AI mà bản cũ (đã gỡ) có thể để lại.
  try { localStorage.removeItem("anthropic_api_key"); localStorage.removeItem("ai_summaries"); } catch {}

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const DATA = JSON.parse($("#data").textContent);
  const SOURCES = DATA.sources.map(([id, name]) => ({ id, name }));
  const CATS = DATA.cats.map(([id, name]) => ({ id, name }));
  const ITEMS = DATA.items.map(([title, url, desc, img, src, cats, time, hasQuick], i) => ({
    i, title, url, desc, img, src, cats, time, hasQuick,
  }));
  const badImages = new Set();

  // Xin ảnh vừa khung hiển thị thay vì ảnh gốc 1200px (chỉ với báo mà lúc build đã thử thành công).
  const RESIZE = {
    vnexpress: (u, w) => u.replace(/([?&])w=\d+/, `$1w=${w}`),
    tuoitre: (u, w) => u.replace(/\/thumb_w\/\d+\//, `/thumb_w/${w}/`),
    thanhnien: (u, w) => u.replace(/\/zoom\/(\d+)_(\d+)\//, (m, a, b) => `/zoom/${w}_${Math.round((w * b) / a)}/`),
  };
  const RESIZE_PATTERN = {
    vnexpress: /[?&]w=\d+/, tuoitre: /\/thumb_w\/\d+\//, thanhnien: /\/zoom\/\d+_\d+\//,
  };
  const WIDTHS = [240, 480, 800, 1200];
  const SIZES_LEAD = "(min-width: 1040px) 640px, (min-width: 720px) 50vw, 100vw";
  const SIZES_CARD = "(min-width: 1040px) 360px, (min-width: 720px) 50vw, 112px";
  const resizable = new Set(DATA.resize || []);
  function imgAttrs(url, srcId, lead) {
    const fn = RESIZE[srcId];
    if (!resizable.has(srcId) || !RESIZE_PATTERN[srcId].test(url)) return `src="${esc(url)}"`;
    const srcset = WIDTHS.map((w) => `${esc(fn(url, w))} ${w}w`).join(", ");
    return `src="${esc(fn(url, 480))}" srcset="${srcset}" sizes="${lead ? SIZES_LEAD : SIZES_CARD}" data-orig="${esc(url)}"`;
  }

  const grid = $("#grid");
  const tabs = $$(".tab");
  const chips = $$(".chip");
  const q = $("#q");
  const moreWrap = $("#more");
  const moreBtn = $("#more-btn");
  const empty = $("#empty");

  // ---------- tiện ích ----------
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
  const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");
  const icon = (name, cls = "") => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  function ago(seconds) {
    const m = Math.round((Date.now() / 1000 - seconds) / 60);
    if (m < 1) return "vừa xong";
    if (m < 60) return `${m} phút trước`;
    if (m < 1440) return `${Math.round(m / 60)} giờ trước`;
    return `${Math.round(m / 1440)} ngày trước`;
  }

  // ---------- dựng một thẻ tin ----------
  function cardHTML(it, lead) {
    const src = SOURCES[it.src];
    const hasImg = it.img && !badImages.has(it.i);
    const cats = it.cats.slice(0, 2).map((c) => CATS[c].name).join(" · ");
    // Không ngắt dòng giữa tỉ số / khoảng số như "2-0", "2026-2027".
    const title = esc(it.title).replace(/\d+(?:[-–/:]\d+)+/g, '<span class="nb">$&</span>');
    const time = it.time
      ? `<time datetime="${new Date(it.time * 1000).toISOString()}" data-t="${it.time}">${ago(it.time)}</time>` : "";
    const img = hasImg
      ? `<div class="thumb"><img ${imgAttrs(it.img, src.id, lead)} alt="" ${lead ? 'fetchpriority="high"' : 'loading="lazy"'} decoding="async" referrerpolicy="no-referrer" data-i="${it.i}"></div>`
      : "";
    const quickBtn = it.hasQuick
      ? `<button class="act quick-btn" type="button" aria-expanded="false">${icon("list")}<span class="label">Tóm tắt</span>${icon("chev", "chev")}</button>`
      : "";
    return `<article class="card s-${src.id}${hasImg ? " has-img" : ""}${lead ? " lead" : ""}" data-i="${it.i}">
<a class="card-link" href="${esc(it.url)}" target="_blank" rel="noopener">${img}
<div class="card-body"><div class="meta"><span class="src">${esc(src.name)}</span>${cats ? `<span class="cat">${esc(cats)}</span>` : ""}${time}</div>
<h2 class="title">${title}</h2>${it.desc ? `<p class="desc">${esc(it.desc)}</p>` : ""}</div></a>
<div class="actions">${quickBtn}<a class="act ask" href="https://claude.ai/new" target="_blank" rel="noopener">${icon("spark")}<span>Hỏi Claude</span></a></div>
</article>`;
  }

  // ---------- lọc + hiển thị ----------
  let cat = store.get("cat") || "all";
  let src = store.get("src") || store.get("filter") || "all";
  if (!tabs.some((t) => t.dataset.cat === cat)) cat = "all";
  if (!chips.some((c) => c.dataset.src === src)) src = "all";
  let matched = [];
  let shown = 0;

  function filter() {
    const term = norm(q.value.trim());
    const catIdx = CATS.findIndex((c) => c.id === cat);
    const srcIdx = SOURCES.findIndex((s) => s.id === src);
    matched = ITEMS.filter((it) =>
      (catIdx < 0 || it.cats.includes(catIdx)) &&
      (srcIdx < 0 || it.src === srcIdx) &&
      (!term || (it._text ??= norm(it.title + " " + it.desc)).includes(term)));
    return term;
  }

  function updateMore() {
    moreWrap.hidden = shown >= matched.length;
    if (!moreWrap.hidden) moreBtn.querySelector("span").textContent = `(còn ${matched.length - shown} tin)`;
  }

  function render() {
    const term = filter();
    tabs.forEach((t) => { const on = t.dataset.cat === cat; t.classList.toggle("active", on); t.setAttribute("aria-selected", on); });
    chips.forEach((c) => { const on = c.dataset.src === src; c.classList.toggle("active", on); c.setAttribute("aria-pressed", on); });
    shown = Math.min(PAGE, matched.length);
    const first = matched[0];
    const leadOk = first && !term && first.img && !badImages.has(first.i);
    grid.innerHTML = matched.slice(0, shown).map((it, k) => cardHTML(it, k === 0 && leadOk)).join("");
    empty.hidden = matched.length > 0;
    updateMore();
  }

  function showMore() {
    const next = matched.slice(shown, shown + PAGE);
    grid.insertAdjacentHTML("beforeend", next.map((it) => cardHTML(it, false)).join(""));
    shown += next.length;
    updateMore();
  }

  const filters = $(".filters");
  const masthead = $(".masthead");
  // Vị trí gốc của thanh lọc (ngay dưới đầu trang). Không dùng filters.offsetTop vì khi đã dính
  // ở đầu màn hình, giá trị đó thay đổi theo vị trí cuộn.
  const filtersHome = () => masthead.offsetTop + masthead.offsetHeight;
  // Đưa nút đang chọn vào giữa hàng (hàng tab cuộn ngang trên điện thoại).
  function centerInRow(el, smooth) {
    if (!el) return;
    const row = el.parentElement;
    row.scrollTo({ left: el.offsetLeft - row.offsetLeft - (row.clientWidth - el.offsetWidth) / 2, behavior: smooth ? "smooth" : "auto" });
  }
  tabs.forEach((t) => t.addEventListener("click", () => {
    cat = t.dataset.cat; store.set("cat", cat); render();
    centerInRow(t, true);
    if (window.scrollY > filtersHome()) window.scrollTo({ top: filtersHome() });
  }));
  chips.forEach((c) => c.addEventListener("click", () => {
    src = c.dataset.src; store.set("src", src); render();
    centerInRow(c, true);
  }));
  let searchTimer;
  q.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(render, 120); });
  q.addEventListener("keydown", (ev) => { if (ev.key === "Enter") q.blur(); });  // ẩn bàn phím điện thoại
  moreBtn.addEventListener("click", showMore);
  // Tự hiện thêm tin khi cuộn gần cuối danh sách.
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && !moreWrap.hidden) showMore();
    }, { rootMargin: "0px 0px 900px 0px" }).observe(moreWrap);
  }

  // Ảnh lỗi: bỏ khung ảnh; nếu là tin nổi bật thì dựng lại để chọn tin khác.
  grid.addEventListener("error", (ev) => {
    const img = ev.target;
    if (img.tagName !== "IMG") return;
    if (img.dataset.orig) {  // ảnh thu nhỏ lỗi: quay về ảnh gốc
      img.removeAttribute("srcset");
      img.src = img.dataset.orig;
      delete img.dataset.orig;
      return;
    }
    badImages.add(Number(img.dataset.i));
    const card = img.closest(".card");
    if (card.classList.contains("lead")) { render(); return; }
    card.classList.remove("has-img");
    img.parentNode.remove();
  }, true);

  render();

  centerInRow($(".tab.active"));
  centerInRow($(".chip.active"));

  // ---------- tóm tắt nhanh (tải riêng, khi rảnh hoặc khi bấm) ----------
  let quickPromise = null;
  const loadQuick = () => (quickPromise ??= fetch(DATA.quickUrl).then((r) => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }).catch((err) => { quickPromise = null; throw err; }));
  (window.requestIdleCallback || ((fn) => setTimeout(fn, 2500)))(() => loadQuick().catch(() => {}), { timeout: 4000 });

  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 5000);
  }

  grid.addEventListener("click", async (ev) => {
    const card = ev.target.closest(".card");
    if (!card) return;
    const it = ITEMS[Number(card.dataset.i)];

    const quickBtn = ev.target.closest(".quick-btn");
    if (quickBtn) {
      let box = $(".quick", card);
      if (box) {
        box.hidden = !box.hidden;
      } else {
        box = document.createElement("div");
        box.className = "quick";
        box.innerHTML = '<p class="quick-label">Ý chính</p><p class="quick-wait">Đang tải…</p>';
        card.append(box);
        try {
          const sentences = (await loadQuick())[it.i] || [];
          box.innerHTML = '<p class="quick-label">Ý chính</p><ul>' + sentences.map((s) => `<li>${esc(s)}</li>`).join("") + "</ul>";
        } catch {
          box.remove();
          toast("Chưa tải được tóm tắt. Kiểm tra mạng rồi thử lại.");
          return;
        }
      }
      quickBtn.setAttribute("aria-expanded", String(!box.hidden));
      $(".label", quickBtn).textContent = box.hidden ? "Tóm tắt" : "Thu gọn";
      return;
    }

    const ask = ev.target.closest(".ask");
    if (ask) {
      // Tạo link lúc bấm (không chèn sẵn vào từng tin cho trang nhẹ).
      const prompt = ASK_PROMPT + it.title + "\n" + it.url;
      ask.href = "https://claude.ai/new?q=" + encodeURIComponent(prompt);
      navigator.clipboard?.writeText(prompt)
        .then(() => toast("Đã chép câu hỏi. Nếu ô chat trên Claude còn trống, chỉ cần dán vào rồi gửi."))
        .catch(() => {});
    }
  });

  // ---------- ngày hôm nay, giờ tương đối ----------
  const dateline = $("#dateline");
  const compact = matchMedia("(max-width: 719px), (max-height: 500px)");
  function showDate() {
    const opts = compact.matches
      ? { weekday: "long", day: "numeric", month: "numeric" }                 // "Thứ Hai, 2/11"
      : { weekday: "long", day: "numeric", month: "long", year: "numeric" };  // "Thứ Hai, 2 tháng 11, 2026"
    const text = new Intl.DateTimeFormat("vi-VN", opts).format(new Date());
    dateline.textContent = text.charAt(0).toUpperCase() + text.slice(1);
  }
  showDate();
  compact.addEventListener?.("change", showDate);
  function tick() {
    for (const t of $$("time[data-t]")) t.textContent = ago(Number(t.dataset.t));
    const up = $(".updated time");
    up.textContent = ago(new Date(up.getAttribute("datetime")) / 1000);
  }
  tick();
  setInterval(tick, 60000);

  // ---------- chế độ sáng/tối ----------
  // Màu thanh trạng thái / thanh địa chỉ trên điện thoại theo đúng chế độ đang chọn.
  function syncThemeColor() {
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
    for (const m of $$('meta[name="theme-color"]')) { m.content = bg; m.removeAttribute("media"); }
  }
  if (document.documentElement.dataset.theme) syncThemeColor();
  $("#theme-toggle").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    store.set("theme", root.dataset.theme);
    syncThemeColor();
  });

  // ---------- cuộn trang: ẩn thanh lọc khi đọc, nút lên đầu trang ----------
  // Trên điện thoại: cuộn xuống thì ẩn thanh lọc cho rộng chỗ đọc, cuộn lên thì hiện lại cùng nút lên đầu trang.
  const toTop = $("#to-top");
  const phone = matchMedia("(max-width: 719px), (max-height: 500px)");
  let lastY = window.scrollY, ticking = false;
  function onScroll() {
    const y = window.scrollY, dy = y - lastY;
    const home = filtersHome();
    const stuck = y > home;
    filters.classList.toggle("is-stuck", stuck);
    if (phone.matches && document.activeElement !== q) {
      if (dy > 6 && y > home + 200) filters.classList.add("is-hidden");
      else if (dy < -6 || !stuck) filters.classList.remove("is-hidden");
      if (Math.abs(dy) > 6) toTop.hidden = !(y > 900 && dy < 0);
    } else {
      filters.classList.remove("is-hidden");
      toTop.hidden = y < 900;
    }
    if (Math.abs(dy) > 6 || y < 10) lastY = y;
    ticking = false;
  }
  window.addEventListener("scroll", () => {
    if (!ticking) { ticking = true; requestAnimationFrame(onScroll); }
  }, { passive: true });
  toTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
})();
