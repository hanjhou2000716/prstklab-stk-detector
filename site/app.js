const formatNumber = (value) => new Intl.NumberFormat("zh-TW", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
}).format(value);

const setText = (id, value) => {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
};

const renderMarkets = (markets) => {
  for (const [key, market] of Object.entries(markets)) {
    setText(`${key}-session`, `${market.label}｜${market.session}`);
    setText(`${key}-date`, market.date || "—");
  }
};

const renderQuotes = (quotes) => {
  const container = document.getElementById("quote-list");
  if (!container) return;
  if (!quotes.length) {
    container.innerHTML = "<li class=\"empty\">尚無可顯示的報價資料</li>";
    return;
  }
  container.innerHTML = quotes.map((quote) => {
    const direction = quote.change > 0 ? "up" : quote.change < 0 ? "down" : "flat";
    const sign = quote.change > 0 ? "+" : "";
    return `<li><span><b>${quote.ticker}</b><small>${quote.name}</small></span><span class="quote-value"><b>${formatNumber(quote.price)} ${quote.currency}</b><small class="${direction}">${sign}${formatNumber(quote.change)} (${sign}${quote.change_percent}%)</small></span></li>`;
  }).join("");
};

const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
})[character]);

const renderRisk = (risk) => {
  if (!risk) return;
  setText("risk-notice", risk.notice || "公開資料風險觀察。");
  const usScore = risk.us?.sentiment?.score;
  setText("risk-tag", usScore === null || usScore === undefined ? "部分缺漏" : `美股情緒 ${usScore}`);
  const container = document.getElementById("risk-list");
  if (!container) return;
  container.innerHTML = [risk.taiwan, risk.us].filter(Boolean).map((market) => {
    const sentiment = market.sentiment?.score === null || market.sentiment?.score === undefined
      ? "情緒資料暫時無法取得"
      : `${market.sentiment.source_label} ${market.sentiment.score}｜${market.sentiment.label}`;
    const vix = market.vix?.value === undefined || market.vix?.value === null
      ? "VIX 暫時無法取得"
      : `VIX ${market.vix.value}${market.vix.change_percent === null ? "" : `（${market.vix.change_percent > 0 ? "+" : ""}${market.vix.change_percent}%）`}`;
    return `<li><span><b>${market.label}</b><small>${sentiment}</small></span><span class="risk-value"><small>${vix}</small></span></li>`;
  }).join("");
};

const renderNewsList = (id, stories) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!stories?.length) {
    container.innerHTML = '<li class="empty">目前沒有符合持股關鍵字的新聞</li>';
    return;
  }
  container.innerHTML = stories.map((story) => {
    const url = story.url?.startsWith("https://news.cnyes.com/news/id/") ? story.url : "#";
    return `<li><a href="${url}" target="_blank" rel="noopener noreferrer">${escapeHtml(story.title)}</a><small>${escapeHtml(story.source)}</small></li>`;
  }).join("");
};

const renderNews = (news) => {
  renderNewsList("taiwan-news", news?.taiwan);
  renderNewsList("us-news", news?.us);
};

const render = (snapshot) => {
  setText("data-status", snapshot.data_status || "資料暫時無法取得");
  setText("updated-at", snapshot.generated_at ? new Date(snapshot.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "尚未更新");
  renderMarkets(snapshot.markets || {});
  renderQuotes(snapshot.quotes || []);
  renderRisk(snapshot.risk);
  renderNews(snapshot.news);
  if (snapshot.errors?.length) setText("data-note", `部分資料暫時無法取得：${snapshot.errors.map((item) => item.ticker).join("、")}`);
};

fetch("data/market.json", { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject(new Error("資料檔讀取失敗")))
  .then(render)
  .catch(() => setText("data-status", "資料暫時無法取得"));
