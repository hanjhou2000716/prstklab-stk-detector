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

const compactQuoteMeta = (item) => {
  const raw = String(item.quote_source || "公開來源");
  const provider = raw.includes("TPEx") ? "TPEx" : raw.includes("TWSE") ? "TWSE" : raw.includes("TAIFEX") ? "TAIFEX" : raw.includes("Yahoo") ? "Yahoo" : "公開";
  const observed = String(item.quote_time || item.quote_date || "");
  const match = observed.match(/(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2}))?/);
  if (!match) return "來源時間暫時無法取得";
  const date = `${Number(match[1]) % 100}/${Number(match[2])}/${Number(match[3])}`;
  const clock = match[4] ? ` ${match[4]}:${match[5]}` : "";
  // A daily bar without an intraday timestamp is a previous close, not a
  // live Yahoo observation. Keep that distinction visible and compact.
  const label = !clock && (item.freshness === "recent_close" || raw.includes("daily quote"))
    ? "最近收盤"
    : provider;
  const time = `${date}${clock}`;
  const freshness = item.freshness === "stale" ? "｜逾時" : item.freshness === "live" ? "｜盤中" : "";
  return `${label} | ${time}${freshness}`;
};

const renderQuoteList = (id, items) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!items?.length) { container.innerHTML = '<li class="empty">公開報價暫時無法取得</li>'; return; }
  container.innerHTML = items.map((item) => {
    const state = item.change_percent > 0 ? "market-up" : item.change_percent < 0 ? "market-down" : "flat";
    const meta = compactQuoteMeta(item);
    return `<li><span><b>${escapeHtml(item.ticker)}</b><small>${escapeHtml(item.name)}</small></span><span class="quote-value ${state}"><b>${formatNumber(item.price)} ${escapeHtml(item.currency || "")}</b><small>${signedPercent(item.change_percent)}</small><em class="quote-meta">${escapeHtml(meta)}</em></span></li>`;
  }).join("");
};

const activeExternalAlert = (alert) => {
  if (!alert?.summary || !alert?.expires_at) return null;
  const expiresAt = new Date(alert.expires_at);
  return Number.isNaN(expiresAt.getTime()) || expiresAt <= new Date() ? null : alert;
};

const renderFocus = (events, externalAlert) => {
  if (externalAlert) {
    setText("market-focus", `外部快訊｜${externalAlert.summary}`);
    return;
  }
  const event = events?.items?.[0];
  setText("market-focus", event ? (event.brief_title || `${event.short_label}｜${event.title}`) : "今日無重大市場事件，持續觀察。");
};

const formatAlertQuote = (item) => {
  if (!item || item.price === null || item.price === undefined) return "";
  const state = item.change_percent > 0 ? "up" : item.change_percent < 0 ? "down" : "flat";
  return `<div class="alert-quote"><b>${escapeHtml(item.name || item.ticker)}</b><strong class="${state}">${formatNumber(item.price)}${item.currency ? ` ${escapeHtml(item.currency)}` : ""}</strong><small class="${state}">${item.change === null || item.change === undefined ? "" : `${item.change > 0 ? "+" : ""}${formatNumber(item.change)}　`}${signedPercent(item.change_percent)}</small></div>`;
};

