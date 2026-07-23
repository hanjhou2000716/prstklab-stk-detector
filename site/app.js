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

const renderEvents = (events) => {
  if (!events) return;
  setText("event-tag", events.status || "持續觀察");
  setText("event-message", events.message || "今日無重大市場事件，持續觀察。");
  const container = document.getElementById("event-list");
  if (!container) return;
  if (!events.items?.length) {
    container.innerHTML = '<li class="empty">今日無重大市場事件</li>';
    return;
  }
  container.innerHTML = events.items.map((event) => {
    const title = `${event.short_label}｜${event.title}`;
    const url = event.url?.startsWith("https://news.cnyes.com/news/id/") ? event.url : null;
    const content = url ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>` : escapeHtml(title);
    return `<li>${content}<small>${escapeHtml(event.source)}</small></li>`;
  }).join("");
};

const renderResearch = (research) => {
  if (!research) return;
  setText("research-tag", research.status || "研究模式");
  setText("research-notice", research.notice || "僅供公開市場結構研究。");
  const container = document.getElementById("research-list");
  if (!container) return;
  if (!research.candidates?.length) {
    container.innerHTML = '<li class="empty">本次無符合結構的代表標的</li>';
    return;
  }
  container.innerHTML = research.candidates.map((candidate) => `<li><span><b>${escapeHtml(candidate.ticker)}</b><small>${escapeHtml(candidate.name)}｜${escapeHtml(candidate.funnel_labels.join("、"))}</small></span><span class="risk-value"><small>ATR ${candidate.atr}｜風險參考 ${candidate.reference_risk}</small></span></li>`).join("");
};

const renderMomentum = (momentum) => {
  if (!momentum) return;
  setText("momentum-tag", momentum.status || "研究模式");
  setText("momentum-notice", momentum.notice || "僅供公開市場動能研究。");
  const container = document.getElementById("momentum-list");
  if (!container) return;
  if (!momentum.candidates?.length) { container.innerHTML = '<li class="empty">本次無符合條件的代表標的</li>'; return; }
  container.innerHTML = momentum.candidates.map((item) => `<li><span><b>${escapeHtml(item.ticker)}</b><small>${escapeHtml(item.name)}｜10日變動 ${item.roc10 > 0 ? "+" : ""}${item.roc10}%</small></span><span class="risk-value"><small>動能分數 ${item.score}</small></span></li>`).join("");
};

const renderResonance = (resonance) => {
  if (!resonance) return;
  setText("resonance-tag", resonance.status || "研究模式");
  setText("resonance-notice", resonance.notice || "僅供公開市場研究。");
  const container = document.getElementById("resonance-list");
  if (!container) return;
  if (!resonance.candidates?.length) { container.innerHTML = '<li class="empty">本次無 FGI 低於 56 的代表標的</li>'; return; }
  container.innerHTML = resonance.candidates.map((item) => `<li><span><b>${escapeHtml(item.ticker)}</b><small>${escapeHtml(item.name)}｜${escapeHtml(item.status)}</small></span><span class="risk-value"><small>共振分數 ${item.score}</small></span></li>`).join("");
};

const renderValue = (value) => {
  if (!value) return;
  setText("value-tag", value.status || "研究模式");
  setText("value-notice", value.notice || "公開財務資料研究。");
  const container = document.getElementById("value-list");
  if (!container) return;
  if (!value.candidates?.length) { container.innerHTML = '<li class="empty">財務資料暫時無法取得</li>'; return; }
  container.innerHTML = value.candidates.map((item) => {
    const roe = item.roe === null ? "ROE —" : `ROE ${(item.roe * 100).toFixed(1)}%`;
    const pe = item.pe === null ? "本益比 —" : `本益比 ${item.pe.toFixed(1)}`;
    return `<li><span><b>${escapeHtml(item.ticker)}</b><small>${escapeHtml(item.name)}｜${roe}｜${pe}</small></span><span class="risk-value"><small>品質欄位 ${item.score}/3</small></span></li>`;
  }).join("");
};

const render = (snapshot) => {
  setText("data-status", snapshot.data_status || "資料暫時無法取得");
  setText("updated-at", snapshot.generated_at ? new Date(snapshot.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "尚未更新");
  renderMarkets(snapshot.markets || {});
  renderQuotes(snapshot.quotes || []);
  renderRisk(snapshot.risk);
  renderNews(snapshot.news);
  renderEvents(snapshot.events);
  renderResearch(snapshot.research);
  renderMomentum(snapshot.momentum);
  renderResonance(snapshot.resonance);
  renderValue(snapshot.value);
  if (snapshot.errors?.length) setText("data-note", `部分資料暫時無法取得：${snapshot.errors.map((item) => item.ticker).join("、")}`);
};

fetch("data/market.json", { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject(new Error("資料檔讀取失敗")))
  .then(render)
  .catch(() => setText("data-status", "資料暫時無法取得"));
