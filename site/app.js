const telegram = window.Telegram?.WebApp;
if (telegram) { telegram.ready(); telegram.expand(); }

const setText = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = value; };
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
const formatNumber = (value) => typeof value === "number" ? value.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "—";
const signedPercent = (value) => value === null || value === undefined ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
const marketName = (key) => key === "taiwan" ? "台股" : key === "us" ? "美股" : key;

const renderMarkets = (markets) => {
  const text = ["taiwan", "us"].map((key) => {
    const market = markets[key];
    return market ? `${marketName(key)}｜${market.session}` : null;
  }).filter(Boolean).join("　");
  setText("market-status", text || "交易日資訊暫時無法取得");
};

const renderQuoteList = (id, items) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!items?.length) { container.innerHTML = '<li class="empty">公開報價暫時無法取得</li>'; return; }
  container.innerHTML = items.map((item) => {
    const state = item.change_percent > 1 ? "up" : item.change_percent < -1 ? "down" : "flat";
    return `<li><span><b>${escapeHtml(item.ticker)}</b><small>${escapeHtml(item.name)}</small></span><span class="quote-value"><b>${formatNumber(item.price)} ${escapeHtml(item.currency || "")}</b><small class="${state}">${signedPercent(item.change_percent)} · ${escapeHtml(item.quote_date || "")}</small></span></li>`;
  }).join("");
};

const renderQuoteFreshness = (quotes) => {
  const dates = [...new Set((quotes || []).map((item) => item.quote_date).filter(Boolean))];
  setText("quote-as-of", dates.length ? `代表標的報價基準日：${dates.join("、")}` : "代表標的報價暫時無法取得");
};

const renderFocus = (events) => {
  const event = events?.items?.[0];
  setText("market-focus", event ? (event.brief_title || `${event.short_label}｜${event.title}`) : "今日無重大市場事件，持續觀察。");
};

const formatAlertQuote = (item) => {
  if (!item || item.price === null || item.price === undefined) return "";
  const state = item.change_percent > 0 ? "up" : item.change_percent < 0 ? "down" : "flat";
  return `<div class="alert-quote"><b>${escapeHtml(item.name || item.ticker)}</b><strong class="${state}">${formatNumber(item.price)}${item.currency ? ` ${escapeHtml(item.currency)}` : ""}</strong><small class="${state}">${item.change === null || item.change === undefined ? "" : `${item.change > 0 ? "+" : ""}${formatNumber(item.change)}　`}${signedPercent(item.change_percent)}</small></div>`;
};

const renderAlertCard = (events, generatedAt) => {
  const event = events?.items?.[0];
  const card = document.getElementById("alert-card");
  if (!card) return;
  const displayTime = generatedAt ? new Date(generatedAt).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "公開資料更新中";
  setText("alert-time", `${displayTime} CST`);
  if (!event) {
    card.dataset.risk = "neutral";
    setText("alert-banner", "今日無重大市場事件，持續觀察");
    setText("alert-headline", "市場訊號尚未達提醒門檻");
    setText("alert-summary", "持續整理公開市場報價與已核對事件。");
    setText("alert-trigger", ""); setText("alert-context", "");
    setText("alert-reminder", "僅供公開資訊整理與教育性觀察，不構成投資建議。");
    document.getElementById("alert-quote-grid").innerHTML = '<p class="empty">目前沒有符合門檻的價格訊號</p>';
    return;
  }
  const risk = event.risk_level || "持續觀察";
  card.dataset.risk = risk.includes("高風險") ? "high" : risk.includes("警戒") ? "warning" : "neutral";
  setText("alert-banner", event.kind === "market_signal" ? event.short_label : "已核對的重要市場事件");
  setText("alert-headline", event.brief_title || `${event.short_label}｜${event.title}`);
  setText("alert-summary", event.summary || event.title || "公開市場事件更新。");
  setText("alert-trigger", event.trigger || "");
  setText("alert-context", `市場關聯：${event.market_context || "持續觀察公開資料。"}`);
  setText("alert-reminder", event.friendly_reminder || "僅供公開資訊整理與教育性觀察，不構成投資建議。");
  const quoteItems = [event.instrument, ...(event.related || [])].filter(Boolean).slice(0, 2);
  document.getElementById("alert-quote-grid").innerHTML = quoteItems.length ? quoteItems.map(formatAlertQuote).join("") : '<p class="empty">本事件暫無可顯示的公開報價</p>';
};