const externalAlertProfile = (category, indices) => {
  const profiles = {
    black_swan: { tickers: ["WTI", "GOLD"], why: "已核對的極端災害、重大系統性事故或市場中斷，可能快速改變全球風險偏好。", linked: "可能連動油價、黃金、美元、日韓市場、Nasdaq 與加密資產；需由後續公開報價確認。", watch: "觀察官方災情更新、能源與避險資產，以及主要股市是否出現持續且同步的波動。" },
    material_positive: { tickers: ["NASDAQ", "SOX"], why: "已核對的停火、政策緩和或其他重大正向事件，可能降低短期風險溢酬；實際影響仍取決於後續細節。", linked: "可能連動油價、黃金、美元、Nasdaq、費半與出口導向市場。", watch: "觀察事件是否有正式細節、油價與避險資產是否回落，以及科技與半導體指數是否同步確認。" },
    energy: { tickers: ["WTI", "GOLD"], why: "能源供應、地緣消息或油價大幅波動可能改變通膨與利率預期。", linked: "可能連動油價、黃金、美元、航運與全球股市風險偏好；以後續價格確認。", watch: "觀察油價、黃金、美元與主要科技指數是否出現可核對的同步變化。" },
    conflict: { tickers: ["WTI", "GOLD"], why: "地緣事件可能推升避險與能源風險溢酬，影響範圍須待官方與市場資料確認。", linked: "可能連動油價、黃金、美元、航運與全球股市風險偏好。", watch: "觀察地緣消息、油價與主要市場是否持續擴大波動。" },
    policy: { tickers: ["NASDAQ", "SOX"], why: "政策或關稅消息可能改變供應鏈、成本與需求預期，應區分公告與實際執行範圍。", linked: "可能連動費半、Nasdaq、出口導向與台股科技權值。", watch: "觀察費半、Nasdaq 與台股電子權值是否出現同步反應或分歧。" },
    semiconductor: { tickers: ["SOX", "NASDAQ"], why: "半導體巨頭消息可能改變需求與資本支出預期，但不代表整個產業。", linked: "可能連動費半、Nasdaq、台積電與台股半導體權值。", watch: "觀察費半與台美半導體權值是否以後續價格同步確認。" },
  };
  const fallback = { tickers: ["NASDAQ", "SOX"], why: "外部公開快訊已通過系統簽章驗證，影響範圍仍須由官方與市場資料確認。", linked: "可能連動市場待後續公開報價確認。", watch: "觀察主要股市、能源、利率或半導體指數是否出現可核對的同步變化。" };
  const profile = profiles[category] || fallback;
  return { ...profile, related: profile.tickers.map((ticker) => indices.find((item) => item.ticker === ticker)).filter(Boolean) };
};

const externalAlertLabel = (category) => ({
  black_swan: "黑天鵝事件",
  material_positive: "重大正向事件",
}[category] || "外部快訊");

const safeHttpsUrl = (value) => {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" ? url.href : "";
  } catch (_) { return ""; }
};

const traceTime = (value) => {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false });
};

const renderAlertTrace = (event) => {
  const container = document.getElementById("alert-trace");
  if (!container) return;
  container.replaceChildren();
  container.hidden = true;
  const trace = event?.source_trace;
  if (!trace) return;
  const facts = [];
  if (trace.verification) facts.push(`核對：${trace.verification}`);
  if (event?.impact_confirmation?.method) {
    const markets = (event.impact_confirmation.markets || []).join("、");
    facts.push(`市場影響核對：${event.impact_confirmation.method}${markets ? `（${markets}）` : ""}`);
  }
  if (trace.source_label) facts.push(`來源：${trace.source_label}`);
  const domains = Array.isArray(trace.verified_domains) ? trace.verified_domains.filter(Boolean) : [];
  if (domains.length) facts.push(`核對網域：${domains.join("、")}`);
  const eventTime = traceTime(trace.event_time);
  if (eventTime) facts.push(`事件時間：${eventTime} CST`);
  const checkedAt = traceTime(trace.checked_at);
  if (checkedAt) facts.push(`核對時間：${checkedAt} CST`);
  facts.forEach((fact) => {
    const item = document.createElement("span");
    item.textContent = fact;
    container.append(item);
  });
  const sourceUrl = safeHttpsUrl(trace.source_url);
  if (sourceUrl) {
    const link = document.createElement("a");
    link.href = sourceUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "開啟原始來源 ↗";
    container.append(link);
  }
  container.hidden = container.childElementCount === 0;
};

