// Đọc báo mỗi ngày — lọc tin, tóm tắt nhanh, chế độ sáng/tối.
(() => {
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch {} },
  };
  // Dọn khóa API / tóm tắt AI mà bản cũ (đã gỡ) có thể để lại.
  try { localStorage.removeItem("anthropic_api_key"); localStorage.removeItem("ai_summaries"); } catch {}

  const PAGE = 45;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const cards = $$(".card");
  const tabs = $$(".tab");
  const chips = $$(".chip");
  const q = $("#q");
  const moreWrap = $("#more");
  const moreBtn = $("#more-btn");
  const empty = $("#empty");

  // ---------- ngày hôm nay ----------
  const dateline = $("#dateline");
  if (dateline) {
    const text = new Intl.DateTimeFormat("vi-VN", {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    }).format(new Date());
    dateline.textContent = text.charAt(0).toUpperCase() + text.slice(1);
  }

  // ---------- chế độ sáng/tối ----------
  $("#theme-toggle")?.addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    store.set("theme", root.dataset.theme);
  });

  // ---------- lọc tin ----------
  const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");
  for (const c of cards) {
    c._cats = (c.dataset.cats || "").split(" ");
    c._text = norm(($(".title", c)?.textContent || "") + " " + ($(".desc", c)?.textContent || ""));
  }

  let cat = store.get("cat") || "all";
  let src = store.get("src") || store.get("filter") || "all";
  if (!tabs.some((t) => t.dataset.cat === cat)) cat = "all";
  if (!chips.some((c) => c.dataset.src === src)) src = "all";
  let limit = PAGE;

  function apply() {
    const term = norm(q.value.trim());
    tabs.forEach((t) => { t.classList.toggle("active", t.dataset.cat === cat); t.setAttribute("aria-selected", t.dataset.cat === cat); });
    chips.forEach((c) => { c.classList.toggle("active", c.dataset.src === src); c.setAttribute("aria-pressed", c.dataset.src === src); });

    let shown = 0, matched = 0, lead = null;
    for (const c of cards) {
      const ok = (cat === "all" || c._cats.includes(cat))
        && (src === "all" || c.dataset.source === src)
        && (!term || c._text.includes(term));
      if (ok) matched++;
      const visible = ok && matched <= limit;
      c.hidden = !visible;
      c.classList.remove("lead");
      if (visible && shown++ === 0 && c.classList.contains("has-img") && !term) lead = c;
    }
    lead?.classList.add("lead");
    empty.hidden = matched > 0;
    moreWrap.hidden = matched <= limit;
    if (matched > limit) moreBtn.querySelector("span").textContent = `(còn ${matched - limit} tin)`;
  }

  function reset() { limit = PAGE; apply(); }

  tabs.forEach((t) => t.addEventListener("click", () => {
    cat = t.dataset.cat; store.set("cat", cat); reset();
    const filters = $(".filters");
    if (filters.getBoundingClientRect().top <= 0) window.scrollTo({ top: filters.offsetTop });
  }));
  chips.forEach((c) => c.addEventListener("click", () => { src = c.dataset.src; store.set("src", src); reset(); }));
  q.addEventListener("input", reset);
  moreBtn.addEventListener("click", () => { limit += PAGE; apply(); });
  window.addEventListener("imgfail", apply);  // ảnh lỗi thì chọn lại tin nổi bật
  apply();

  // Cuộn hàng tab để mục / báo đang chọn nằm trong màn hình.
  for (const el of [$(".tab.active"), $(".chip.active")]) {
    if (!el) continue;
    const row = el.parentElement;
    row.scrollLeft = el.offsetLeft - row.offsetLeft - (row.clientWidth - el.offsetWidth) / 2;
  }

  // ---------- tóm tắt nhanh + hỏi Claude ----------
  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 5000);
  }
  $("#grid").addEventListener("click", (ev) => {
    const quick = ev.target.closest(".quick-btn");
    if (quick) {
      const box = $(".quick", quick.closest(".card"));
      box.hidden = !box.hidden;
      quick.setAttribute("aria-expanded", String(!box.hidden));
      $(".label", quick).textContent = box.hidden ? "Tóm tắt nhanh" : "Thu gọn";
      return;
    }
    const ask = ev.target.closest(".ask");
    if (ask && navigator.clipboard) {
      navigator.clipboard.writeText(ask.dataset.prompt)
        .then(() => toast("Đã chép câu hỏi. Nếu ô chat trên Claude còn trống, chỉ cần dán vào rồi gửi."))
        .catch(() => {});
    }
  });

  // ---------- thời gian tương đối ----------
  function ago(iso) {
    if (!iso) return "";
    const m = Math.round((Date.now() - new Date(iso)) / 60000);
    if (m < 1) return "vừa xong";
    if (m < 60) return `${m} phút trước`;
    if (m < 1440) return `${Math.round(m / 60)} giờ trước`;
    return `${Math.round(m / 1440)} ngày trước`;
  }
  function tick() {
    for (const t of $$("time[datetime]")) {
      const s = ago(t.getAttribute("datetime"));
      if (s) t.textContent = s;
    }
  }
  tick();
  setInterval(tick, 60000);

  // ---------- nút lên đầu trang ----------
  const toTop = $("#to-top");
  const onScroll = () => { toTop.hidden = window.scrollY < 900; };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  toTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
})();
