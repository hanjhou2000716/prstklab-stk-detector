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
  const freshness = item.data_status ? `｜${item.data_status}` : item.freshness === "stale" ? "｜逾時" : item.freshness === "live" ? "｜盤中" : "";
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
  const identity = [];
  const evidence = [];
  const decision = [];
  const observationId = event?.observation_id || event?.instrument?.observation_id;
  if (observationId) identity.push(`觀測 ID：${observationId}`);
  if (event?.snapshot_id) identity.push(`快照 ID：${event.snapshot_id}`);
  if (event?.trace_id) identity.push(`Trace ID：${event.trace_id}`);
  if (event?.impact_confirmation?.method) {
    const markets = (event.impact_confirmation.markets || []).join("、");
    evidence.push(`市場影響核對：${event.impact_confirmation.method}${markets ? `（${markets}）` : ""}`);
  }
  if (trace?.verification) evidence.push(`核對：${trace.verification}`);
  if (trace?.source_label) evidence.push(`來源：${trace.source_label}`);
  // FinancialJuice is an attributed discovery source.  Keep its vendor
  // priority visibly separate from the PRStK risk decision so the risk card
  // cannot be read as a vendor score being promoted to system risk.
  const isFinancialJuice = String(event?.source_key || event?.source || "").toLowerCase() === "financialjuice";
  if (isFinancialJuice) {
    const importance = event?.vendor_importance ?? trace?.vendor_importance;
    evidence.push(`來源重要度：${importance === null || importance === undefined || importance === "" ? "待核對" : `${importance} / 10`}`);
    const riskLevel = event?.prstk_risk?.prstk_risk_level || event?.risk_level || "R2";
    evidence.push(`PRStK Risk：${riskLevel}`);
    const hasCrosscheck = Boolean(event?.crosscheck_status && event.crosscheck_status !== "unverified")
      || Boolean(trace?.crosscheck_status && trace.crosscheck_status !== "unverified");
    evidence.push(`Evidence：${hasCrosscheck ? "已完成來源核對" : "等待第二來源"}`);
  }
  const domains = Array.isArray(trace?.verified_domains) ? trace.verified_domains.filter(Boolean) : [];
  if (domains.length) evidence.push(`核對網域：${domains.join("、")}`);
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
    evidence.push(`事件交叉核對：${label}${crosscheckDomains.length ? `（${crosscheckDomains.join("、")}）` : ""}`);
  }
  const evidenceState = String(event?.evidence_state || trace?.evidence_state || "").trim();
  const evidenceReason = String(event?.evidence_reason || trace?.evidence_reason || "").trim();
  if (evidenceState || evidenceReason) {
    const stateLabels = {
      discovery: "探索中",
      single_source: "單一來源",
      pending_crosscheck: "等待核對",
      corroborated: "第二來源已核對",
      official_confirmed: "官方已確認",
    };
    const stateLabel = stateLabels[evidenceState] || evidenceState || "證據狀態待確認";
    evidence.push(`證據狀態：${stateLabel}${evidenceReason ? `｜${evidenceReason}` : ""}`);
  }
  const eventTime = traceTime(trace?.event_time);
  if (eventTime) identity.push(`事件時間：${eventTime} CST`);
  const checkedAt = traceTime(trace?.checked_at);
  if (checkedAt) evidence.push(`核對時間：${checkedAt} CST`);
  const pendingReasons = Array.isArray(event?.notification_reasons)
    ? event.notification_reasons.filter(Boolean)
    : (event?.notification_reason ? [event.notification_reason] : []);
  if (event?.notification_status === "pending" && pendingReasons.length) {
    decision.push(`未推播原因：${pendingReasons.join("、")}`);
  }
  const verificationPlan = Array.isArray(event?.verification_plan) && event.verification_plan.length
    ? event.verification_plan
    : (Array.isArray(trace?.verification_plan) ? trace.verification_plan : []);
  if (verificationPlan.length) decision.push(`核對計畫：${verificationPlan.join("＋")}`);
  const status = event?.notification_status || event?.lifecycle_state;
  if (status) decision.push(`通知判定：${status}`);
  const sourceUrl = safeHttpsUrl(trace?.source_url);
  if (sourceUrl) {
    const link = document.createElement("a");
    link.href = sourceUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "開啟原始來源 ↗";
    link.dataset.traceSource = sourceUrl;
  }
  const groups = [["資料識別", identity], ["來源與證據", evidence], ["通知判定", decision]];
  groups.forEach(([title, facts]) => {
    if (!facts.length) return;
    const section = document.createElement("section");
    section.className = "trace-group";
    const heading = document.createElement("h4");
    heading.textContent = title;
    section.append(heading);
    facts.forEach((fact) => {
      const item = document.createElement("span");
      item.textContent = fact;
      section.append(item);
    });
    if (title === "來源與證據" && sourceUrl) {
      const link = document.createElement("a");
      link.href = sourceUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "開啟原始來源 ↗";
      section.append(link);
    }
    container.append(section);
  });
  container.hidden = container.childElementCount === 0;
};

const externalRiskReasonLabel = (reason) => ({
  risk_threshold_not_reached: "風險門檻尚未達成",
  official_confirmation_missing: "等待官方核對",
  market_sync_missing: "等待市場同步",
})[String(reason || "")] || `待核對：${String(reason || "資料證據不足")}`;

const renderAlertCard = (events, generatedAt, externalAlert, indices = [], externalRisk = null) => {
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
    const externalReasons = externalRisk?.status === "pending"
      ? (Array.isArray(externalRisk.notification?.reasons) ? externalRisk.notification.reasons : [])
      : [];
    const externalText = externalReasons.length
      ? `外部事件 ${externalRisk.score?.prstk_risk_level || "R2"}｜${externalReasons.map(externalRiskReasonLabel).join("、")}｜目前不具備高風險推播資格`
      : "";
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
    const detail = [externalText, ...reasons.map((reason) => `核對：${reason}`), ...suppressedText].filter(Boolean);
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
    const corporatePending = event.corporate_event && event.notification_status === "pending";
    const corporateRoutine = event.corporate_event && event.notification_status === "observe_only";
    banner.textContent = event.kind === "external_alert"
      ? externalBanner
      : corporatePending
        ? "官方來源已核對｜等待台股／台指同步"
        : corporateRoutine
          ? "例行公司公告｜觀察"
          : "已核對的重要市場事件";
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
    const sentimentQuality = sentiment.data_quality === "stale_last_good"
      ? "｜資料降級（最後成功版本）"
      : sentiment.data_quality === "unavailable" ? "｜來源失敗" : "";
    const vix = market.vix || {};
    const vixValue = vix.value === undefined || vix.value === null ? "—" : Number(vix.value).toFixed(2);
    const vixChange = vix.change_percent === null || vix.change_percent === undefined ? "—" : signedPercent(vix.change_percent);
    const vixStage = vix.stage || "波動階段待確認";
    const vixState = vix.change_percent > 0 ? "risk-up" : vix.change_percent < 0 ? "risk-down" : "flat";
    const vixPercentile = vix.percentile_status === "available" && vix.percentile !== null && vix.percentile !== undefined
      ? `｜歷史百分位 ${Number(vix.percentile).toFixed(1)}` : "";
    return `<section class="risk-market-group"><h4>${escapeHtml(market.label)}</h4><div class="risk-metric-grid"><article class="risk-metric-card"><span>${escapeHtml(source)}</span><strong>${escapeHtml(score)}</strong><small>${escapeHtml(sentimentLabel)}${escapeHtml(sentimentQuality)}</small></article><article class="risk-metric-card ${vixState}"><span>VIX</span><strong>${escapeHtml(vixValue)}</strong><small>${escapeHtml(vixChange)}｜${escapeHtml(vixStage)}${escapeHtml(vixPercentile)}</small></article></div></section>`;
  }).join("");
};