const renderAlertCard = (events, generatedAt, externalAlert, indices = []) => {
  const profile = externalAlert ? externalAlertProfile(externalAlert.category, indices) : null;
  const event = externalAlert ? {
    kind: "external_alert", risk_level: externalAlert.category === "black_swan" ? "高風險" : "警戒", short_label: externalAlertLabel(externalAlert.category),
    brief_title: `金十｜${externalAlertLabel(externalAlert.category)}`, summary: externalAlert.summary,
    trigger: `事件時間：${externalAlert.occurred_at}`,
    why_important: profile.why,
    market_context: `${profile.linked} 來源：${externalAlert.source}。`,
    stock_observation: profile.watch,
    friendly_reminder: "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    related: profile.related,
    source_trace: {
      verification: externalAlert.source === "gdelt" ? "兩個獨立新聞網域交叉核對" : "已簽章驗證的外部公開快訊",
      source_label: externalAlert.source === "jin10" ? "金十授權快訊" : "GDELT 交叉核對",
      source_url: externalAlert.source_url || "",
      event_time: externalAlert.occurred_at || "",
      checked_at: externalAlert.received_at || "",
      verified_domains: externalAlert.verified_domains || [],
    },
  } : events?.items?.[0];
  const card = document.getElementById("alert-card");
  if (!card) return;
  const displayTime = generatedAt ? new Date(generatedAt).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "公開資料更新中";
  setText("alert-time", `${displayTime} CST`);
  if (!event) {
    card.dataset.risk = "neutral";
    setText("alert-banner", "今日無重大市場事件，持續觀察");
    setText("alert-headline", "市場訊號尚未達提醒門檻");
    setText("alert-summary", "目前沒有需優先提示的重大市場事件。");
    setText("alert-trigger", "為何重要：日內價格訊號尚未觸及提醒門檻。");
    setText("alert-context", "可能連動：持續觀察公開資料與主要市場變化。");
    setText("alert-stock-observation", "股市觀察：等待可核對的市場變化，不預設市場間因果。 ");
    setText("alert-reminder", "僅供公開資訊整理與教育性觀察，不構成投資建議。");
    document.getElementById("alert-quote-grid").innerHTML = '<p class="empty">目前沒有符合門檻的價格訊號</p>';
    renderAlertTrace(null);
    return;
  }
  const risk = event.risk_level || "持續觀察";
  card.dataset.risk = risk.includes("高風險") ? "high" : risk.includes("警戒") ? "warning" : "neutral";
  const externalBanner = externalAlert?.category === "black_swan" ? "極端黑天鵝／重大風險事件" : externalAlert?.category === "material_positive" ? "已核對重大正向事件" : "已核對外部快訊";
  setText("alert-banner", event.kind === "market_signal" ? event.short_label : event.kind === "external_alert" ? externalBanner : "已核對的重要市場事件");
  setText("alert-headline", event.brief_title || `${event.short_label}｜${event.title}`);
  setText("alert-summary", `事件：${event.summary || event.title || "公開市場事件更新。"}`);
  setText("alert-trigger", `為何重要：${event.why_important || event.trigger || "已核對公開訊號，等待後續市場反應。"}`);
  setText("alert-context", `可能連動：${event.market_context || "持續觀察公開資料。"}`);
  setText("alert-stock-observation", `股市觀察：${event.stock_observation || "觀察主要市場是否出現可核對的同步變化。"}`);
  setText("alert-reminder", event.friendly_reminder || "僅供公開資訊整理與教育性觀察，不構成投資建議。");
  const quoteItems = [event.instrument, ...(event.related || [])].filter(Boolean).slice(0, 2);
  document.getElementById("alert-quote-grid").innerHTML = quoteItems.length ? quoteItems.map(formatAlertQuote).join("") : '<p class="empty">本事件暫無可顯示的公開報價</p>';
  renderAlertTrace(event);
};

const renderLegacyRisk = (risk) => {
  const container = document.getElementById("risk-list");
  if (!container) return;
  const markets = [risk?.taiwan, risk?.us].filter(Boolean);
  if (!markets.length) { container.innerHTML = '<li class="empty">風控資料暫時無法取得</li>'; return; }
  container.innerHTML = markets.map((market) => {
    const sentiment = market.sentiment || {};
    const score = sentiment.score === null || sentiment.score === undefined ? "資料暫時無法取得" : `${sentiment.source_label || "情緒"} ${Number(sentiment.score).toFixed(1)}｜${sentiment.label}`;
    const subScores = Object.entries(sentiment.components || {}).map(([label, value]) => `${label} ${Number(value).toFixed(0)}`).join(" · ");
    const vix = market.vix?.value === undefined || market.vix?.value === null ? "VIX 暫時無法取得" : `VIX ${market.vix.value}${market.vix.change_percent === null ? "" : ` (${signedPercent(market.vix.change_percent)})`}`;
    return `<li><span><b>${escapeHtml(market.label)}</b><small>${escapeHtml(score)}${sentiment.date ? ` · ${escapeHtml(sentiment.date)}` : ""}</small>${subScores ? `<small>${escapeHtml(subScores)}</small>` : ""}</span><span class="risk-value"><small>${escapeHtml(vix)}</small></span></li>`;
  }).join("");
};

