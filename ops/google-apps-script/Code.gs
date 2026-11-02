/**
 * Independent PRStK watchdog for the no-custom-domain deployment.
 * Configure the three Script Properties in the cutover guide, then run
 * setupPrstkWatchdog() once from the Apps Script editor.
 */
const PRSTK_HEARTBEAT_WORKFLOW = ".github/workflows/incident-ops-heartbeat.yml";
const PRSTK_REPOSITORY = "hanjhou2000716/prstklab-stk-detector";
const PRSTK_TRIGGER_HANDLER = "pollPrstkWatchdog";
const PRSTK_STATE_PROPERTY = "PRSTK_WATCHDOG_LAST_STATE";
const PRSTK_TRANSITION_PROPERTY = "PRSTK_WATCHDOG_TRANSITION_ID";
const PRSTK_TRANSITION_ID_PROPERTY = "PRSTK_WATCHDOG_LAST_TRANSITION_KEY";
const PRSTK_LAST_TELEGRAM_PROPERTY = "PRSTK_WATCHDOG_LAST_TELEGRAM_RESULT";
const PRSTK_WORKER_MAX_AGE_MS = 5 * 60 * 1000;
const PRSTK_GITHUB_MAX_AGE_MS = 20 * 60 * 1000;
const PRSTK_FUTURE_TOLERANCE_MS = 5 * 60 * 1000;

function setupPrstkWatchdog() {
  const props = PropertiesService.getScriptProperties();
  const base = props.getProperty("PRSTK_WATCHDOG_WORKER_BASE") || "";
  const botToken = props.getProperty("PRSTK_WATCHDOG_TELEGRAM_BOT_TOKEN") || "";
  const chatId = props.getProperty("PRSTK_WATCHDOG_TELEGRAM_CHAT_ID") || "";
  if (!/^https:\/\/[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*\.workers\.dev$/i.test(base)) {
    throw new Error("Set PRSTK_WATCHDOG_WORKER_BASE to the exact HTTPS workers.dev origin.");
  }
  if (!/^\d{6,15}:[A-Za-z0-9_-]{20,}$/.test(botToken) || !/^-?\d{4,20}$/.test(chatId)) {
    throw new Error("Set a dedicated Telegram bot token and the private administrator chat ID in Script Properties.");
  }
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === PRSTK_TRIGGER_HANDLER) ScriptApp.deleteTrigger(trigger);
  });
  ScriptApp.newTrigger(PRSTK_TRIGGER_HANDLER).timeBased().everyMinutes(5).create();
  return "PRStK independent watchdog installed with one five-minute trigger.";
}

function sendPrstkWatchdogTelegramTest() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty("PRSTK_WATCHDOG_TELEGRAM_BOT_TOKEN") || "";
  const chatId = props.getProperty("PRSTK_WATCHDOG_TELEGRAM_CHAT_ID") || "";
  if (!/^\d{6,15}:[A-Za-z0-9_-]{20,}$/.test(token) || !/^-?\d{4,20}$/.test(chatId)) {
    throw new Error("Set a dedicated Telegram bot token and the private administrator chat ID in Script Properties.");
  }
  const priorTest = props.getProperty("PRSTK_WATCHDOG_LAST_MANUAL_TEST") || "";
  if (priorTest.split("|")[1] === "delivery_unknown") {
    throw new Error("The prior Telegram test result is unknown. Check the private chat before starting another test.");
  }
  const testId = Utilities.getUuid();
  props.setProperty("PRSTK_WATCHDOG_LAST_MANUAL_TEST", testId + "|delivery_unknown");
  const response = UrlFetchApp.fetch("https://api.telegram.org/bot" + token + "/sendMessage", {
    method: "post", muteHttpExceptions: true, followRedirects: false,
    contentType: "application/json",
    payload: JSON.stringify({
      chat_id: chatId,
      text: "PRStK Telegram 備援鏈路驗證（管理員手動測試）\n測試身份：" + testId + "\n這不是事故告警。",
      disable_web_page_preview: true,
    }),
  });
  const body = JSON.parse(response.getContentText() || "{}");
  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300 || body.ok !== true) {
    const state = response.getResponseCode() >= 500 ? "delivery_unknown" : "failed_not_sent";
    props.setProperty("PRSTK_WATCHDOG_LAST_MANUAL_TEST", testId + "|" + state + "|http_" + response.getResponseCode());
    throw new Error("Telegram manual verification was not confirmed; inspect this execution and do not assume delivery.");
  }
  props.setProperty("PRSTK_WATCHDOG_LAST_MANUAL_TEST", testId + "|sent|" + String(body.result?.message_id || "unknown"));
  return "Telegram manual verification accepted; check the private administrator chat. Test identity: " + testId;
}