const newsEmptyState = (health, intelligence = null) => {
  const status = String(health?.status || "").toLowerCase();
  const collectionState = String(health?.collection_state || "").toLowerCase();
  const checkedAt = traceTime(health?.checked_at || health?.fetched_at);
  const summary = intelligence?.scan_summary || {};
  const sourceDetail = Number.isFinite(Number(summary.provider_count))
    ? `來源 ${Number(summary.provider_count)} 個｜成功 ${Number(summary.successful_provider_count) || 0}／失敗 ${Number(summary.failed_provider_count) || 0}`
    : "";
  if (collectionState === "source_failed") return { title: "新聞來源掃描失敗", detail: ["本輪未採用不完整來源，等待下一次重試", sourceDetail].filter(Boolean).join("｜") };
  if (collectionState === "degraded") return { title: "新聞來源部分降級", detail: ["部分來源失敗，本輪內容需待核對", sourceDetail].filter(Boolean).join("｜") };
  if (status === "failed") return { title: "新聞來源暫時失敗", detail: "本輪未採用不完整來源，等待下一次重試" };
  if (status === "stale") return { title: "目前使用最近成功快取", detail: checkedAt ? `最後成功 ${checkedAt}` : "等待來源恢復後更新" };
  if (status === "pending") return { title: "新聞來源檢查中", detail: "等待本輪市場掃描完成" };
  if (status === "no_event") return { title: "本輪沒有符合條件的公開新聞", detail: "來源掃描完成，沒有可列出的市場事件" };
  return { title: "目前沒有可顯示的公開新聞", detail: "等待下一次市場掃描" };
};

const newsBadgeLabels = (story) => {
  const reasons = Array.isArray(story?.relevance_reasons) ? story.relevance_reasons.map((item) => String(item)) : [];
  const reasonText = reasons.join(" ").toLowerCase();
  const topics = Array.isArray(story?.topics) ? story.topics.map((item) => String(item)) : [];
  const topicText = topics.join(" ").toLowerCase();
  const badges = [];
  const add = (key, label, matched) => {
    if (matched && !badges.some((item) => item.key === key)) badges.push({ key, label });
  };
  const sourceTier = String(story?.source_tier || story?.authority_tier || "").toLowerCase();
  add("official", "官方", sourceTier === "official" || reasons.some((item) => /^official(?::|$)/i.test(item)));
  add("research", "研究標的", reasons.some((item) => /^research_candidate:/i.test(item)) || (story?.research_tickers || []).length > 0);
  add("tracked", "追蹤標的", reasons.some((item) => /^tracked_ticker:/i.test(item)) || (story?.ticker_interest || []).length > 0);
  add("creator", "Creator 提及", reasons.some((item) => /^creator_mentioned:/i.test(item)) || (story?.creator_mentions || []).length > 0);
  add("sector", "產業", reasons.some((item) => /^tracked_sector:/i.test(item)) || (story?.sector_interest || []).length > 0);
  add("macro", "總經", reasons.some((item) => /^active_topic:/i.test(item)) || /macro|econom|rate|fed|inflation|cpi|pce|gdp|央行|利率|通膨|總經/.test(`${reasonText} ${topicText}`));
  const eventCategory = String(story?.event_classification?.category || "").trim();
  const eventLabels = {
    black_swan: "黑天鵝",
    conflict: "地緣衝突",
    policy: "政策",
    fed: "央行／利率",
    macro: "總經數據",
    energy: "能源",
    semiconductor: "半導體",
    market: "市場波動",
    material_positive: "風險降級",
  };
  add("event", `事件：${eventLabels[eventCategory] || eventCategory}`, Boolean(eventCategory));
  if (!badges.length) add("source", "公開來源", true);
  return badges;
};

const humanNewsReason = (reason) => {
  const value = String(reason || "");
  if (/^tracked_ticker:/i.test(value)) return "追蹤標的相關";
  if (/^research_candidate:/i.test(value)) return "研究標的相關";
  if (/^tracked_sector:/i.test(value)) return "追蹤產業相關";
  if (/^active_topic:/i.test(value)) return "主題相關";
  if (/^active_event:/i.test(value)) return "進行中事件相關";
  if (/^creator_mentioned:/i.test(value)) return "Creator 提及";
  if (/^market:/i.test(value) || value === "keyword_no_match") return "市場公開資訊";
  if (/^official(?::|$)/i.test(value)) return "官方來源";
  return value && !value.includes(":") ? value : "";
};

const renderNewsList = (id, stories, providerRegistry = [], health = null, intelligence = null) => {
  const container = document.getElementById(id);
  if (!container) return;
  const diversityNode = document.getElementById(`${id}-source-status`);
  const diversity = intelligence?.source_diversity;
  const scanSummary = intelligence?.scan_summary || {};
  const observationCount = (stories || []).filter((story) => String(story?.source_tier || story?.authority_tier || "").toLowerCase() !== "official").length;
  const funnelDetail = Number.isFinite(Number(scanSummary.provider_count))
    ? `｜來源 ${Number(scanSummary.provider_count)} 個｜可用 ${Number(scanSummary.ranked_story_count) || 0} 則｜排除 ${Number(scanSummary.filtered_story_count) || 0} 則`
    : "";
  if (diversityNode) {
    if (!diversity || diversity.status === "no_event") {
      diversityNode.textContent = `來源核對：本輪沒有可用新聞${funnelDetail}`;
      diversityNode.dataset.state = "no-event";
    } else if (diversity.status === "multi_source") {
      diversityNode.textContent = `來源核對：${Number(diversity.independent_source_count) || 0} 個獨立來源${observationCount ? `｜觀察 ${observationCount} 則` : ""}${funnelDetail}`;
      diversityNode.dataset.state = "multi-source";
    } else {
      diversityNode.textContent = `來源核對：單一來源，等待第二來源${observationCount ? `｜觀察 ${observationCount} 則` : ""}${funnelDetail}`;
      diversityNode.dataset.state = "single-source";
    }
  }
  if (!stories?.length) {
    const state = newsEmptyState(health, intelligence);
    container.innerHTML = `<li class="empty news-empty-state"><strong>${escapeHtml(state.title)}</strong><small>${escapeHtml(state.detail)}</small></li>`;
    return;
  }
  container.innerHTML = stories.slice(0, 5).map((story) => {
    // URL safety is release-provided.  The UI never infers trust from a
    // provider label or accepts an arbitrary URL from the payload.
    let url = "#";
    try {
      const parsed = new URL(story.url || "", window.location.href);
      const provider = providerRegistry.find((item) => item.provider_id === story.provider);
      const domains = provider?.domains || [];
      if (parsed.protocol === "https:" && domains.some((domain) => parsed.hostname === domain || parsed.hostname.endsWith(`.${domain}`)) && story.public_safe !== false) url = parsed.href;
    } catch (_) {
      url = "#";
    }
    const title = String(story.title || "").replace(/^\s*\d+\.\s*/, "");
    const badges = newsBadgeLabels(story).map((badge) => `<span class="news-badge news-badge-${badge.key}">${escapeHtml(badge.label)}</span>`).join("");
    const reasonDetails = (story.relevance_reasons || []).map(humanNewsReason).filter(Boolean).slice(0, 2).join("、");
    const eventReason = story?.event_classification?.reason && story.event_classification.reason !== "keyword_no_match" ? "事件分類已核對" : "";
    const source = escapeHtml(story.source || story.provider_name || "公開來源");
    const detailParts = [reasonDetails, eventReason].filter(Boolean).map((item) => escapeHtml(item));
    const detail = detailParts.length ? `<span class="news-reason-detail">${detailParts.join("、")}</span>` : "";
    return `<li><a href="${url}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a><div class="news-badges" aria-label="這則新聞的關聯理由">${badges}</div><small>${source}${detail}</small></li>`;
  }).join("");
};