const renderRisk = (risk) => {
  const container = document.getElementById("risk-list");
  if (!container) return;
  const markets = [risk?.taiwan, risk?.us].filter(Boolean);
  if (!markets.length) { container.innerHTML = '<li class="empty">風控資料暫時無法取得</li>'; return; }
  container.innerHTML = markets.map((market) => {
    const sentiment = market.sentiment || {};
    const score = sentiment.score === null || sentiment.score === undefined ? "資料暫時無法取得" : `${sentiment.source_label || "情緒"} ${Number(sentiment.score).toFixed(1)}｜${sentiment.label}`;
    const subScores = Object.entries(sentiment.sub_scores || {}).map(([label, value]) => `${label} ${Number(value).toFixed(0)}`).join(" · ");
    const vix = market.vix?.value === undefined || market.vix?.value === null ? "VIX 暫時無法取得" : `VIX ${market.vix.value}${market.vix.change_percent === null ? "" : ` (${signedPercent(market.vix.change_percent)})`}`;
    return `<li><span><b>${escapeHtml(market.label)}</b><small>${escapeHtml(score)}${sentiment.date ? ` · ${escapeHtml(sentiment.date)}` : ""}</small>${subScores ? `<small>${escapeHtml(subScores)}</small>` : ""}</span><span class="risk-value"><small>${escapeHtml(vix)}</small></span></li>`;
  }).join("");
};

const renderNewsList = (id, stories) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!stories?.length) { container.innerHTML = '<li class="empty">目前沒有可顯示的公開新聞</li>'; return; }
  container.innerHTML = stories.slice(0, 3).map((story) => {
    const url = story.url?.startsWith("https://news.cnyes.com/news/id/") ? story.url : "#";
    const title = String(story.title || "").replace(/^\s*\d+\.\s*/, "");
    return `<li><a href="${url}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a><small>${escapeHtml(story.source)}</small></li>`;
  }).join("");
};

const renderEvents = (events) => {
  setText("event-tag", events?.status || "觀察中");
  const container = document.getElementById("event-list");
  if (!container) return;
  if (!events?.items?.length) { container.innerHTML = '<li class="empty">目前沒有符合門檻的重大事件</li>'; return; }
  container.innerHTML = events.items.slice(1).map((event) => `<li>${escapeHtml(event.brief_title || `${event.short_label}｜${event.title}`)}<small>${escapeHtml(event.source || "公開來源")}</small></li>`).join("") || '<li class="empty">其餘符合門檻的訊號會顯示於此</li>';
};