function pollPrstkWatchdog() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return "watchdog_overlap_skipped";
  try {
    const props = PropertiesService.getScriptProperties();
    const base = props.getProperty("PRSTK_WATCHDOG_WORKER_BASE") || "";
    const current = inspectPrstkHealth_(base);
    const prior = props.getProperty(PRSTK_STATE_PROPERTY) || "";
    if (current === prior) {
      const transitionId = props.getProperty(PRSTK_TRANSITION_ID_PROPERTY) || "";
      const lastResult = props.getProperty(PRSTK_LAST_TELEGRAM_PROPERTY) || "";
      if (transitionId && lastResult === transitionId + "|not_configured") {
        const transitionNumber = Number(props.getProperty(PRSTK_TRANSITION_PROPERTY) || "0");
        sendPrstkTelegramOnce_(props, transitionId, current,
          "PRStK 獨立監看發現告警服務狀態變更。\n狀態：" + current + "\n轉換序號：" + transitionNumber + "\n時間：" + new Date().toISOString(), transitionNumber);
      }
      return current;
    }
    const transitionNumber = Number(props.getProperty(PRSTK_TRANSITION_PROPERTY) || "0") + 1;
    const transitionId = String(transitionNumber) + ":" + sha256Prstk_(prior + "\n" + current);

    // Record before the network call. If Telegram accepts a request and its
    // response is lost, the same transition is never blindly sent again.
    props.setProperty(PRSTK_STATE_PROPERTY, current);
    props.setProperty(PRSTK_TRANSITION_PROPERTY, String(transitionNumber));
    props.setProperty(PRSTK_TRANSITION_ID_PROPERTY, transitionId);
    if (current === "healthy") {
      if (prior) sendPrstkTelegramOnce_(props, transitionId, "healthy", "PRStK 事故郵件與 GitHub 心跳已恢復；獨立監看已重新取得兩側新鮮證據。", transitionNumber);
      return current;
    }
    sendPrstkTelegramOnce_(props, transitionId, current, "PRStK 獨立監看發現告警服務狀態變更。\n狀態：" + current + "\n轉換序號：" + transitionNumber + "\n時間：" + new Date().toISOString(), transitionNumber);
    return current;
  } finally {
    lock.releaseLock();
  }
}

