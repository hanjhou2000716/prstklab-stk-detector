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
  setText("market-focus", event ? `${event.short_label}｜${event.title}` : "今日無重大市場事件，持續觀察。");
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
  container.innerHTML = stories.map((story) => {
    const url = story.url?.startsWith("https://news.cnyes.com/news/id/") ? story.url : "#";
    return `<li><a href="${url}" target="_blank" rel="noopener noreferrer">${escapeHtml(story.title)}</a><small>${escapeHtml(story.source)}</small></li>`;
  }).join("");
};

const renderEvents = (events) => {
  setText("event-tag", events?.status || "觀察中");
  setText("event-message", events?.message || "今日無重大市場事件，持續觀察。");
  const container = document.getElementById("event-list");
  if (!container) return;
  if (!events?.items?.length) { container.innerHTML = '<li class="empty">目前沒有符合門檻的重大事件</li>'; return; }
  container.innerHTML = events.items.map((event) => `<li>${escapeHtml(`${event.short_label}｜${event.title}`)}<small>${escapeHtml(event.source || "公開來源")}</small></li>`).join("");
};

const renderResearchList = (id, items, empty) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!items?.length) { container.innerHTML = `<li class="empty">${empty}</li>`; return; }
  container.innerHTML = items.map((item) => {
    const valueMetrics = item.strategy === "value" ? `｜ROE ${item.roe === null || item.roe === undefined ? "—" : `${(Number(item.roe) * 100).toFixed(1)}%`}｜本益比 ${item.pe === null || item.pe === undefined ? "—" : Number(item.pe).toFixed(1)}` : "";
    return `<li><span><b>${escapeHtml(item.ticker)}</b><small>${escapeHtml(item.name || item.ticker)}｜${item.market === "taiwan" ? "台股" : "美股"}${item.structure ? `｜${escapeHtml(item.structure)}` : ""}${valueMetrics}</small></span><span class="risk-value"><small>${item.strategy === "value" ? `覆核分數 ${item.score ?? "—"}` : `掃描排序 ${item.rank ?? "—"}`}</small></span></li>`;
  }).join("");
};

const renderResearch = (snapshot) => {
  const report = snapshot.research_report || {};
  const candidates = report.candidates || [];
  const strategyLabel = (strategy) => strategy === "momentum" ? "動能" : strategy === "price_action" ? "裸K" : strategy === "resonance" ? "三維共振" : "品質價值";
  const coverage = (report.sources || []).map((source) => `${source.market === "taiwan" ? "台股" : "美股"} ${strategyLabel(source.strategy)} ${source.candidates ?? 0} 筆`).join("｜");
  const generatedAt = report.generated_at ? ` 掃描時間：${new Date(report.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}` : "";
  setText("research-tag", report.status || "掃描資料");
  setText("research-notice", `${report.notice || "全市場公開資料研究。"}${coverage ? ` ${coverage}` : ""}${generatedAt}`);
  renderResearchList("research-list", candidates.filter((item) => item.strategy === "price_action"), "本輪全市場掃描沒有符合裸 K 結構的候選標的");
  renderResearchList("momentum-list", candidates.filter((item) => item.strategy === "momentum"), "本輪全市場掃描沒有符合動能條件的候選標的");
  renderResearchList("resonance-list", candidates.filter((item) => item.strategy === "resonance"), "本輪全市場掃描沒有符合三維共振條件的候選標的");
  renderResearchList("value-list", candidates.filter((item) => item.strategy === "value"), "本輪上游候選沒有完成品質／價值公開資料覆核");
};

const render = (snapshot) => {
  setText("data-status", snapshot.data_status || "資料更新中");
  setText("updated-at", snapshot.generated_at ? new Date(snapshot.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "尚未更新");
  renderFocus(snapshot.events);
  renderMarkets(snapshot.markets || {});
  renderQuoteList("index-list", snapshot.indices || []);
  renderQuoteList("quote-list", snapshot.quotes || []);
  renderQuoteFreshness(snapshot.quotes || []);
  renderRisk(snapshot.risk);
  renderEvents(snapshot.events);
  renderResearch(snapshot);
  renderNewsList("taiwan-news", snapshot.news?.taiwan);
  renderNewsList("us-news", snapshot.news?.us);
};

fetch("data/market.json", { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject(new Error("market snapshot unavailable")))
  .then(render)
  .catch(() => { setText("data-status", "資料暫時無法取得"); setText("market-focus", "市場資料暫時無法取得，請稍後再試。"); });
