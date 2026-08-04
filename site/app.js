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
  const checked = item.cross_checked ? "｜已核對" : "｜未核對";
  const base = `${label} | ${time}${freshness}`;
  // Legacy compact form: return `${label} | ${time}${freshness}`
  return `${base}${checked}`;
};

const renderQuoteList = (id, items) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!items?.length) { container.innerHTML = '<li class="empty">公開報價暫時無法取得</li>'; return; }
  const ordered = [...items].sort((a, b) => {
    const rank = (item) => item.ticker === "TAIEX" ? 0 : item.ticker === "TPEx" ? 1 : 2;
    return rank(a) - rank(b);
  });
  container.innerHTML = ordered.map((item) => {
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
  const state = item.change_percent > 0 ? "market-up" : item.change_percent < 0 ? "market-down" : "flat";
  return `<div class="alert-quote"><b>${escapeHtml(item.name || item.ticker)}</b><strong class="${state}">${formatNumber(item.price)}${item.currency ? ` ${escapeHtml(item.currency)}` : ""}</strong><small class="${state}">${item.change === null || item.change === undefined ? "" : `${item.change > 0 ? "+" : ""}${formatNumber(item.change)}　`}${signedPercent(item.change_percent)}</small></div>`;
};

const movementClass = (value) => {
  const text = String(value || "");
  if (/(急升|上漲|漲勢|大漲|走高|反彈)/.test(text)) return "market-up";
  if (/(急跌|下跌|跌勢|大跌|走低|回落)/.test(text)) return "market-down";
  return "flat";
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
  const facts = [];
  const observationId = event?.observation_id || event?.instrument?.observation_id;
  if (observationId) facts.push(`觀測 ID：${observationId}`);
  if (event?.snapshot_id) facts.push(`快照 ID：${event.snapshot_id}`);
  if (event?.trace_id) facts.push(`Trace ID：${event.trace_id}`);
  if (trace?.verification) facts.push(`核對：${trace.verification}`);
  if (event?.impact_confirmation?.method) {
    const markets = (event.impact_confirmation.markets || []).join("、");
    facts.push(`市場影響核對：${event.impact_confirmation.method}${markets ? `（${markets}）` : ""}`);
  }
  if (trace?.source_label) facts.push(`來源：${trace.source_label}`);
  const domains = Array.isArray(trace?.verified_domains) ? trace.verified_domains.filter(Boolean) : [];
  if (domains.length) facts.push(`核對網域：${domains.join("、")}`);
  const crosscheckStatus = String(event?.crosscheck_status || trace?.crosscheck_status || "").trim();
  const crosscheckDomains = Array.isArray(event?.crosscheck_domains)
    ? event.crosscheck_domains.filter(Boolean)
    : (Array.isArray(trace?.crosscheck_domains) ? trace.crosscheck_domains.filter(Boolean) : []);
  if (crosscheckStatus && crosscheckStatus !== "unverified") {
    const label = crosscheckStatus === "official_confirmed"
      ? "官方＋第二來源已核對"
      : crosscheckStatus === "corroborated"
        ? "第二來源已核對"
        : "等待第二來源";
    facts.push(`事件交叉核對：${label}${crosscheckDomains.length ? `（${crosscheckDomains.join("、")}）` : ""}`);
  }
  const eventTime = traceTime(trace?.event_time);
  if (eventTime) facts.push(`事件時間：${eventTime} CST`);
  const checkedAt = traceTime(trace?.checked_at);
  if (checkedAt) facts.push(`核對時間：${checkedAt} CST`);
  const pendingReasons = Array.isArray(event?.notification_reasons)
    ? event.notification_reasons.filter(Boolean)
    : (event?.notification_reason ? [event.notification_reason] : []);
  if (event?.notification_status === "pending" && pendingReasons.length) {
    facts.push(`未推播原因：${pendingReasons.join("、")}`);
  }
  const verificationPlan = Array.isArray(event?.verification_plan) && event.verification_plan.length
    ? event.verification_plan
    : (Array.isArray(trace?.verification_plan) ? trace.verification_plan : []);
  if (verificationPlan.length) {
    facts.push(`核對計畫：${verificationPlan.join("＋")}`);
  }
  facts.forEach((fact) => {
    const item = document.createElement("span");
    item.textContent = fact;
    container.append(item);
  });
  const sourceUrl = safeHttpsUrl(trace?.source_url);
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
    event: externalAlert.summary,
    importance_detail: profile.why,
    market_impact: profile.linked,
    watch: profile.watch,
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
  const pendingNode = document.getElementById("alert-pending");
  if (pendingNode) {
    const pendingItems = externalAlert ? [] : (events?.items || []).filter((item) => item?.notification_status === "pending");
    const reasons = [...new Set(pendingItems.flatMap((item) => Array.isArray(item.notification_reasons)
      ? item.notification_reasons
      : (item.notification_reason ? [item.notification_reason] : [])))];
    const suppressed = externalAlert ? [] : (events?.suppressed_signals || []);
    const suppressedText = suppressed.slice(0, 3).map((item) => {
      const ticker = item.ticker || "市場";
      if (item.reason === "quote_delayed") return `${ticker} 報價逾時`;
      if (item.reason === "taiex_crosscheck_pending") return `${ticker} 等待 TWSE／TAIFEX 核對`;
      if (item.reason === "missing_change_percent") return `${ticker} 缺少漲跌幅`;
      if (item.reason === "below_threshold") {
        const daily = Number.isFinite(item.change_percent) ? `${item.change_percent >= 0 ? "+" : ""}${item.change_percent.toFixed(2)}%` : "無日內幅度";
        const threshold = Number.isFinite(item.daily_threshold) ? `${item.daily_threshold.toFixed(1)}%` : "門檻";
        return `${ticker} ${daily} 未達海外門檻 ${threshold}`;
      }
      return `${ticker} 暫未達提醒條件`;
    });
    const detail = [...reasons.map((reason) => `核對：${reason}`), ...suppressedText];
    pendingNode.hidden = detail.length === 0;
    pendingNode.textContent = detail.length ? `未推播原因：${detail.join("；")}` : "";
  }
  const displayTime = generatedAt ? new Date(generatedAt).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "公開資料更新中";
  setText("alert-time", `${displayTime} CST`);
  if (!event) {
    card.dataset.risk = "neutral";
    setText("alert-banner", "今日無重大市場事件，持續觀察");
    setText("alert-headline", "市場訊號尚未達提醒門檻");
    setText("alert-summary", "目前沒有需優先提示的重大市場事件。");
    setText("alert-trigger", "日內價格訊號尚未觸及提醒門檻。");
    setText("alert-context", "持續核對公開資料與主要市場變化。");
    setText("alert-stock-observation", "等待可核對的市場變化，不預設市場間因果。");
    setText("alert-reminder", "僅供公開資訊整理與教育性觀察，不構成投資建議。");
    document.getElementById("alert-quote-grid").innerHTML = '<p class="empty">目前沒有符合門檻的價格訊號</p>';
    renderAlertTrace(null);
    return;
  }
  const risk = event.risk_level || "持續觀察";
  card.dataset.risk = risk.includes("高風險") ? "high" : risk.includes("警戒") ? "warning" : "neutral";
  const externalBanner = externalAlert?.category === "black_swan" ? "極端黑天鵝／重大風險事件" : externalAlert?.category === "material_positive" ? "已核對重大正向事件" : "已核對外部快訊";
  const banner = document.getElementById("alert-banner");
  // A market signal already states its instrument in the detail headline.
  // Hiding this label avoids rendering "台指價格訊號觸發" twice.
  if (banner) {
    banner.hidden = event.kind === "market_signal";
    banner.textContent = event.kind === "external_alert" ? externalBanner : "已核對的重要市場事件";
  }
  const headline = event.brief_title || `${event.short_label}｜${event.title}`;
  setText("alert-headline", headline);
  const headlineNode = document.getElementById("alert-headline");
  if (headlineNode) headlineNode.className = `market-signal-title ${movementClass(headline)}`;
  setText("alert-summary", event.event || event.summary || event.title || "公開市場事件更新。");
  setText("alert-trigger", event.importance_detail || event.why_important || event.trigger || "已核對公開訊號，等待後續市場反應。");
  setText("alert-context", event.market_impact || event.market_context || "持續觀察公開資料。");
  setText("alert-stock-observation", event.watch || event.stock_observation || "觀察主要市場是否出現可核對的同步變化。");
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
    const vixStage = vix.stage || "波動階段暫時無法取得";
    const vixState = vix.change_percent > 0 ? "risk-up" : vix.change_percent < 0 ? "risk-down" : "flat";
    const vixBasis = vix.percentile_status === "available" ? `歷史百分位 ${vix.percentile ?? "—"}` : "歷史百分位未取得";
    const vixMeta = vix.fetched_at ? `資料 ${new Date(vix.fetched_at).toISOString()}｜${vixBasis}` : vixBasis;
    return `<section class="risk-market-group"><h4>${escapeHtml(market.label)}</h4><div class="risk-metric-grid"><article class="risk-metric-card"><span>${escapeHtml(source)}</span><strong>${escapeHtml(score)}</strong><small>${escapeHtml(sentimentLabel)}</small></article><article class="risk-metric-card ${vixState}"><span>VIX</span><strong>${escapeHtml(vixValue)}</strong><small>${escapeHtml(vixChange)}｜${escapeHtml(vixStage)}</small><small class="metric-meta">${escapeHtml(vixMeta)}</small></article></div></section>`;
  }).join("");
};

