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

const render = (snapshot) => {
  setText("data-status", snapshot.data_status || "資料暫時無法取得");
  setText("updated-at", snapshot.generated_at ? new Date(snapshot.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "尚未更新");
  renderMarkets(snapshot.markets || {});
  renderQuotes(snapshot.quotes || []);
  if (snapshot.errors?.length) setText("data-note", `部分資料暫時無法取得：${snapshot.errors.map((item) => item.ticker).join("、")}`);
};

fetch("data/market.json", { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject(new Error("資料檔讀取失敗")))
  .then(render)
  .catch(() => setText("data-status", "資料暫時無法取得"));
