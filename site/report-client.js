/* Async report client for the Cloudflare Worker boundary.
 * It never accepts a caller-supplied Telegram user ID; the Worker verifies
 * Telegram WebApp initData and enforces TG_ALLOWED_USERS server-side.
 */
(function () {
  "use strict";
  const telegram = window.Telegram?.WebApp;
  const meta = document.querySelector('meta[name="prstk-api-base"]');
  const API_BASE = String(window.PRSTK_API_BASE_URL || meta?.content || window.location.origin).replace(/\/$/, "");
  const state = { jobId: null, timer: null, deadline: 0 };
  const byId = (id) => document.getElementById(id);
  const setState = (value) => { const node = byId("report-job-state"); if (node) node.textContent = value; };
  const authHeaders = () => {
    const initData = telegram?.initData || "";
    return initData ? { "X-Telegram-Init-Data": initData } : {};
  };
  const request = async (path, options = {}) => {
    const response = await fetch(`${API_BASE}${path}`, { ...options, headers: { "content-type": "application/json", ...authHeaders(), ...(options.headers || {}) } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(String(payload.error || `請求失敗（${response.status}）`));
    return payload;
  };
  const stopPolling = () => { if (state.timer) window.clearTimeout(state.timer); state.timer = null; };
  const poll = async () => {
    if (!state.jobId) return;
    if (Date.now() >= state.deadline) { stopPolling(); setState("背景處理中"); byId("report-error").textContent = "報告仍可能在背景產生，可稍後重新查看。"; return; }
    try {
      const result = await request(`/api/jobs/${encodeURIComponent(state.jobId)}`, { headers: {} });
      setState(result.status === "running" ? "執行中" : result.status === "queued" ? "排隊中" : result.status === "completed" ? "完成" : "失敗");
      if (result.status === "completed") {
        stopPolling(); byId("report-preview").hidden = false; byId("report-preview").textContent = String(result.report || ""); byId("send-report").disabled = !result.report; return;
      }
      if (result.status === "failed") { stopPolling(); byId("report-error").textContent = String(result.error || "報告產生失敗"); return; }
    } catch (error) { byId("report-error").textContent = `暫時無法查詢報告：${error.message}`; }
    state.timer = window.setTimeout(poll, 2500);
  };
  const generate = async () => {
    stopPolling(); byId("generate-report").disabled = true; byId("send-report").disabled = true; byId("report-error").textContent = ""; byId("report-preview").hidden = true; setState("排隊中");
    try {
      const result = await request("/api/report", { method: "POST", body: JSON.stringify({ market: byId("report-market").value, intro: byId("report-intro").value, outro: byId("report-outro").value }) });
      state.jobId = result.job_id; state.deadline = Date.now() + 5 * 60 * 1000; await poll();
    } catch (error) { setState("失敗"); byId("report-error").textContent = error.message; }
    finally { byId("generate-report").disabled = false; }
  };
  const send = async () => {
    const report = byId("report-preview").textContent.trim(); if (!report) return; byId("send-report").disabled = true; setState("發送中");
    try { const result = await request("/api/send", { method: "POST", body: JSON.stringify({ report }) }); setState(result.ok ? "已送出" : "部分失敗"); byId("report-error").textContent = `Telegram：${result.sent}/${result.total} 位收件人成功。`; }
    catch (error) { setState("發送失敗"); byId("report-error").textContent = error.message; }
    finally { byId("send-report").disabled = false; }
  };
  window.addEventListener("DOMContentLoaded", () => { byId("generate-report")?.addEventListener("click", generate); byId("send-report")?.addEventListener("click", send); });
}());