const renderRisk = (risk) => {
  const container = document.getElementById("risk-list");
  if (!container) return;
  const markets = [["taiwan", risk?.taiwan], ["us", risk?.us]].filter(([, market]) => Boolean(market));
  if (!markets.length) {
    container.innerHTML = '<p class="empty">情緒資料暫時無法取得</p>';
    return;
  }
  container.innerHTML = markets.map(([marketKey, market]) => {
    const sentiment = market.sentiment || {};
    const source = sentiment.source_label || (marketKey === "taiwan" ? "TAIEX Macro FGI" : "CNN Fear & Greed");
    const score = sentiment.score === null || sentiment.score === undefined ? "—" : Number(sentiment.score).toFixed(1);
    const sentimentLabel = sentiment.label || "資料暫時無法取得";
    const vix = market.vix || {};
    const vixValue = vix.value === undefined || vix.value === null ? "—" : Number(vix.value).toFixed(2);
    const vixChange = vix.change_percent === null || vix.change_percent === undefined ? "資料暫時無法取得" : signedPercent(vix.change_percent);
    const vixState = vix.change_percent > 0 ? "risk-up" : vix.change_percent < 0 ? "risk-down" : "flat";
    return `<section class="risk-market-group"><h4>${escapeHtml(market.label)}</h4><div class="risk-metric-grid"><article class="risk-metric-card"><span>${escapeHtml(source)}</span><strong>${escapeHtml(score)}</strong><small>${escapeHtml(sentimentLabel)}</small></article><article class="risk-metric-card ${vixState}"><span>VIX</span><strong>${escapeHtml(vixValue)}</strong><small>${escapeHtml(vixChange)}</small></article></div></section>`;
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
  const secondary = events?.items?.slice(1) || [];
  if (!secondary.length) { container.innerHTML = '<li class="empty">目前沒有其他同步市場訊號</li>'; return; }
  container.innerHTML = `<li class="signal-list-title">同步市場訊號</li>${secondary.map((event) => `<li class="signal-card"><b>${escapeHtml(event.brief_title || `${event.short_label}｜${event.title}`)}</b><small>${escapeHtml(event.source || "公開市場報價")}</small></li>`).join("")}`;
};

const renderSourceHealth = (health, snapshot = {}) => {
  const card = document.getElementById("source-health");
  const summary = document.getElementById("source-health-summary");
  const event = document.getElementById("source-health-event");
  const list = document.getElementById("source-health-list");
  if (!summary || !event || !list) return;
  if (!health?.sources || !health?.event_scan) {
    const observedAt = traceTime(snapshot.generated_at);
    summary.textContent = "等待下一輪健康檢查";
    event.textContent = "此市場快照建立於健康狀態欄位上線前；下一次資料刷新將顯示各來源狀態。";
    event.dataset.status = "partial";
    list.innerHTML = `<li><span><b>目前市場快照</b><small>${escapeHtml(observedAt || "時間暫時無法取得")}</small></span><em class="source-status partial">待刷新</em></li>`;
    if (card) card.open = false;
    return;
  }
  const missing = health.sources.filter((source) => source.status === "partial").length;
  summary.textContent = `${missing} 個來源有資料缺口`;
  const scan = health.event_scan;
  event.textContent = `${scan.label || "事件掃描"}｜${scan.detail || ""}`;
  event.dataset.status = scan.status || "partial";
  list.innerHTML = health.sources.map((source) => {
    const status = source.status === "healthy" ? "正常" : source.status === "warming" ? "建檔中" : "部分缺漏";
    const issue = Array.isArray(source.issues) && source.issues.length ? source.issues.join("；") : "本輪可用";
    return `<li><span><b>${escapeHtml(source.label || source.key)}</b><small>${escapeHtml(issue)}</small></span><em class="source-status ${escapeHtml(source.status || "partial")}">${status}</em></li>`;
  }).join("");
  if (card) card.open = false;
};

const renderBriefing = (briefing, generatedAt) => {
  const report = briefing || {};
  const observations = report.observations || [];
  const displayTime = generatedAt ? new Date(generatedAt).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "公開資料更新中";
  setText("briefing-time", `${displayTime} CST`);
  setText("briefing-overview", report.overview || "本次以公開市場報價、官方事件與風險資料整理市場脈絡。 ");
  setText("briefing-reminder", report.reminder || "僅供公開資訊整理與教育性觀察，不構成投資建議。");
  const container = document.getElementById("briefing-observations");
  if (!container) return;
  if (!observations.length) { container.innerHTML = '<p class="empty">本次定時報資料暫時無法取得</p>'; return; }
  container.innerHTML = observations.map((item) => `<article class="briefing-observation"><h4>${escapeHtml(item.title || "公開市場觀察")}</h4><p><b>事件：</b>${escapeHtml(item.event || "公開資料更新中。")}</p><p><b>為何重要：</b>${escapeHtml(item.importance || "持續核對公開資料。")}</p><p><b>可能影響：</b>${escapeHtml(item.market_impact || "不預設市場間因果。")}</p><p><b>你要看：</b>${escapeHtml(item.watch || "觀察後續公開市場報價。")}</p></article>`).join("");
};

const renderLegacyResearchList = (id, items, empty) => {
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
    if (item.strategy === "resonance") return `共振相符度 ${Number(item.score).toFixed(1)} / 100`;
    if (item.strategy === "value") return `璞玉價值分數 ${Number(item.score).toFixed(0)} / 100`;
    return `動能相符度 ${Number(item.score).toFixed(1)} / 100`;
  };
  container.innerHTML = items.slice(0, 5).map((item) => {
    const valueMetrics = item.strategy === "value" ? `｜ROE ${item.roe === null || item.roe === undefined ? "—" : `${(Number(item.roe) * 100).toFixed(1)}%`}｜本益比 ${item.pe === null || item.pe === undefined ? "—" : Number(item.pe).toFixed(1)}` : "";
    const structure = structureText(item.structure);
    return `<li><span><b>${escapeHtml(item.ticker)}</b><small>${escapeHtml(item.name || item.ticker)}${structure ? `｜${escapeHtml(structure)}` : ""}${valueMetrics}</small></span><span class="risk-value"><small>${escapeHtml(strategyScore(item))}</small></span></li>`;
  }).join("");
};

const researchStructureLabel = (value) => String(value || "").replace(/[\[\]'\"]/g, "").split(",").map((item) => item.trim()).filter(Boolean).join("、");

const researchStrategyLabel = (item) => {
  if (item.strategy === "price_action") return researchStructureLabel(item.structure) || "裸 K 結構觀察";
  if (item.strategy === "momentum") return "動能觀察";
  if (item.strategy === "resonance") return item.status || "三維共振";
  return item.pe === null || item.pe === undefined ? "璞玉價值｜本益比暫時無法取得" : `璞玉價值｜本益比 ${Number(item.pe).toFixed(1)}`;
};

const researchStrategyTags = (item) => {
  if (item.strategy === "price_action") {
    const labels = researchStructureLabel(item.structure).split("、").filter(Boolean);
    return labels.length ? labels : ["裸 K 結構觀察"];
  }
  if (item.strategy === "resonance") {
    const labels = researchStructureLabel(item.conditions_matched).split("、").filter(Boolean);
    return labels.length ? labels : [researchStrategyLabel(item)];
  }
  if (item.strategy === "value") {
    const labels = researchStructureLabel(item.value_checks).split("、").filter(Boolean);
    return labels.length ? labels : [researchStrategyLabel(item)];
  }
  return [researchStrategyLabel(item)];
};

const researchScoreParts = (item) => {
  if (item.score === null || item.score === undefined) return { label: "策略分數", value: "暫時無法取得" };
  if (item.strategy === "price_action") return { label: "裸 K 相符度", value: `${Number(item.score).toFixed(1)} / 100` };
  if (item.strategy === "resonance") return { label: item.status || "共振分數", value: `${Number(item.score).toFixed(1)} / 100` };
  if (item.strategy === "value") return { label: "璞玉價值分數", value: `${Number(item.score).toFixed(0)} / 100` };
  return { label: "動能分數", value: `${Number(item.score).toFixed(1)} / 100` };
};

const renderResearchList = (id, items, empty) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!items?.length) { container.innerHTML = `<li class="empty">${escapeHtml(empty)}</li>`; return; }
  container.innerHTML = items.slice(0, 5).map((item) => {
    const state = item.change_percent > 0 ? "market-up" : item.change_percent < 0 ? "market-down" : "flat";
    const currency = item.market === "taiwan" ? "TWD" : "USD";
    const price = item.close === null || item.close === undefined ? "報價待完整掃描" : `${formatNumber(item.close)} ${currency}`;
    const change = item.change_percent === null || item.change_percent === undefined ? "—" : signedPercent(item.change_percent);
    const tags = researchStrategyTags(item).map((label) => `<span class="strategy-chip">${escapeHtml(label)}</span>`).join("");
    const score = researchScoreParts(item);
    return `<li class="research-item"><div class="research-item-top"><div class="research-identity"><b class="research-ticker">${escapeHtml(item.ticker)}</b><span class="research-company">${escapeHtml(item.name || item.ticker)}</span></div><span class="research-price ${state}"><span class="research-price-label">收盤參考</span><strong>${escapeHtml(price)}</strong><small>${escapeHtml(change)}</small></span></div><div class="research-strategies">${tags}</div><div class="research-item-bottom"><span class="research-score-label">${escapeHtml(score.label)}</span><strong class="research-score">${escapeHtml(score.value)}</strong></div></li>`;
  }).join("");
};

let activeResearchMarket = "taiwan";

const renderResearch = (snapshot) => {
  const report = snapshot.research_report || {};
  const candidates = report.candidates || [];
  const generatedAt = report.generated_at ? ` 掃描時間：${new Date(report.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}` : "";
  setText("research-tag", activeResearchMarket === "taiwan" ? "台股" : "美股");
  const unavailable = report.availability === "expired" ? "研究資料逾時，等待下一次全市場掃描" : null;
  setText("research-notice", unavailable || generatedAt.trim() || "掃描時間暫時無法取得");
  const marketCandidates = candidates.filter((item) => item.market === activeResearchMarket);
  const valueSource = (report.sources || []).find((item) => item.market === activeResearchMarket && item.strategy === "value");
  const valuePending = valueSource?.scan_state === "building";
  const valueMessage = valuePending
    ? `歷史核對中：已完成 ${valueSource.history_cached ?? 0}/${valueSource.history_expected ?? "—"} 檔；未完成八項公開資料覆核前不列入正式璞玉價值候選。`
    : "本輪沒有同時通過璞玉品質與三月去熱門化公開資料覆核的標的";
  renderResearchList("research-list", marketCandidates.filter((item) => item.strategy === "price_action"), unavailable || "本輪掃描沒有符合裸 K 結構的候選標的");
  renderResearchList("momentum-list", marketCandidates.filter((item) => item.strategy === "momentum"), unavailable || "本輪掃描沒有符合動能條件的候選標的");
  renderResearchList("resonance-list", marketCandidates.filter((item) => item.strategy === "resonance"), unavailable || "本輪掃描沒有符合三維共振條件的候選標的");
  renderResearchList("value-list", marketCandidates.filter((item) => item.strategy === "value"), unavailable || valueMessage);
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
  const externalAlert = activeExternalAlert(snapshot.external_alert);
  setText("data-status", snapshot.data_status || "資料更新中");
  setText("updated-at", snapshot.generated_at ? new Date(snapshot.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "尚未更新");
  renderFocus(snapshot.events, externalAlert);
  renderMarkets(snapshot.markets || {});
  renderQuoteList("index-list", snapshot.indices || []);
  renderQuoteList("quote-list", snapshot.quotes || []);
  renderRisk(snapshot.risk);
  renderAlertCard(snapshot.events, snapshot.generated_at, externalAlert, snapshot.indices || []);
  renderEvents(snapshot.events);
  renderSourceHealth(snapshot.source_health, snapshot);
  renderBriefing(snapshot.briefing, snapshot.generated_at);
  renderResearch(snapshot);
  renderNewsList("taiwan-news", snapshot.news?.taiwan);
  renderNewsList("us-news", snapshot.news?.us);
};

// GitHub Pages and Telegram's in-app WebView can both retain a static JSON
// response longer than the dashboard itself.  A per-open query value makes
// every Mini App launch request the current public snapshot, rather than a
// previously cached market.json response.
const snapshotUrl = `data/market.json?v=${Date.now()}`;

fetch(snapshotUrl, {
  cache: "no-store",
  headers: { "Cache-Control": "no-cache" },
})
  .then((response) => response.ok ? response.json() : Promise.reject(new Error("market snapshot unavailable")))
  .then(render)
  .catch(() => { setText("data-status", "資料暫時無法取得"); setText("market-focus", "市場資料暫時無法取得，請稍後再試。"); });