const renderEvents = (events) => {
  setText("event-tag", events?.status || "觀察中");
  const container = document.getElementById("event-list");
  if (!container) return;
  const secondary = events?.items?.slice(1) || [];
  if (!secondary.length) { container.innerHTML = '<li class="empty">目前沒有其他同步市場訊號</li>'; }
  else container.innerHTML = `<li class="signal-list-title">同步市場訊號</li>${secondary.map((event) => {
    const title = event.brief_title || `${event.short_label}｜${event.title}`;
    return `<li class="signal-card"><b class="${movementClass(title)}">${escapeHtml(title)}</b><small>${escapeHtml(event.source || "公開市場報價")}</small></li>`;
  }).join("")}`;
  const timeline = document.getElementById("event-timeline");
  const timelineList = document.getElementById("event-timeline-list");
  const feedback = document.getElementById("event-feedback");
  if (!timeline || !timelineList || !feedback) return;
  const rows = (events?.items || []).flatMap((event) => {
    const history = Array.isArray(event.lifecycle_history) ? event.lifecycle_history : [];
    return history.map((entry) => ({ ...entry, event_key: entry.event_key || event.event_cluster_key || event.event_key, title: event.brief_title || event.title }));
  }).filter((entry) => entry.event_key && (entry.at || entry.timestamp || entry.created_at));
  if (!rows.length) {
    timeline.hidden = true;
    timelineList.replaceChildren();
    feedback.hidden = true;
    feedback.replaceChildren();
    return;
  }
  timelineList.innerHTML = rows.slice(-8).reverse().map((entry) => `<li><time>${escapeHtml(traceTime(entry.at || entry.timestamp || entry.created_at) || "時間暫時無法取得")}</time><b>${escapeHtml(entry.state || entry.lifecycle_state || "事件更新")}</b><span>${escapeHtml(entry.reason || entry.note || entry.title || "公開事件狀態更新")}</span></li>`).join("");
  const eventKey = rows[0].event_key;
  feedback.innerHTML = `<span>這則事件對你有幫助嗎？</span><div role="group" aria-label="事件回饋"><button type="button" data-event-feedback="correct" data-event-key="${escapeHtml(eventKey)}">正確</button><button type="button" data-event-feedback="irrelevant" data-event-key="${escapeHtml(eventKey)}">不相關</button><button type="button" data-event-feedback="duplicate" data-event-key="${escapeHtml(eventKey)}">重複</button><button type="button" data-event-feedback="too_late" data-event-key="${escapeHtml(eventKey)}">太晚通知</button></div><small>回饋僅供品質檢視，不會自動修改警報門檻。</small>`;
  timeline.hidden = false;
  feedback.hidden = false;
};

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-event-feedback]");
  if (!button) return;
  const key = button.dataset.eventKey;
  const label = button.dataset.eventFeedback;
  if (!key || !label) return;
  const payload = { event_key: key, label, release_id: window.marketSnapshot?.release_id || null, snapshot_id: window.marketSnapshot?.snapshot_id || null };
  const endpoint = String(window.PRSTK_FEEDBACK_ENDPOINT || "").trim();
  try {
    if (endpoint) {
      const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!response.ok) throw new Error("feedback rejected");
    } else {
      const pending = JSON.parse(window.localStorage?.getItem("prstk_event_feedback") || "[]");
      pending.push(payload);
      window.localStorage?.setItem("prstk_event_feedback", JSON.stringify(pending.slice(-100)));
    }
    button.parentElement.querySelectorAll("button").forEach((item) => { item.disabled = true; });
    button.parentElement.insertAdjacentHTML("afterend", `<small class="feedback-confirmed">已記錄${endpoint ? "並送出" : "於本機待同步"}，不會自動修改政策。</small>`);
  } catch (_) {
    button.insertAdjacentText("afterend", "（暫時無法送出）");
  }
});

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
  const degradedStates = ["critical", "critical_gap", "failed", "degraded_with_fallback", "fallback_active", "partial", "data_gap", "stale", "configuration_missing", "configuration_required"];
  const sourceState = (source) => source.semantic_state || source.state || source.status;
  // The backend emits the canonical semantic gap count.  Older snapshots may
  // not have it, so retain a deterministic compatibility fallback; current
  // releases must never derive a second, divergent investor count in the UI.
  const declaredMissing = Number(health.missing_source_count);
  const missing = Number.isFinite(declaredMissing) && declaredMissing >= 0
    ? Math.trunc(declaredMissing)
    : health.sources.filter((source) => degradedStates.includes(sourceState(source))).length;
  const declaredRuntimeFailure = Number(health.runtime_failure_count);
  const critical = health.sources.filter((source) => ["critical", "critical_gap", "failed", "configuration_missing", "configuration_required"].includes(sourceState(source))).length;
  // Keep optional credential gaps in engineering rows, but show investors the
  // canonical runtime degradation count rather than implying an outage for
  // an unconfigured enrichment provider.
  const displayedMissing = Number.isFinite(declaredRuntimeFailure) && declaredRuntimeFailure >= 0
    ? Math.trunc(declaredRuntimeFailure) : missing;
  const pending = Number(health.pending_event_count || health.monitor_health?.pending_count || 0);
  const aggregate = health.investor_status || (missing === 0 ? "資料正常" : critical > 0 ? "核心資料不足" : "部分資料降級");
  summary.textContent = `${aggregate}${displayedMissing ? `｜${displayedMissing} 個來源有資料缺口` : ""}`;
  if (pending) summary.textContent += `｜${pending} 個事件待核對`;
  const scan = health.event_scan;
  const scanState = scan.state || scan.status || "unknown";
  // Normalize legacy/backend aliases in one place so an empty successful
  // scan can never be presented as a failed source (or vice versa).
  const sourceHealthStateLabel = (state) => {
    const normalized = String(state || "").trim().toLowerCase();
    if (["scan_failed", "failed", "failure", "error"].includes(normalized)) return "掃描失敗";
    if (["no_events", "no_event", "no_new_content", "empty", "none"].includes(normalized)) return "本輪無事件";
    if (["scanning", "running", "in_progress"].includes(normalized)) return "掃描中";
    if (["healthy", "ok", "complete", "completed"].includes(normalized)) return "本輪已掃描";
    return "狀態待確認";
  };
  const scanStateLabel = sourceHealthStateLabel(scanState);
  const observation = health.observability || health.slo || health.monitor_health || {};
  const history = observation.history && typeof observation.history === "object" ? observation.history : null;
  const historyWindow = (key) => history && history.windows && history.windows[key] && typeof history.windows[key] === "object"
    ? history.windows[key] : null;
  const historyParts = [];
  ["24h", "7d"].forEach((key) => {
    const metric = historyWindow(key);
    if (!metric || !Number.isFinite(Number(metric.sample_count))) return;
    const label = key === "24h" ? "24 小時" : "7 日";
    const success = Number.isFinite(Number(metric.success_rate)) ? `成功率 ${Number(metric.success_rate).toFixed(1)}%` : "成功率待定";
    historyParts.push(`${label} ${success}／失敗 ${Number(metric.failure_count) || 0}／無事件 ${Number(metric.no_event_count) || 0}`);
  });
  const healthMetricParts = [
    Number.isFinite(Number(observation.success_rate)) ? `成功率 ${Number(observation.success_rate).toFixed(1)}%` : "",
    Number.isFinite(Number(observation.no_event_count)) ? `無事件 ${Number(observation.no_event_count)} 個` : "",
    Number.isFinite(Number(observation.failure_count)) ? `掃描失敗 ${Number(observation.failure_count)} 個` : "",
    Number.isFinite(Number(observation.crosscheck_rate)) ? `核對率 ${Number(observation.crosscheck_rate).toFixed(1)}%` : "",
    Number.isFinite(Number(observation.stale_count)) ? `快取 ${Number(observation.stale_count)} 筆` : "",
    historyParts.length ? `歷史：${historyParts.join("；")}` : "",
  ].filter(Boolean).join("｜");
  event.textContent = `${scan.label || "事件掃描"}｜${scanStateLabel}${scan.detail ? `｜${scan.detail}` : ""}${healthMetricParts ? `｜${healthMetricParts}` : ""}`;
  event.dataset.status = scan.status || "partial";
  list.innerHTML = health.sources.map((source) => {
    // Use the canonical semantic state for both the aggregate count and the
    // row label; legacy state/status fields are only compatibility fallbacks.
    const state = source.semantic_state || source.state || source.status;
    // Keep the legacy status spelling for older snapshots and source-health
    // fixtures (source.status === "warming" ? "建檔中").
    const normalizedState = String(state || "").toLowerCase();
    const status = state === "healthy" ? "正常" : ["no_event", "no_events", "no_new_content", "empty", "none"].includes(normalizedState) ? "無事件" : ["not_checked", "not_scanned", "not_checked_yet"].includes(normalizedState) ? "尚未檢查" : state === "warming" ? "建檔中" : state === "pending_confirmation" || state === "pending" ? "待核對" : state === "configuration_missing" || state === "configuration_required" ? "需設定" : state === "optional_degraded" ? "選配降級" : state === "degraded_with_fallback" || state === "fallback_active" ? "備援可用" : state === "secondary_unavailable" ? "第二來源不可用" : state === "stale" ? "使用快取" : ["failed", "scan_failed", "failure", "error", "provider_failed", "parse_failed"].includes(normalizedState) ? "掃描失敗" : "資料缺口";
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
    const quality = [
      Number.isFinite(Number(source.success_rate)) ? `成功率 ${Number(source.success_rate).toFixed(1)}%` : "",
      Number.isFinite(Number(source.consecutive_failures)) ? `連續失敗 ${Number(source.consecutive_failures)} 次` : "",
      Number.isFinite(Number(source.crosscheck_rate)) ? `核對率 ${Number(source.crosscheck_rate).toFixed(1)}%` : "",
    ].filter(Boolean).join("｜");
    const external = source.key === "external_financialjuice" && source.observability && typeof source.observability === "object"
      ? [
        source.observability.last_received_at ? `最近收到 ${traceTime(source.observability.last_received_at)}` : "",
        Number.isFinite(Number(source.observability.qualifying_item_count)) ? `>=8 ${Number(source.observability.qualifying_item_count)} 筆` : "",
        Number.isFinite(Number(source.observability.pending_cluster_count)) ? `待核對群組 ${Number(source.observability.pending_cluster_count)}` : "",
        Number.isFinite(Number(source.observability.parser_error_count)) ? `解析失敗 ${Number(source.observability.parser_error_count)} 筆` : "",
        source.observability.last_notification_decision === "eligible" ? "通知資格：已具備" : source.observability.last_notification_decision === "pending_confirmation" ? "通知資格：待核對" : "",
      ].filter(Boolean).join("｜") : "";
    const creator = String(source.key || "").startsWith("creator_") && source.observability && typeof source.observability === "object"
      ? [
        Number.isFinite(Number(source.observability.observations)) ? `觀測 ${Number(source.observability.observations)} 筆` : "",
        source.observability.last_parsed_at ? `最近解析 ${traceTime(source.observability.last_parsed_at)}` : "",
        Number.isFinite(Number(source.observability.parser_error_count)) ? `解析失敗 ${Number(source.observability.parser_error_count)} 筆` : "",
        source.observability.last_delivery_at ? `最近送達 ${traceTime(source.observability.last_delivery_at)}` : "",
      ].filter(Boolean).join("｜") : "";
    const lineage = source.observability && typeof source.observability === "object"
      ? [
        source.observability.morning_batch_state ? `晨批 ${source.observability.morning_batch_state}` : "",
        source.observability.morning_batch_key ? `批次 ${source.observability.morning_batch_key}` : "",
        Number.isFinite(Number(source.observability.daily_coverage_count)) ? `日覆蓋 ${Number(source.observability.daily_coverage_count)} 筆` : "",
        source.observability.last_snapshot_id ? `快照 ${source.observability.last_snapshot_id}` : "",
        source.observability.last_observation_id ? `觀測 ${source.observability.last_observation_id}` : "",
        source.observability.last_telegram_delivery_status ? `Telegram ${source.observability.last_telegram_delivery_status}` : "",
        source.observability.last_importance_gte_8_at ? `>=8 最近 ${traceTime(source.observability.last_importance_gte_8_at)}` : "",
      ].filter(Boolean).join("｜") : "";
    const detail = [issue, candidateNote, provenance, quality, freshness.join("｜"), external, creator, lineage].filter(Boolean).join("｜");
    return `<li><span><b>${escapeHtml(source.label || source.key)}</b><small>${escapeHtml(detail)}</small></span><em class="source-status ${escapeHtml(state || "partial")}">${status}</em></li>`;
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
  const intelligenceContent = document.getElementById("briefing-intelligence-content");
  const context = report.intelligence;
  if (intelligenceContent) {
    if (!context || typeof context !== "object") {
      if (intelligenceContent) intelligenceContent.innerHTML = '<p class="empty">本輪市場情報證據暫時無法取得。</p>';
    } else {
      const regime = context.market_regime || {};
      const contagion = context.contagion || {};
      const gate = context.advice_gate_detail || {};
      const surprise = context.macro_surprise || {};
      const impactPaths = Array.isArray(context.market_impact_graph?.paths) ? context.market_impact_graph.paths : [];
      const factors = Object.entries(regime.factor_contributions || {})
        .map(([name, value]) => `${name} ${Number(value).toFixed(2)}`)
        .join("、") || "目前沒有足夠因子";
      const signals = (contagion.confirmed_signals || []).join("、") || "尚未確認跨資產同步";
      const blocking = (gate.blocking_reasons || []).join("、") || "研究閘門已通過（仍不構成交易指令）";
      const scenarios = (context.stress_scenarios || []).slice(0, 3).map((item) => {
        const effect = Number(item.estimated_weighted_effect || 0).toFixed(2);
        return `<li><b>${escapeHtml(item.scenario || "情境")}</b><span>非預測情境｜加權影響 ${escapeHtml(effect)}%</span></li>`;
      }).join("");
      const pathText = impactPaths.length
        ? impactPaths.slice(0, 3).map((path) => `${path.key || "傳導路徑"}｜${path.market_sync ? "已有市場同步" : "等待市場證據"}`).join("；")
        : "尚無符合事件的傳導路徑";
      const externalRisk = context.external_event_risk || {};
      const unifiedEvents = Array.isArray(externalRisk.unified_events) ? externalRisk.unified_events : [];
      const unifiedText = unifiedEvents.slice(0, 3).map((item) => {
        const state = item.lifecycle_state || "pending_confirmation";
        const reasons = Array.isArray(item.pending_reasons) && item.pending_reasons.length
          ? item.pending_reasons.join("、")
          : "證據已完成核對";
        return `${state}｜${reasons}`;
      }).join("；") || "本輪沒有外部事件候選";
      const surpriseText = surprise.status === "insufficient_evidence"
        ? "總經驚喜：缺少預期值或實際值，證據不足"
        : `總經驚喜：${surprise.status}｜實際 ${surprise.actual ?? "—"}／預期 ${surprise.expected ?? "—"}`;
      const reaction = surprise.market_reaction || {};
      const reactionQuotes = Array.isArray(reaction.quotes) ? reaction.quotes : [];
      const reactionText = reaction.status === "observed_only"
        ? `已觀測 ${reactionQuotes.length} 筆價格反應，尚未確認方向`
        : "本輪沒有可用的事件後市場報價";
      if (intelligenceContent) intelligenceContent.innerHTML = `<p><b>市場狀態：</b>${escapeHtml(regime.regime || "資料不足")}｜分數 ${escapeHtml(String(regime.score ?? "—"))}</p><p><b>因子：</b>${escapeHtml(factors)}</p><p><b>跨資產核對：</b>${escapeHtml(contagion.status || "資料不足")}｜${escapeHtml(signals)}</p><p><b>傳導路徑：</b>${escapeHtml(pathText)}</p><p><b>外部事件證據：</b>${escapeHtml(unifiedText)}</p><p><b>${escapeHtml(surpriseText)}</b>（不單獨推定市場方向）</p><p><b>市場第一反應：</b>${escapeHtml(reactionText)}｜${escapeHtml(reaction.reason || "")}</p><p><b>建議閘門：</b>${escapeHtml(context.advice_gate || "observation_only")}｜${escapeHtml(blocking)}</p>${scenarios ? `<ul class="briefing-stress-list"><li class="briefing-stress-heading">壓力情境（非預測）</li>${scenarios}</ul>` : ""}<small>資料不足時維持觀察，不產生買進／賣出指令。</small>`;
    }
  }
  const paperContent = document.getElementById("briefing-paper-content");
  if (paperContent) {
    const tracker = report.paper_portfolio;
    if (!tracker || typeof tracker !== "object") {
      paperContent.innerHTML = '<p class="empty">本輪紙上研究追蹤資料暫時無法取得。</p>';
    } else {
      const records = Array.isArray(tracker.records) ? tracker.records : [];
      const tracking = tracker.tracking || {};
      const state = tracker.state === "available" ? "可追蹤" : "僅觀察／等待有效回測與報價";
      const rows = records.slice(0, 5).map((item) => {
        const horizons = item.horizons || {};
        return `<li><b>${escapeHtml(item.ticker || "—")}</b>｜${escapeHtml(item.strategy || "研究觀察")}｜5日 ${escapeHtml(String(horizons["5d"] ?? "待完成"))}%｜20日 ${escapeHtml(String(horizons["20d"] ?? "待完成"))}%｜60日 ${escapeHtml(String(horizons["60d"] ?? "待完成"))}%</li>`;
      }).join("");
      paperContent.innerHTML = `<p><b>狀態：</b>${escapeHtml(state)}</p><p><b>追蹤進度：</b>${escapeHtml(String(tracking.completed_horizon_count ?? 0))} 個期限已完成</p>${rows ? `<ul>${rows}</ul>` : '<p class="empty">目前沒有符合紙上追蹤條件的研究候選。</p>'}<small>僅為公開資料的紙上研究觀察，不代表實際持倉或交易績效。</small>`;
    }
  }
  const container = document.getElementById("briefing-observations");
  if (!container) return;
  if (!observations.length) { container.innerHTML = '<p class="empty">本次定時報資料暫時無法取得</p>'; return; }
  container.innerHTML = observations.map((item) => `<article class="briefing-observation"><h4>${escapeHtml(item.title || "公開市場觀察")}</h4><p><b>事件：</b>${escapeHtml(item.event || "公開資料更新中。")}</p><p><b>為何重要：</b>${escapeHtml(item.importance || "持續核對公開資料。")}</p><p><b>可能連動：</b>${escapeHtml(item.market_impact || "尚無足夠公開資料判定連動。")}</p><p><b>股市觀察：</b>${escapeHtml(item.watch || "觀察後續公開市場報價。")}</p>${item.source_note ? `<small class="briefing-source">${escapeHtml(item.source_note)}</small>` : ""}</article>`).join("");
};

const renderExternalIntelligence = (snapshot) => {
  const content = document.getElementById("external-intelligence-content");
  if (!content) return;
  const observations = Array.isArray(snapshot?.external_observations)
    ? snapshot.external_observations
    : Array.isArray(snapshot?.briefing?.external_observations)
      ? snapshot.briefing.external_observations : [];
  const decisions = Array.isArray(snapshot?.financialjuice_priority_decisions)
    ? snapshot.financialjuice_priority_decisions : [];
  const priorityEvents = Array.isArray(snapshot?.financialjuice_priority_events)
    ? snapshot.financialjuice_priority_events : [];
  const rowKey = (item) => String(item?.observation_id || item?.item_id || item?.notification_id || "").trim();
  const decisionByKey = new Map(decisions.map((item) => [rowKey(item), item]).filter(([key]) => key));
  const priorityLabels = {
    eligible: "供應商優先：可通知",
    not_eligible: "供應商優先：未達 8/10",
    already_cluster_notified: "供應商優先：同事件已通知",
  };
  const rows = observations.map((item) => ({
    ...item,
    _priorityDecision: decisionByKey.get(rowKey(item)) || null,
  }));
  const seen = new Set(rows.map(rowKey).filter(Boolean));
  // Keep release-projected eligible events visible even when the raw source
  // observation was compacted out of the public snapshot.  This is still the
  // same canonical event lane, not a second notification pipeline.
  for (const event of priorityEvents) {
    const key = rowKey(event);
    if (!key || seen.has(key)) continue;
    rows.push({ ...event, _priorityDecision: { notification_status: "eligible" } });
    seen.add(key);
  }
  if (!rows.length) {
    content.innerHTML = '<p class="empty">本輪沒有可公開顯示的外部快訊；來源無事件與掃描失敗分開記錄。</p>';
    return;
  }
  content.innerHTML = rows.slice(0, 5).map((item) => {
    const source = escapeHtml(item.source || item.content_origin || "外部來源");
    // Consume the canonical semantic projection.  The remaining fallbacks
    // are only for legacy snapshots; parsing and semantic selection stay
    // upstream in the release-bound event projection.
    const semanticEvent = item.event || item.chinese_translation || item.title || item.headline || item.original_headline || "外部市場觀察";
    const semanticWhy = item.why_important || item.ai_commentary || item.summary || "目前尚無額外重要性說明，等待後續公開資料核對。";
    const semanticLinkage = item.possible_linkage || item.possible_impact || "尚無足夠公開資料判定連動。";
    const semanticObservation = item.stock_observation || item.watch || "等待官方後續確認，並觀察相關市場是否同步反應。";
    const title = escapeHtml(item.title || item.headline || item.original_headline || semanticEvent);
    const semanticHtml = `<p><b>事件：</b>${escapeHtml(semanticEvent)}</p><p><b>為何重要：</b>${escapeHtml(semanticWhy)}</p><p><b>可能連動：</b>${escapeHtml(semanticLinkage)}</p><p><b>股市觀察：</b>${escapeHtml(semanticObservation)}</p>`;
    const official = item.official_confirmed === true;
    const synced = item.market_sync_confirmed === true;
    const state = official && synced ? "已核對" : official ? "等待市場同步" : synced ? "等待官方核對" : "等待官方核對／市場同步";
    const priority = item._priorityDecision;
    const priorityStatus = String(priority?.notification_status || "").trim();
    const priorityText = priorityStatus
      ? `${priorityLabels[priorityStatus] || "供應商優先：待核對"}${priority?.notification_reason ? `｜${escapeHtml(priority.notification_reason)}` : ""}`
      : "供應商優先：尚未產生決策";
    const isFinancialJuice = String(item.source_key || item.source || item.content_origin || "").toLowerCase() === "financialjuice";
    const vendorImportance = item.vendor_importance ?? priority?.vendor_importance;
    const prstkRisk = item.prstk_risk?.prstk_risk_level || item.risk_level || "R2";
    const evidenceText = official && synced
      ? "官方與市場同步已核對"
      : official ? "等待市場同步"
        : synced ? "等待官方核對"
          : "等待官方核對／市場同步";
    const evidence = isFinancialJuice
      ? `<small class="external-evidence">來源重要度：${escapeHtml(vendorImportance === null || vendorImportance === undefined || vendorImportance === "" ? "待核對" : `${vendorImportance}/10`)}（不等同 PRStK 風險）｜PRStK Risk：${escapeHtml(prstkRisk)}｜${escapeHtml(evidenceText)}</small>`
      : "";
    const lineage = isFinancialJuice
      ? [
          item.release_id ? `release ${item.release_id}` : "",
          item.snapshot_id ? `snapshot ${item.snapshot_id}` : "",
          item.observation_id ? `observation ${item.observation_id}` : "",
        ].filter(Boolean).join("｜")
      : "";
    const lineageText = lineage ? `<small class="external-lineage">發布鏈：${escapeHtml(lineage)}</small>` : "";
    const timing = isFinancialJuice && (item.published_at || item.fetched_at)
      ? `<small class="external-timing">資料時間：${escapeHtml(traceTime(item.published_at || item.fetched_at))}</small>`
      : "";
    const url = String(item.source_url || "").trim();
    const link = /^https:\/\//.test(url) ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">公開來源</a>` : "";
    return `<article class="external-insight"><h4>${title}</h4><small>${source}｜${state}</small><small>${priorityText}</small>${evidence}${lineageText}${timing}${semanticHtml}${link}</article>`;
  }).join("");
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
    // Keep the six-condition evidence in the release JSON for audit and
    // explainability, but project the public card to one compact strategy
    // label.  Rendering every internal rule as a chip makes the investor view
    // unreadable and leaks implementation taxonomy.
    return ["璞玉價值"];
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

// Research cards remain concise; detailed explainability is available in the
// backend/Creator report and is intentionally not rendered in the public list.
const researchExplainability = () => "";

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
    return `<li class="research-item"><div class="research-item-top"><div class="research-identity"><b class="research-ticker">${escapeHtml(item.ticker)}</b><span class="research-company">${escapeHtml(item.name || item.ticker)}</span></div><span class="research-price ${state}"><span class="research-price-label">收盤參考</span><strong>${escapeHtml(price)}</strong><small>${escapeHtml(change)}</small></span></div><div class="research-strategies">${tags}</div><div class="research-item-bottom"><span class="research-score-label">${escapeHtml(score.label)}</span><strong class="research-score">${escapeHtml(score.value)}</strong></div>${researchExplainability(item)}</li>`;
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
    const explanation = researchExplainability(item);
    return `<li class="research-item"><div class="research-item-top"><div class="research-identity"><b class="research-ticker">${escapeHtml(item.ticker)}</b><span class="research-company">${escapeHtml(item.name || item.ticker)}</span></div><span class="research-price ${state}"><span class="research-price-label">收盤參考</span><strong>${escapeHtml(price)}</strong><small>${escapeHtml(change)}</small></span></div><div class="research-strategies">${tags}</div><div class="research-item-bottom"><span class="research-score-label">${escapeHtml(score.label)}</span><strong class="research-score">${escapeHtml(score.value)}${item.condition_count ? ` · ${escapeHtml(item.condition_count)}` : ""}</strong></div>${explanation}</li>`;
  }).join("");
  container.innerHTML = `${visibleFormal.length ? `<li class="research-subheading">正式候選（至少 5/6，最多 5 檔）</li>${renderGroup("正式候選", visibleFormal)}` : ""}${visibleObservation.length ? `<li class="research-subheading">觀察名單（3/6 或 4/6，補足至 5 檔）</li>${renderGroup("觀察名單", visibleObservation)}` : ""}`;
};