const renderResearchList = (id, items, empty) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!items?.length) { container.innerHTML = `<li class="empty">${empty}</li>`; return; }
  const structureText = (value) => String(value || "").replace(/[\[\]'\"]/g, "").split(",").map((item) => item.trim()).filter(Boolean).join("、");
  const strategyScore = (item) => {
    if (item.strategy === "price_action") {
      const labels = structureText(item.structure).split("、").filter(Boolean);
      const weights = { "撐壓互換回踩": 50, "雙底右腳確認": 60, "假跌破收復": 70, "訂單塊回踩": 60 };
      const fallback = labels.length ? Math.min(Math.max(...labels.map((label) => weights[label] || 0)) + Math.min((new Set(labels).size - 1) * 10, 30), 100) : null;
      const score = item.score ?? fallback;
      return score === null ? "裸 K相符度 暫時無法取得" : `裸 K相符度 ${Number(score).toFixed(1)} / 100`;
    }
    if (item.score === null || item.score === undefined) return "策略相符度 暫時無法取得";
    if (item.strategy === "resonance") return `共振相符度 ${Math.max(0, Math.min(100, (56 - Number(item.score)) / 56 * 100)).toFixed(1)} / 100`;
    if (item.strategy === "value") return `價值相符度 ${Number(item.score).toFixed(0)} / 5`;
    return `動能相符度 ${Number(item.score).toFixed(1)} / 100`;
  };
  container.innerHTML = items.slice(0, 5).map((item) => {
    const valueMetrics = item.strategy === "value" ? `｜ROE ${item.roe === null || item.roe === undefined ? "—" : `${(Number(item.roe) * 100).toFixed(1)}%`}｜本益比 ${item.pe === null || item.pe === undefined ? "—" : Number(item.pe).toFixed(1)}` : "";
    const structure = structureText(item.structure);
    return `<li><span><b>${escapeHtml(item.ticker)}</b><small>${escapeHtml(item.name || item.ticker)}${structure ? `｜${escapeHtml(structure)}` : ""}${valueMetrics}</small></span><span class="risk-value"><small>${escapeHtml(strategyScore(item))}</small></span></li>`;
  }).join("");
};

let activeResearchMarket = "taiwan";

const renderResearch = (snapshot) => {
  const report = snapshot.research_report || {};
  const candidates = report.candidates || [];
  const generatedAt = report.generated_at ? ` 掃描時間：${new Date(report.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}` : "";
  setText("research-tag", activeResearchMarket === "taiwan" ? "台股" : "美股");
  setText("research-notice", generatedAt.trim() || "掃描時間暫時無法取得");
  const marketCandidates = candidates.filter((item) => item.market === activeResearchMarket);
  renderResearchList("research-list", marketCandidates.filter((item) => item.strategy === "price_action"), "本輪掃描沒有符合裸 K 結構的候選標的");
  renderResearchList("momentum-list", marketCandidates.filter((item) => item.strategy === "momentum"), "本輪掃描沒有符合動能條件的候選標的");
  renderResearchList("resonance-list", marketCandidates.filter((item) => item.strategy === "resonance"), "本輪掃描沒有符合三維共振條件的候選標的");
  renderResearchList("value-list", marketCandidates.filter((item) => item.strategy === "value"), "本輪候選沒有完成品質／價值公開資料覆核");
};

document.querySelectorAll(".research-tab").forEach((tab) => tab.addEventListener("click", () => {
  activeResearchMarket = tab.dataset.market || "taiwan";
  document.querySelectorAll(".research-tab").forEach((item) => {
    const selected = item === tab;
    item.classList.toggle("active", selected);
    item.setAttribute("aria-selected", String(selected));
  });
  if (window.marketSnapshot) renderResearch(window.marketSnapshot);
}));

const render = (snapshot) => {
  window.marketSnapshot = snapshot;
  setText("data-status", snapshot.data_status || "資料更新中");
  setText("updated-at", snapshot.generated_at ? new Date(snapshot.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "尚未更新");
  renderFocus(snapshot.events);
  renderMarkets(snapshot.markets || {});
  renderQuoteList("index-list", snapshot.indices || []);
  renderQuoteList("quote-list", snapshot.quotes || []);
  renderQuoteFreshness(snapshot.quotes || []);
  renderRisk(snapshot.risk);
  renderAlertCard(snapshot.events, snapshot.generated_at);
  renderEvents(snapshot.events);
  renderResearch(snapshot);
  renderNewsList("taiwan-news", snapshot.news?.taiwan);
  renderNewsList("us-news", snapshot.news?.us);
};

fetch("data/market.json", { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject(new Error("market snapshot unavailable")))
  .then(render)
  .catch(() => { setText("data-status", "資料暫時無法取得"); setText("market-focus", "市場資料暫時無法取得，請稍後再試。"); });
