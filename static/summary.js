// Nút "Tóm tắt AI": gọi Claude API ngay từ trình duyệt bằng khóa API của chính bạn.
// Khóa được lưu trong localStorage của trình duyệt này, không nằm trong mã nguồn hay trên GitHub.

const SDK_URL = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@1.3.0/+esm";
const MODEL = "claude-opus-5-5";
const KEY_STORE = "anthropic_api_key";
const CACHE_STORE = "ai_summaries";
const CACHE_LIMIT = 200;
const NEWS_DOMAINS = ["vnexpress.net", "tuoitre.vn", "thanhnien.vn"];

const SYSTEM_PROMPT = `Bạn giúp một người Việt đọc nhanh tin tức. Mỗi lần bạn nhận một bài báo (tiêu đề, nguồn, URL, mô tả ngắn).

Hãy dùng công cụ web_fetch để đọc toàn văn bài tại URL đó, rồi viết bản tóm tắt bằng tiếng Việt:
- Dòng đầu: một câu nêu ý chính của bài.
- Sau đó 3 đến 5 dòng, mỗi dòng bắt đầu bằng "• ", nêu các chi tiết quan trọng: ai, việc gì, khi nào, ở đâu, con số, hệ quả.

Chỉ dựa vào nội dung bài báo, không thêm nhận định riêng. Viết văn bản thuần, không dùng Markdown, không tiêu đề, không lời dẫn kiểu "Dưới đây là bản tóm tắt". Nếu không đọc được bài, viết một dòng nói rõ là không mở được bài, rồi tóm tắt ngắn từ tiêu đề và mô tả.`;

let sdkPromise = null;
const loadSdk = () => (sdkPromise ??= import(SDK_URL)
  .then((m) => m.default)
  .catch((err) => { sdkPromise = null; throw err; }));  // lỗi mạng thì lần sau tải lại

// ---------- lưu trữ trong trình duyệt (bọc try/catch vì có thể bị chặn) ----------
function getKey() {
  try { return localStorage.getItem(KEY_STORE) || ""; } catch { return ""; }
}
function setKey(value) {
  try {
    if (value) localStorage.setItem(KEY_STORE, value);
    else localStorage.removeItem(KEY_STORE);
  } catch {}
}
function readCache() {
  try { return JSON.parse(localStorage.getItem(CACHE_STORE) || "{}"); } catch { return {}; }
}
function cacheGet(url) {
  return readCache()[url]?.text || "";
}
function cachePut(url, text) {
  try {
    const cache = readCache();
    cache[url] = { text, at: Date.now() };
    const urls = Object.keys(cache).sort((a, b) => cache[b].at - cache[a].at);
    for (const old of urls.slice(CACHE_LIMIT)) delete cache[old];
    localStorage.setItem(CACHE_STORE, JSON.stringify(cache));
  } catch {}
}

// ---------- hộp nhập khóa API ----------
const dialog = document.getElementById("key-dialog");
const keyInput = document.getElementById("key-input");

function askForKey() {
  keyInput.value = getKey();
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      if (dialog.returnValue === "save") setKey(keyInput.value.trim());
      if (dialog.returnValue === "remove") setKey("");
      resolve(getKey());
    }, { once: true });
  });
}
document.getElementById("key-open").addEventListener("click", askForKey);

// ---------- gọi Claude ----------
async function summarize(article, onText) {
  const Anthropic = await loadSdk();
  const client = new Anthropic({ apiKey: getKey(), dangerouslyAllowBrowser: true });

  const messages = [{
    role: "user",
    content: `Tóm tắt bài báo này.\nTiêu đề: ${article.title}\nNguồn: ${article.source}\nURL: ${article.url}\nMô tả: ${article.desc}`,
  }];

  let text = "";
  // Công cụ chạy phía máy chủ có thể dừng giữa chừng (pause_turn): gửi lại để chạy tiếp.
  for (let round = 0; round < 3; round++) {
    const stream = client.beta.messages.stream({
      model: MODEL,
      max_tokens: 16000,
      output_config: { effort: "low" },
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: SYSTEM_PROMPT,
      tools: [{
        type: "web_fetch_20260209",
        name: "web_fetch",
        max_uses: 2,
        allowed_domains: NEWS_DOMAINS,
        max_content_tokens: 12000,
      }],
      messages,
    });
    stream.on("text", (delta) => { text += delta; onText(text); });
    const message = await stream.finalMessage();

    if (message.stop_reason === "refusal") {
      throw new Error("Claude từ chối tóm tắt bài này.");
    }
    if (message.stop_reason !== "pause_turn") break;
    messages.push({ role: "assistant", content: message.content });
  }
  return text.trim();
}

function explainError(err, Anthropic) {
  if (Anthropic) {
    if (err instanceof Anthropic.AuthenticationError) return "Khóa API không đúng. Bấm “Khóa AI” ở đầu trang để nhập lại.";
    if (err instanceof Anthropic.PermissionDeniedError) return "Khóa API này không có quyền gọi Claude.";
    if (err instanceof Anthropic.RateLimitError) return "Gọi quá nhiều trong thời gian ngắn. Đợi một chút rồi thử lại.";
    if (err instanceof Anthropic.BadRequestError && /credit|billing|balance/i.test(err.message)) {
      return "Tài khoản Claude API hết tiền. Nạp thêm tại platform.claude.com rồi thử lại.";
    }
    if (err instanceof Anthropic.APIConnectionError) return "Không kết nối được tới Claude. Kiểm tra mạng rồi thử lại.";
    if (err instanceof Anthropic.APIError) return `Lỗi từ Claude API: ${err.message}`;
  }
  if (err?.message?.includes("dynamically imported module")) return "Không tải được thư viện Claude. Kiểm tra mạng rồi thử lại.";
  return err?.message || String(err);
}

// ---------- nút trên từng tin ----------
document.querySelector("main").addEventListener("click", async (event) => {
  const button = event.target.closest(".ai-btn");
  if (!button || button.disabled) return;
  const card = button.closest(".card");
  const out = card.querySelector(".ai-out");
  const link = card.querySelector("a").href;

  if (!out.hidden && out.dataset.state === "done") {  // bấm lần nữa để ẩn
    out.hidden = true;
    button.textContent = "✦ Tóm tắt AI";
    return;
  }

  const cached = cacheGet(link);
  if (cached) {
    out.dataset.state = "done";
    out.className = "ai-out";
    out.textContent = cached;
    out.hidden = false;
    button.textContent = "Ẩn tóm tắt";
    return;
  }

  if (!getKey() && !(await askForKey())) return;

  const article = {
    url: link,
    title: card.querySelector("h2").textContent,
    source: card.querySelector(".badge").textContent,
    desc: card.querySelector("p")?.textContent || "",
  };

  button.disabled = true;
  button.textContent = "Đang đọc bài…";
  out.hidden = false;
  out.className = "ai-out loading";
  out.dataset.state = "loading";
  out.textContent = "Claude đang đọc bài báo…";

  try {
    const text = await summarize(article, (partial) => {
      out.className = "ai-out";
      out.textContent = partial;
    });
    if (!text) throw new Error("Claude không trả về nội dung.");
    out.textContent = text;
    out.dataset.state = "done";
    cachePut(link, text);
    button.textContent = "Ẩn tóm tắt";
  } catch (err) {
    let Anthropic = null;
    try { Anthropic = await loadSdk(); } catch {}
    out.className = "ai-out error";
    out.dataset.state = "error";
    out.textContent = explainError(err, Anthropic);
    button.textContent = "✦ Thử lại";
  } finally {
    button.disabled = false;
  }
});