let activeResearchMarket = "taiwan";

const renderResearch = (snapshot) => {
  const report = snapshot.research_report || {};
  const candidates = report.candidates || [];
  const generatedAt = report.generated_at ? ` 掃描時間：${new Date(report.generated_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}` : "";
  setText("research-tag", activeResearchMarket === "taiwan" ? "台股" : "美股");
  const staleResearch = report.availability === "expired"
    || report.research_freshness === "stale_fallback"
    || report.fallback_used === true
    || report.scan_state === "failed";
  const lastSuccessfulAt = report.last_successful_generated_at || report.fallback_from_generated_at || report.generated_at;
  const staleNotice = staleResearch
    ? `資料降級｜沿用上一個成功版本${lastSuccessfulAt ? `（${new Date(lastSuccessfulAt).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}）` : ""}`
    : null;
  const backtestState = window.releaseManifest?.backtest_publication_state;
  const backtestNotice = backtestState && backtestState !== "ready"
    ? "正式回測尚未發布；候選僅供研究觀察，不提供操作判斷。"
    : "";
  setText("research-notice", staleNotice || backtestNotice || generatedAt.trim() || "掃描時間暫時無法取得");
  const sourceFor = (strategy) => (report.sources || []).find((item) => item.market === activeResearchMarket && item.strategy === strategy) || {};
  const sourceBlocked = (strategy) => {
    const source = sourceFor(strategy);
    const partialCandidatesAllowed = source.partial_candidates_allowed === true;
    const buildingWithoutPartialRows = source.status === "建檔中" || source.scan_state === "building";
    const sourceHasCandidates = marketCandidates.some((item) => item.strategy === strategy);
    return (!sourceHasCandidates && (source.status === "掃描失敗" || source.status === "資料暫時無法取得" || source.scan_state === "failed"))
      || (buildingWithoutPartialRows && !partialCandidatesAllowed && !sourceHasCandidates);
  };
  const marketCandidates = candidates.filter((item) => item.market === activeResearchMarket);
  const sourceMessage = (strategy, fallback) => {
    const source = sourceFor(strategy);
    if (staleNotice) return staleNotice;
    if (source.status === "掃描失敗" || source.scan_state === "failed") {
      const evidence = source.failure_evidence || {};
      const attempts = Number.isFinite(Number(evidence.attempts)) ? `（已重試 ${Number(evidence.attempts)} 次）` : "";
      return `本輪掃描失敗${attempts}；顯示上一個成功版本候選，等待重試。`;
    }
    if (source.status === "資料暫時無法取得") return "本輪資料暫時無法取得；顯示上一個成功版本候選。";
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

const renderCreatorInsights = (creatorRelease) => {
  const panel = document.getElementById("creator-intelligence");
  const content = document.getElementById("creator-intelligence-content");
  const status = document.getElementById("creator-status");
  if (!panel || !content) return;
  panel.hidden = false;
  content.replaceChildren();
  if (status) status.textContent = "資料可用";
  if (!creatorRelease || typeof creatorRelease !== "object") {
    if (status) status.textContent = "尚未發布";
    content.innerHTML = '<p class="empty">本輪尚未發布財經內容洞察；不代表沒有內容，請等待下一個已核對版本。</p>';
    return;
  }
  if (creatorRelease.status !== "ready") {
    if (status) status.textContent = "來源待核對";
    const reason = Array.isArray(creatorRelease.validation_errors) && creatorRelease.validation_errors.length
      ? creatorRelease.validation_errors.slice(0, 3).join("、")
      : "本輪來源未完成驗證";
    content.innerHTML = `<p class="empty">財經內容洞察目前不可用：${escapeHtml(reason)}。不影響核心市場資料。</p>`;
    return;
  }
  const consensus = creatorRelease.creator_consensus;
  if (consensus && typeof consensus === "object") {
    const stateLabels = {
      aligned: "多來源方向一致（僅描述觀點）",
      mixed: "多來源觀點分歧",
      insufficient_sources: "來源不足，暫不形成共識",
      pending_verification: "有內容但缺少可比的明確立場",
      stale: "內容過期，暫不作為目前觀察",
    };
    const evidenceLabels = {
      aligned: "市場資料可比對",
      partially_aligned: "部分市場資料可比對",
      stale: "市場資料過期",
      insufficient_evidence: "市場證據不足",
    };
    const topicStateLabels = {
      aligned: "一致",
      mixed: "分歧",
      insufficient_sources: "來源不足",
      pending_verification: "待核對",
    };
    const topics = Array.isArray(consensus.topic_consensus) ? consensus.topic_consensus.slice(0, 6) : [];
    const topicText = topics.map((item) => `${escapeHtml(item.topic || "未命名主題")}：${escapeHtml(topicStateLabels[item.consensus_state] || "待核對")}`).join("、");
    const divergent = Array.isArray(consensus.divergent_views) ? consensus.divergent_views : [];
    const risks = Array.isArray(consensus.common_risks) ? consensus.common_risks : [];
    const asOf = consensus.as_of ? new Date(consensus.as_of).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "尚無時間資料";
    content.insertAdjacentHTML("beforeend", `<article class="creator-consensus"><h4>多來源內容共識</h4><p><b>狀態：</b>${escapeHtml(stateLabels[consensus.consensus_state] || "待核對")}</p><p><b>涵蓋：</b>${escapeHtml(consensus.coverage || "0/0")}｜<b>主題：</b>${topicText || "尚無可比主題"}</p><p><b>觀點分歧：</b>${divergent.length ? divergent.map((item) => escapeHtml(item.topic || "未命名主題")).join("、") : "未發現明確分歧"}</p><p><b>共同風險：</b>${risks.length ? risks.map(escapeHtml).join("、") : "尚無可交集風險標籤"}</p><small>市場證據：${escapeHtml(evidenceLabels[consensus.evidence_alignment] || "尚未核對")}｜資料時間：${escapeHtml(asOf)}</small><small>此區為公開內容觀點整理，不是事件核對，也不是投資訊號。</small></article>`);
  }
  let insights = Array.isArray(creatorRelease.insights) ? creatorRelease.insights : [];
  if (!insights.length && creatorRelease.creators && typeof creatorRelease.creators === "object") {
    insights = Object.values(creatorRelease.creators).flatMap((creator) => {
      const episodes = Array.isArray(creator?.episodes) ? creator.episodes : [];
      return episodes.map((episode) => ({ ...episode, creator_name: creator.creator_name || creator.creator_id }));
    });
  }
  if (!insights.length) {
    content.innerHTML = '<p class="empty">本輪沒有可公開顯示的內容洞察。</p>';
    return;
  }
  content.innerHTML = insights.slice(0, 5).map((item) => {
    const title = escapeHtml(item.episode_title || item.episode_key || "Creator Insight");
    const verificationLabels = {
      verified: "已核對", partially_verified: "部分核對", unverified: "待核對",
      contradicted: "與已知證據不一致", not_applicable: "不適用",
    };
    const verification = escapeHtml(verificationLabels[item.verification_state] || "待核對");
    const claims = Array.isArray(item.claims) ? item.claims.filter(Boolean).slice(0, 3) : [];
    const opinions = Array.isArray(item.opinions) ? item.opinions.filter(Boolean).slice(0, 2) : [];
    const claimsHtml = claims.map((value) => `<li>來源主張：${escapeHtml(value)}</li>`).join("");
    const views = opinions.map((value) => `<li>作者觀點：${escapeHtml(value)}</li>`).join("");
    const creator = escapeHtml(item.creator_name || "公開財經內容來源");
    const sourceUrl = String(item.source_url || "").trim();
    const sourceLink = /^https:\/\//.test(sourceUrl)
      ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">開啟公開來源</a>`
      : "";
    return `<article class="creator-insight"><h4>${title}</h4><small>${creator}｜核對狀態：${verification}</small><ul>${claimsHtml}${views}</ul>${sourceLink}</article>`;
  }).join("");
};

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
  renderAlertCard(snapshot.events, snapshot.generated_at, externalAlert, snapshot.indices || [], snapshot.intelligence?.external_event_risk);
  renderEvents(snapshot.events);
  renderSourceHealth(snapshot.source_health, snapshot);
  renderBriefing(snapshot.briefing, snapshot.generated_at);
  renderExternalIntelligence(snapshot);
  renderResearch(snapshot);
  const newsRegistry = snapshot.news?.provider_registry || [];
  const newsMarkets = snapshot.news?.markets || snapshot.news?.intelligence || snapshot.news;
  const newsHealth = Array.isArray(snapshot.news?.source_health) ? snapshot.news.source_health : [];
  const newsHealthFor = (market) => {
    const aggregate = newsHealth.find((item) => item?.key === `news_${market}`) || {};
    const intelligence = newsMarkets?.[market] || {};
    return {
      ...aggregate,
      collection_state: intelligence.collection_state || aggregate.collection_state,
      source_failure_count: intelligence.source_failure_count ?? aggregate.source_failure_count,
    };
  };
  renderNewsList("taiwan-news", newsMarkets?.taiwan?.stories || snapshot.news?.taiwan, newsRegistry, newsHealthFor("taiwan"), newsMarkets?.taiwan);
  renderNewsList("us-news", newsMarkets?.us?.stories || snapshot.news?.us, newsRegistry, newsHealthFor("us"), newsMarkets?.us);
};

// Telegram buttons carry the release and alert identity.  Resolve that
// identity only after the manifest/hash boundary has succeeded; never fall
// back to an unrelated current event when a deep link is stale or unknown.
const applyDeepLink = (snapshot) => {
  const params = new URLSearchParams(window.location.search);
  const requestedRelease = String(params.get("release") || "").trim();
  const requestedAlert = String(params.get("alert") || "").trim();
  const requestedSnapshot = String(params.get("snapshot") || "").trim();
  const requestedObservation = String(params.get("observation") || "").trim();
  const view = String(params.get("view") || "").trim().toLowerCase();
  if (!requestedRelease && !requestedAlert && !view) return;
  const manifestRelease = String(window.releaseManifest?.release_id || "");
  if (!requestedRelease || requestedRelease !== manifestRelease) {
    setReleaseHealth("該訊息版本已歸檔或不可用；目前顯示最新安全版本。", "error");
    setText("market-focus", "訊息版本與目前公開 release 不一致，暫不載入其他事件。");
    return;
  }
  const knownSnapshots = [
    window.releaseManifest?.market_snapshot_id,
    window.releaseManifest?.research_snapshot_id,
    window.releaseManifest?.event_snapshot_id,
  ].filter(Boolean).map(String);
  if (requestedSnapshot && knownSnapshots.length && !knownSnapshots.includes(requestedSnapshot)) {
    setReleaseHealth("該訊息快照不屬於目前 release；暫不載入其他資料。", "error");
    setText("market-focus", "訊息快照與公開版本不一致，暫不替換為其他事件。");
    return;
  }
  const sectionByView = {
    event: "risk", resolved: "risk", market: "market", briefing: "briefing-report",
    research: "research", "source-health": "source-health",
  };
  const targetId = sectionByView[view] || (requestedAlert ? "risk" : "");
  const target = targetId ? document.getElementById(targetId) : null;
  if (target?.tagName === "DETAILS") target.open = true;
  if (requestedAlert) {
    const items = Array.isArray(snapshot.events?.items) ? snapshot.events.items : [];
    // Delivery producers use the durable event-cluster/notification identity,
    // while older market artifacts may expose only `id` or `canonical_key`.
    // Accept every contract identity that can be emitted in a deep link, but
    // still resolve only against this release's event items.
    const event = items.find((item) => [
      item.alert_id,
      item.event_id,
      item.id,
      item.canonical_key,
      item.event_cluster_key,
      item.event_key,
      item.notification_id,
      item.item_id,
      item.story_id,
    ].filter(Boolean).some((value) => String(value) === requestedAlert));
    if (!event) {
      setReleaseHealth("該訊息已歸檔或不可用；未顯示其他事件。", "error");
      setText("market-focus", "找不到此 alert 的同一 release 證據，暫不替換為其他事件。");
      return;
    }
    if (requestedSnapshot && event.snapshot_id && String(event.snapshot_id) !== requestedSnapshot) {
      setReleaseHealth("該訊息快照與事件不一致；暫不載入其他事件。", "error");
      setText("market-focus", "事件與快照核對失敗，暫不替換為其他事件。");
      return;
    }
    if (requestedObservation && event.observation_id && String(event.observation_id) !== requestedObservation) {
      setReleaseHealth("該訊息觀測 ID 與事件不一致；暫不載入其他事件。", "error");
      setText("market-focus", "事件與來源觀測核對失敗，暫不替換為其他事件。");
      return;
    }
    renderAlertCard({ items: [event] }, snapshot.generated_at, null, snapshot.indices || []);
  }
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
};

// The manifest is the release boundary.  Fetching an artifact directly could
// otherwise combine a new market file with an older research/event file when
// GitHub Pages or Telegram's WebView serves different cache generations.
const cacheBust = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const fetchResponseWithRetry = (url, attempt = 0) => fetch(`${url}${url.includes("?") ? "&" : "?"}v=${cacheBust()}`, {
  cache: "no-store",
  headers: { "Cache-Control": "no-cache" },
}).then((response) => {
  if (response.ok) return response;
  throw new Error(`HTTP ${response.status}`);
}).catch((error) => {
  if (attempt < 2) return sleep(250 * (attempt + 1)).then(() => fetchResponseWithRetry(url, attempt + 1));
  throw new Error(`artifact unavailable: ${url} (${error.message})`);
});

const fetchJson = (url) => fetchResponseWithRetry(url).then((response) => response.json());

const sha256Hex = async (text) => {
  if (!window.crypto?.subtle) throw new Error("integrity verification unavailable");
  const bytes = new TextEncoder().encode(text);
  const digest = await window.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
};

const LAST_GOOD_RELEASE_KEY = "prstk.lastGoodRelease.v1";

const setReleaseHealth = (message, kind = "degraded") => {
  const node = document.getElementById("release-health");
  if (!node) return;
  node.hidden = !message;
  node.textContent = message || "";
  node.dataset.state = kind;
};

const saveLastGoodRelease = (manifest, artifactTexts) => {
  try {
    localStorage.setItem(LAST_GOOD_RELEASE_KEY, JSON.stringify({
      manifest,
      artifactTexts,
      saved_at: new Date().toISOString(),
    }));
  } catch (_error) {
    // Quota/private mode is non-fatal; the current network release is still usable.
  }
};

const readLastGoodRelease = async () => {
  try {
    const saved = JSON.parse(localStorage.getItem(LAST_GOOD_RELEASE_KEY) || "null");
    if (!saved?.manifest || saved.manifest.status !== "ready" || !saved.manifest.release_id) return null;
    if (!saved.artifactTexts?.["market.json"]) return null;
    for (const [name, expectedHash] of Object.entries(saved.manifest.artifact_hashes || {})) {
      const text = saved.artifactTexts[name];
      if (typeof text !== "string" || await sha256Hex(text) !== String(expectedHash)) return null;
    }
    const snapshot = JSON.parse(saved.artifactTexts["market.json"]);
    if (String(snapshot.snapshot_id || "") !== String(saved.manifest.market_snapshot_id || "")) return null;
    const research = saved.artifactTexts["research-report.json"] ? JSON.parse(saved.artifactTexts["research-report.json"]) : null;
    const events = saved.artifactTexts["event-ledger.json"] ? JSON.parse(saved.artifactTexts["event-ledger.json"]) : null;
    if (saved.manifest.research_snapshot_id && String(research?.snapshot_id || "") !== String(saved.manifest.research_snapshot_id)) return null;
    if (research && typeof research === "object") snapshot.research_report = research;
    if (saved.manifest.event_snapshot_id && String(events?.snapshot_id || "") !== String(saved.manifest.event_snapshot_id)) return null;
    const newsText = saved.artifactTexts["news.json"];
    if (newsText) {
      const news = JSON.parse(newsText);
      if (String(news.market_snapshot_id || "") !== String(saved.manifest.market_snapshot_id || "")) return null;
      if (saved.manifest.news_snapshot_id && String(news.snapshot_id || "") !== String(saved.manifest.news_snapshot_id)) return null;
      snapshot.news = news;
    }
    const creatorText = saved.artifactTexts["creator-release.json"];
    if (creatorText) {
      const creator = JSON.parse(creatorText);
      if (String(creator.parent_release_id || "") !== String(saved.manifest.release_id || "")) return null;
      if (String(creator.market_snapshot_id || "") !== String(saved.manifest.market_snapshot_id || "")) return null;
      if (String(creator.event_snapshot_id || "") !== String(saved.manifest.event_snapshot_id || "")) return null;
      if (saved.manifest.creator_release_id && String(creator.release_id || "") !== String(saved.manifest.creator_release_id)) return null;
      snapshot.creator_release = creator;
    }
    const creatorPublicText = saved.artifactTexts["creator-insights.json"];
    if (creatorPublicText) {
      const creatorPublic = JSON.parse(creatorPublicText);
      if (String(creatorPublic.parent_release_id || "") !== String(saved.manifest.release_id || "")) return null;
      if (String(creatorPublic.market_snapshot_id || "") !== String(saved.manifest.market_snapshot_id || "")) return null;
      if (String(creatorPublic.research_snapshot_id || "") !== String(saved.manifest.research_snapshot_id || "")) return null;
      if (String(creatorPublic.event_snapshot_id || "") !== String(saved.manifest.event_snapshot_id || "")) return null;
      if (saved.manifest.creator_snapshot_id && String(creatorPublic.snapshot_id || "") !== String(saved.manifest.creator_snapshot_id)) return null;
      snapshot.creator_public_artifact = creatorPublic;
    }
    return { ...saved, snapshot };
  } catch (_error) {
    return null;
  }
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
    const response = await fetchResponseWithRetry(`data/${relativePath.replace(/^data\//, "")}`);
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
  const researchText = artifactTexts["research-report.json"];
  if (manifest.research_snapshot_id && researchText) {
    const research = JSON.parse(researchText);
    if (String(research.snapshot_id || "") !== String(manifest.research_snapshot_id)) {
      throw new Error("research snapshot does not match release");
    }
    snapshot.research_report = research;
  } else if (researchText) {
    snapshot.research_report = JSON.parse(researchText);
  }
  const eventText = artifactTexts["event-ledger.json"];
  if (manifest.event_snapshot_id && eventText) {
    const events = JSON.parse(eventText);
    if (String(events.snapshot_id || "") !== String(manifest.event_snapshot_id)) {
      throw new Error("event snapshot does not match release");
    }
  }
  const newsText = artifactTexts["news.json"];
  if (newsText) {
    const news = JSON.parse(newsText);
    if (String(news.market_snapshot_id || "") !== String(manifest.market_snapshot_id || "")) {
      throw new Error("news market snapshot does not match release");
    }
    if (manifest.news_snapshot_id && String(news.snapshot_id || "") !== String(manifest.news_snapshot_id)) {
      throw new Error("news snapshot does not match release");
    }
    snapshot.news = news;
  }
  const creatorText = artifactTexts["creator-release.json"];
  if (creatorText) {
    const creator = JSON.parse(creatorText);
    if (String(creator.parent_release_id || "") !== String(manifest.release_id || "")) {
      throw new Error("creator release parent does not match release");
    }
    if (String(creator.market_snapshot_id || "") !== String(manifest.market_snapshot_id || "")) {
      throw new Error("creator release market snapshot does not match release");
    }
    if (String(creator.event_snapshot_id || "") !== String(manifest.event_snapshot_id || "")) {
      throw new Error("creator release event snapshot does not match release");
    }
    if (manifest.creator_release_id && String(creator.release_id || "") !== String(manifest.creator_release_id)) {
      throw new Error("creator release id does not match release manifest");
    }
    snapshot.creator_release = creator;
  }
  const creatorPublicText = artifactTexts["creator-insights.json"];
  if (creatorPublicText) {
    const creatorPublic = JSON.parse(creatorPublicText);
    if (String(creatorPublic.parent_release_id || "") !== String(manifest.release_id || "")) {
      throw new Error("creator public artifact parent does not match release");
    }
    if (String(creatorPublic.market_snapshot_id || "") !== String(manifest.market_snapshot_id || "")) {
      throw new Error("creator public artifact market snapshot does not match release");
    }
    if (String(creatorPublic.research_snapshot_id || "") !== String(manifest.research_snapshot_id || "")) {
      throw new Error("creator public artifact research snapshot does not match release");
    }
    if (String(creatorPublic.event_snapshot_id || "") !== String(manifest.event_snapshot_id || "")) {
      throw new Error("creator public artifact event snapshot does not match release");
    }
    if (manifest.creator_snapshot_id && String(creatorPublic.snapshot_id || "") !== String(manifest.creator_snapshot_id)) {
      throw new Error("creator public snapshot does not match release manifest");
    }
    snapshot.creator_public_artifact = creatorPublic;
  }
  const healthText = artifactTexts["source-health.json"];
  if (healthText) {
    const healthEnvelope = JSON.parse(healthText);
    if (String(healthEnvelope.market_snapshot_id || "") !== String(manifest.market_snapshot_id || "")) {
      throw new Error("source-health snapshot does not match release");
    }
    if (!healthEnvelope.source_health || !Array.isArray(healthEnvelope.source_health.sources)) {
      throw new Error("source-health artifact is invalid");
    }
    if (String(healthEnvelope.snapshot_id || "") !== `${manifest.market_snapshot_id}-health`) {
      throw new Error("source-health artifact binding is invalid");
    }
    snapshot.source_health = healthEnvelope.source_health;
  }
  window.releaseManifest = manifest;
  saveLastGoodRelease(manifest, artifactTexts);
  return snapshot;
};

loadPublishedRelease()
  .then((snapshot) => {
    render(snapshot);
    applyDeepLink(snapshot);
    // Healthy is the normal state; keep engineering metadata out of the hero.
    setReleaseHealth("", "ready");
  })
  .catch(async (error) => {
    const saved = await readLastGoodRelease();
    if (saved) {
      window.releaseManifest = saved.manifest;
      render(saved.snapshot);
      const savedAtValue = saved.manifest.created_at || saved.saved_at;
      const savedAt = savedAtValue ? new Date(savedAtValue).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }) : "未知";
      setText("data-status", "資料降級");
      setText("market-focus", "目前沿用上一個成功版本；本輪資料不可觸發高風險快訊。");
      setReleaseHealth(`資料降級｜最後成功 ${savedAt}｜來源失敗：${error.message}`, "degraded");
      return;
    }
    setText("data-status", "來源失敗");
    setText("market-focus", "本輪資料無法取得，暫不判斷市場風險。");
    setReleaseHealth(`發布資料不完整｜${error.message}｜目前不可觸發高風險快訊`, "error");
  });