function inspectPrstkHealth_(workerBase) {
  let workerState = "healthy";
  let githubState = "healthy";
  try {
    if (!/^https:\/\/[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*\.workers\.dev$/i.test(workerBase)) {
      throw new Error("workers_dev_origin_invalid");
    }
    const response = UrlFetchApp.fetch(workerBase + "/public/ops/liveness", {
      method: "get", muteHttpExceptions: true, followRedirects: false,
      headers: { "Accept": "application/json" },
    });
    if (response.getResponseCode() !== 200) throw new Error("worker_liveness_http_" + response.getResponseCode());
    const body = JSON.parse(response.getContentText());
    if (body.ok !== true || body.component !== "incident-coordinator") throw new Error("worker_liveness_contract_invalid");
    const observed = Date.parse(body.observed_at || "");
    if (!Number.isFinite(observed)) throw new Error("worker_liveness_time_ambiguous");
    const age = Date.now() - observed;
    if (age < -PRSTK_FUTURE_TOLERANCE_MS) throw new Error("worker_liveness_time_ambiguous");
    if (age > PRSTK_WORKER_MAX_AGE_MS) throw new Error("worker_liveness_stale");
  } catch (error) {
    workerState = safeErrorCodePrstk_(error);
  }

  try {
    const url = "https://api.github.com/repos/" + PRSTK_REPOSITORY
      + "/actions/workflows/incident-ops-heartbeat.yml/runs?branch=main&per_page=20&page=1";
    const response = UrlFetchApp.fetch(url, {
      method: "get", muteHttpExceptions: true, followRedirects: false,
      headers: { "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
    });
    if (response.getResponseCode() !== 200) throw new Error("github_heartbeat_http_" + response.getResponseCode());
    const body = JSON.parse(response.getContentText());
    const runs = Array.isArray(body.workflow_runs) ? body.workflow_runs : [];
    if (body.total_count < runs.length) throw new Error("github_heartbeat_coverage_invalid");
    const exact = runs.filter(function (run) {
      return run && run.path === PRSTK_HEARTBEAT_WORKFLOW
        && run.head_branch === "main"
        && run.head_repository && run.head_repository.full_name === PRSTK_REPOSITORY;
    });
    if (exact.length !== runs.length || exact.length === 0) throw new Error("github_heartbeat_identity_invalid");
    exact.sort(function (left, right) {
      return String(right.created_at || "").localeCompare(String(left.created_at || ""));
    });
    const newest = exact[0];
    const newestCreated = Date.parse(newest.created_at || "");
    if (!Number.isFinite(newestCreated) || newestCreated - Date.now() > PRSTK_FUTURE_TOLERANCE_MS) {
      throw new Error("github_heartbeat_time_ambiguous");
    }
    if (newest.status === "completed" && newest.conclusion !== "success") {
      throw new Error("github_heartbeat_latest_failed");
    }
    const successful = exact.filter(function (run) {
      return run.status === "completed" && run.conclusion === "success";
    }).sort(function (left, right) {
      return String(right.updated_at || right.created_at || "").localeCompare(String(left.updated_at || left.created_at || ""));
    });
    if (successful.length === 0) throw new Error("github_heartbeat_success_missing");
    const successTime = Date.parse(successful[0].updated_at || successful[0].created_at || "");
    if (!Number.isFinite(successTime) || successTime - Date.now() > PRSTK_FUTURE_TOLERANCE_MS) {
      throw new Error("github_heartbeat_time_ambiguous");
    }
    if (Date.now() - successTime > PRSTK_GITHUB_MAX_AGE_MS) throw new Error("github_heartbeat_stale");
  } catch (error) {
    githubState = safeErrorCodePrstk_(error);
  }
  if (workerState === "healthy" && githubState === "healthy") return "healthy";
  return "worker=" + workerState + ";github=" + githubState;
}

function sendPrstkTelegramOnce_(props, transitionId, state, message, transitionNumber) {
  const previous = props.getProperty(PRSTK_LAST_TELEGRAM_PROPERTY) || "";
  if (previous.indexOf(transitionId + "|") === 0 && previous !== transitionId + "|not_configured") return;
  const token = props.getProperty("PRSTK_WATCHDOG_TELEGRAM_BOT_TOKEN") || "";
  const chatId = props.getProperty("PRSTK_WATCHDOG_TELEGRAM_CHAT_ID") || "";
  const resultKey = transitionId + "|delivery_unknown";
  props.setProperty(PRSTK_LAST_TELEGRAM_PROPERTY, resultKey);
  if (!token || !chatId) {
    props.setProperty(PRSTK_LAST_TELEGRAM_PROPERTY, transitionId + "|not_configured");
    return;
  }
  const url = "https://api.telegram.org/bot" + token + "/sendMessage";
  try {
    const response = UrlFetchApp.fetch(url, {
      method: "post", muteHttpExceptions: true, followRedirects: false,
      contentType: "application/json",
      payload: JSON.stringify({ chat_id: chatId, text: message, disable_web_page_preview: true }),
    });
    if (response.getResponseCode() >= 200 && response.getResponseCode() < 300) {
      const body = JSON.parse(response.getContentText());
      props.setProperty(PRSTK_LAST_TELEGRAM_PROPERTY,
        transitionId + "|" + (body.ok === true ? "sent" : "failed_not_sent") + "|" + state + "|" + transitionNumber);
    } else {
      const status = response.getResponseCode();
      props.setProperty(PRSTK_LAST_TELEGRAM_PROPERTY,
        transitionId + "|" + (status >= 500 ? "delivery_unknown" : "failed_not_sent") + "|http_" + status);
    }
  } catch (_) {
    // Request outcome may be ambiguous. Keep the pre-recorded no-retry marker.
  }
}

function safeErrorCodePrstk_(error) {
  const value = error && error.message ? String(error.message) : "unknown";
  return value.replace(/[^A-Za-z0-9_.:-]/g, "_").slice(0, 100) || "unknown";
}

function sha256Prstk_(text) {
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8);
  return bytes.map(function (value) {
    const unsigned = (value + 256) % 256;
    return (unsigned < 16 ? "0" : "") + unsigned.toString(16);
  }).join("");
}