const renderNewsList = (id, stories) => {
  const container = document.getElementById(id);
  if (!container) return;
  if (!stories?.length) { container.innerHTML = '<li class="empty">目前沒有可顯示的公開新聞</li>'; return; }
  container.innerHTML = stories.slice(0, 5).map((story) => {
    // Primary stories come from Anue; the market-specific RSS fallback uses
    // Google News links.  Keep both public, read-only domains clickable while
    // rejecting arbitrary URLs from the generated snapshot.
    let url = "#";
    try {
      const parsed = new URL(story.url || "", window.location.href);
      const allowed = ["news.cnyes.com", "news.google.com"];
      if (parsed.protocol === "https:" && allowed.includes(parsed.hostname)) url = parsed.href;
    } catch (_) {
      url = "#";
    }
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
  container.innerHTML = `<li class="signal-list-title">同步市場訊號</li>${secondary.map((event) => {
    const title = event.brief_title || `${event.short_label}｜${event.title}`;
    return `<li class="signal-card"><b class="${movementClass(title)}">${escapeHtml(title)}</b><small>${escapeHtml(event.source || "公開市場報價")}</small></li>`;
  }).join("")}`;
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
  const missing = health.sources.filter((source) => ["partial", "failed", "data_gap"].includes(source.status)).length;
  const displayedMissing = Number.isFinite(Number(health.missing_source_count))
    ? Number(health.missing_source_count)
    : missing;
  const pending = Number(health.pending_event_count || health.monitor_health?.pending_count || 0);
  summary.textContent = `${missing} 個來源有資料缺口`;
  if (displayedMissing !== missing) summary.textContent = `${displayedMissing} 個來源有資料缺口`;
  if (pending) summary.textContent += `｜${pending} 個事件待核對`;
  const scan = health.event_scan;
  event.textContent = `${scan.label || "事件掃描"}｜${scan.detail || ""}`;
  event.dataset.status = scan.status || "partial";
  list.innerHTML = health.sources.map((source) => {
    const status = source.status === "healthy" ? "正常" : source.status === "no_event" ? "無事件" : source.status === "warming" ? "建檔中" : source.status === "pending" ? "待核對" : source.status === "stale" ? "使用快取" : "部分缺漏";
    const pendingReasons = source.status === "pending" && source.pending_reasons && typeof source.pending_reasons === "object"
      ? Object.entries(source.pending_reasons).filter(([, count]) => Number(count) > 0).map(([reason, count]) => {
        const labels = {
          waiting_second_trusted_source: "等待第二來源：尚未有第二個可信新聞網域核對",
          waiting_shared_entity_action: "等待共同實體／動作：來源尚未指向同一事件",
          waiting_market_sync_for_warning: "等待市場同步：相關價格或波動尚未確認",
        };
        return `${labels[reason] || `待核對：${reason}`}（${Number(count)} 個候選）`;
      }).join("；") : "";
    const fallbackPendingReason = source.status === "pending" && !pendingReasons
      ? (source.market_sync_status === "confirmed"
        ? `等待第二來源：尚未有第二個可信新聞網域核對（${Number(source.pending_count || 0)} 個候選）`
        : `等待市場同步：相關價格或波動尚未確認（${Number(source.pending_count || 0)} 個候選）`)
      : "";
    const issue = pendingReasons || fallbackPendingReason || (Array.isArray(source.issues) && source.issues.length ? source.issues.join("；") : "本輪可用");
    let provenance = "";
    if (source.status === "pending" && (source.checked_at || source.source_url)) {
      let domain = "公開來源";
      try { domain = new URL(String(source.source_url || "")).hostname || domain; } catch (_) { /* keep generic label */ }
      const checkedAt = traceTime(source.checked_at) || "時間暫時無法取得";
      provenance = `來源 ${domain}｜核對 ${checkedAt}`;
    }
    const candidateNote = source.key === "research" && source.candidate_state
      ? source.candidate_state === "no_candidates"
        ? "本輪無符合門檻候選"
        : `候選 ${source.candidate_count ?? 0} 檔｜正式 ${source.formal_candidates ?? 0} 檔｜觀察 ${source.observation_candidates ?? 0} 檔`
      : "";
    const sourceCount = Array.isArray(source.source_urls) ? source.source_urls.length : 0;
    const freshness = [];
    if (sourceCount) freshness.push(`端點 ${sourceCount} 個`);
    if (Number.isFinite(Number(source.item_count))) freshness.push(`資料 ${Number(source.item_count)} 筆`);
    if (source.last_success_at) freshness.push(`最近成功 ${traceTime(source.last_success_at)}`);
    if (Number.isFinite(Number(source.latency_ms))) freshness.push(`延遲 ${Math.round(Number(source.latency_ms))} ms`);
    const detail = [issue, candidateNote, provenance, freshness.join("｜")].filter(Boolean).join("｜");
    return `<li><span><b>${escapeHtml(source.label || source.key)}</b><small>${escapeHtml(detail)}</small></span><em class="source-status ${escapeHtml(source.status || "partial")}">${status}</em></li>`;
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
  const correlation = document.getElementById("briefing-correlation");
  if (correlation) {
    correlation.replaceChildren();
    const values = [
      ["觀測 ID", report.observation_id],
      ["報告 Trace ID", report.trace_id],
      ["快照 ID", report.snapshot_id],
    ].filter(([, value]) => value);
    values.forEach(([label, value]) => {
      const item = document.createElement("span");
      item.textContent = `${label}：${value}`;
      correlation.append(item);
    });
    correlation.hidden = correlation.childElementCount === 0;
  }
  const container = document.getElementById("briefing-observations");
  if (!container) return;
  if (!observations.length) { container.innerHTML = '<p class="empty">本次定時報資料暫時無法取得</p>'; return; }
  container.innerHTML = observations.map((item) => `<article class="briefing-observation"><h4>${escapeHtml(item.title || "公開市場觀察")}</h4><p><b>事件：</b>${escapeHtml(item.event || "公開資料更新中。")}</p><p><b>為何重要：</b>${escapeHtml(item.importance || "持續核對公開資料。")}</p><p><b>可能連動：</b>${escapeHtml(item.market_impact || "尚無足夠公開資料判定連動。")}</p><p><b>股市觀察：</b>${escapeHtml(item.watch || "觀察後續公開市場報價。")}</p>${item.source_note ? `<small class="briefing-source">${escapeHtml(item.source_note)}</small>` : ""}</article>`).join("");
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

const renderValueResearch = (id, items, empty) => {
  const container = document.getElementById(id);
  if (!container) return;
  const formal = (items || []).filter((item) => item.list_type === "formal");
  const observation = (items || []).filter((item) => item.list_type === "observation");
  if (!formal.length && !observation.length) {
    container.innerHTML = `<li class="empty">${escapeHtml(empty)}</li>`;
    return;
  }
  // The product output is a five-stock shortlist.  Observation rows are only
  // a fallback while fewer than five formal candidates are available; once
  // the formal list is full, do not make users read a second redundant list.
  const visibleFormal = formal.slice(0, 5);
  const visibleObservation = visibleFormal.length >= 5 ? [] : observation.slice(0, 5 - visibleFormal.length);
  const renderGroup = (title, group) => group.map((item) => {
    const state = item.change_percent > 0 ? "market-up" : item.change_percent < 0 ? "market-down" : "flat";
    const currency = item.market === "taiwan" ? "TWD" : "USD";
    const price = item.close === null || item.close === undefined ? "報價待完整掃描" : `${formatNumber(item.close)} ${currency}`;
    const change = item.change_percent === null || item.change_percent === undefined ? "—" : signedPercent(item.change_percent);
    const tags = researchStrategyTags(item).map((label) => `<span class="strategy-chip">${escapeHtml(label)}</span>`).join("");
    const score = researchScoreParts(item);
    return `<li class="research-item"><div class="research-item-top"><div class="research-identity"><b class="research-ticker">${escapeHtml(item.ticker)}</b><span class="research-company">${escapeHtml(item.name || item.ticker)}</span></div><span class="research-price ${state}"><span class="research-price-label">收盤參考</span><strong>${escapeHtml(price)}</strong><small>${escapeHtml(change)}</small></span></div><div class="research-strategies">${tags}</div><div class="research-item-bottom"><span class="research-score-label">${escapeHtml(score.label)}</span><strong class="research-score">${escapeHtml(score.value)}${item.condition_count ? ` · ${escapeHtml(item.condition_count)}` : ""}</strong></div></li>`;
  }).join("");
  container.innerHTML = `${visibleFormal.length ? `<li class="research-subheading">正式候選（至少 5/6，最多 5 檔）</li>${renderGroup("正式候選", visibleFormal)}` : ""}${visibleObservation.length ? `<li class="research-subheading">觀察名單（3/6 或 4/6，補足至 5 檔）</li>${renderGroup("觀察名單", visibleObservation)}` : ""}`;
};

let activeResearchMarket = "taiwan";

const renderResearch = (snapshot) => {
  const report = snapshot.research_report || {};
  const candidates = report.candidates || [];
  const generatedAt = report.generated_at ? ` 掃描時間：${new Date(report.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}` : "";
  setText("research-tag", activeResearchMarket === "taiwan" ? "台股" : "美股");
  const unavailable = report.availability === "expired" ? "研究資料逾時，等待下一次全市場掃描" : null;
  setText("research-notice", unavailable || generatedAt.trim() || "掃描時間暫時無法取得");
  const sourceFor = (strategy) => (report.sources || []).find((item) => item.market === activeResearchMarket && item.strategy === strategy) || {};
  const sourceBlocked = (strategy) => {
    const source = sourceFor(strategy);
    const partialCandidatesAllowed = source.partial_candidates_allowed === true;
    const buildingWithoutPartialRows = source.status === "建檔中" || source.scan_state === "building";
    return unavailable || source.status === "掃描失敗" || source.status === "資料暫時無法取得" || source.scan_state === "failed" || (buildingWithoutPartialRows && !partialCandidatesAllowed);
  };
  const marketCandidates = candidates.filter((item) => item.market === activeResearchMarket);
  const sourceMessage = (strategy, fallback) => {
    const source = sourceFor(strategy);
    if (unavailable) return unavailable;
    if (source.status === "掃描失敗" || source.scan_state === "failed") return "本輪掃描失敗，等待重試；不沿用舊候選。";
    if (source.status === "資料暫時無法取得") return "本輪資料暫時無法取得；不沿用舊候選。";
    if (source.failed > 0) return `本輪有 ${source.failed} 檔資料缺漏，候選僅供檢視。`;
    return fallback;
  };
  const valueSource = sourceFor("value");
  const valuePending = valueSource?.scan_state === "building";
  const valueDiagnostics = valueSource?.selection_diagnostics || {};
  const valueMessage = valuePending
    ? `歷史核對中：已完成 ${valueSource.history_cached ?? 0}/${valueSource.history_expected ?? "—"} 檔（${valueSource.history_progress_pct ?? 0}%）；未完成六項公開資料覆核前不列入正式璞玉價值候選或觀察名單。`
    : valueDiagnostics.records === 0
      ? "本輪沒有可評估的公開資料；請查看來源健康狀態。"
      : valueDiagnostics.complete_records === 0
        ? `本輪 ${valueDiagnostics.records} 檔仍有必要資料缺口，未列入正式候選。`
        : valueDiagnostics.formal_eligible_records === 0 && valueDiagnostics.observation_eligible_records === 0
          ? `本輪 ${valueDiagnostics.complete_records} 檔資料完整，但未達正式 5/6 或觀察 3/6–4/6 門檻。`
          : "本輪沒有同時通過璞玉品質與三月去熱門化公開資料覆核的標的";
  renderResearchList("research-list", sourceBlocked("price_action") ? [] : marketCandidates.filter((item) => item.strategy === "price_action"), sourceMessage("price_action", "本輪掃描沒有符合裸 K 結構的候選標的"));
  renderResearchList("momentum-list", sourceBlocked("momentum") ? [] : marketCandidates.filter((item) => item.strategy === "momentum"), sourceMessage("momentum", "本輪掃描沒有符合動能條件的候選標的"));
  renderResearchList("resonance-list", sourceBlocked("resonance") ? [] : marketCandidates.filter((item) => item.strategy === "resonance"), sourceMessage("resonance", "本輪掃描沒有符合三維共振條件的候選標的"));
  renderValueResearch("value-list", sourceBlocked("value") ? [] : marketCandidates.filter((item) => item.strategy === "value"), sourceMessage("value", valueMessage));
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

let activeNewsMarket = "taiwan";
document.querySelectorAll(".news-tab").forEach((tab) => tab.addEventListener("click", () => {
  activeNewsMarket = tab.dataset.market || "taiwan";
  document.querySelectorAll(".news-tab").forEach((item) => {
    const selected = item === tab;
    item.classList.toggle("active", selected);
    item.setAttribute("aria-selected", String(selected));
  });
  document.querySelectorAll(".news-panel").forEach((panel) => {
    panel.hidden = panel.dataset.newsMarket !== activeNewsMarket;
  });
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

// The manifest is the release boundary.  Fetching an artifact directly could
// otherwise combine a new market file with an older research/event file when
// GitHub Pages or Telegram's WebView serves different cache generations.
const cacheBust = Date.now();
const fetchJson = (url) => fetch(`${url}${url.includes("?") ? "&" : "?"}v=${cacheBust}`, {
  cache: "no-store",
  headers: { "Cache-Control": "no-cache" },
}).then((response) => response.ok ? response.json() : Promise.reject(new Error(`artifact unavailable: ${url}`)));

const sha256Hex = async (text) => {
  if (!window.crypto?.subtle) throw new Error("integrity verification unavailable");
  const bytes = new TextEncoder().encode(text);
  const digest = await window.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
};

const loadPublishedRelease = async () => {
  const manifest = await fetchJson("data/release-manifest.json");
  if (!manifest || manifest.status !== "ready" || !manifest.release_id) {
    throw new Error("published release is incomplete");
  }
  const hashes = manifest.artifact_hashes || {};
  const paths = manifest.artifact_paths || {};
  const artifactTexts = {};
  for (const [name, expectedHash] of Object.entries(hashes)) {
    const relativePath = String(paths[name] || "");
    if (!relativePath || relativePath.startsWith("/") || relativePath.includes("..")) {
      throw new Error(`invalid artifact path: ${name}`);
    }
    const response = await fetch(`data/${relativePath.replace(/^data\//, "")}?v=${cacheBust}`, {
      cache: "no-store",
      headers: { "Cache-Control": "no-cache" },
    });
    if (!response.ok) throw new Error(`artifact unavailable: ${name}`);
    const text = await response.text();
    if (await sha256Hex(text) !== String(expectedHash)) throw new Error(`artifact hash mismatch: ${name}`);
    artifactTexts[name] = text;
  }
  const marketText = artifactTexts["market.json"];
  if (!marketText) throw new Error("market artifact missing from release");
  const snapshot = JSON.parse(marketText);
  if (String(snapshot.snapshot_id || "") !== String(manifest.market_snapshot_id || "")) {
    throw new Error("market snapshot does not match release");
  }
  window.releaseManifest = manifest;
  return snapshot;
};

loadPublishedRelease()
  .then(render)
  .catch(() => {
    setText("data-status", "發布資料不完整");
    setText("market-focus", "發布資料不完整，等待下一個通過驗證的公開版本。");
  });
