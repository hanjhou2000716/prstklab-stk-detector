/**
 * Cloudflare Worker API boundary for interactive reports.
 *
 * It performs authentication, validation, Supabase CRUD, workflow dispatch and
 * Telegram transport only. Market downloads and report computation stay in
 * GitHub Actions (`jobs/process_report_job.py`).
 */

interface Env {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  GITHUB_DISPATCH_TOKEN: string;
  GITHUB_REPOSITORY: string;
  TG_TOKEN: string;
  TG_SUBSCRIBERS?: string;
  TELEGRAM_CHAT_IDS?: string;
  TG_ALLOWED_USERS?: string;
  ADMIN_KEY?: string;
  ALLOWED_ORIGINS?: string;
  SERVICE_NAME?: string;
  VERSION?: string;
}

type Job = Record<string, unknown> & { id: string; status: string };

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });

function origins(env: Env): string[] {
  return String(env.ALLOWED_ORIGINS || "").split(",").map((value) => value.trim()).filter(Boolean);
}

function cors(request: Request, env: Env): Record<string, string> {
  const origin = request.headers.get("Origin") || "";
  const allowed = origins(env);
  return origin && allowed.includes(origin) ? { "access-control-allow-origin": origin, vary: "Origin" } : {};
}

function withCors(response: Response, request: Request, env: Env): Response {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(cors(request, env))) headers.set(key, value);
  return new Response(response.body, { status: response.status, headers });
}

function safeId(value: string): boolean {
  return /^[0-9a-fA-F-]{16,80}$/.test(value);
}

async function hmac(key: ArrayBuffer | string, data: string): Promise<ArrayBuffer> {
  const material = typeof key === "string" ? new TextEncoder().encode(key) : key;
  const cryptoKey = await crypto.subtle.importKey("raw", material, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return crypto.subtle.sign("HMAC", cryptoKey, new TextEncoder().encode(data));
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function verifyTelegramInitData(request: Request, env: Env): Promise<{ userId: string; username?: string } | null> {
  const supplied = request.headers.get("X-Telegram-Init-Data") || request.headers.get("Authorization")?.replace(/^tma\s+/i, "") || "";
  if (!supplied || !env.TG_TOKEN) return null;
  const params = new URLSearchParams(supplied);
  const hash = params.get("hash");
  const authDate = Number(params.get("auth_date") || 0);
  if (!hash || !Number.isFinite(authDate) || Math.abs(Date.now() / 1000 - authDate) > 86400) return null;
  params.delete("hash");
  const dataCheck = [...params.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => `${key}=${value}`).join("\n");
  const secret = await hmac("WebAppData", env.TG_TOKEN);
  if (hex(await hmac(secret, dataCheck)) !== hash.toLowerCase()) return null;
  try {
    const user = JSON.parse(params.get("user") || "{}");
    const userId = String(user.id || "");
    return /^\d+$/.test(userId) ? { userId, username: typeof user.username === "string" ? user.username : undefined } : null;
  } catch (_) {
    return null;
  }
}

async function isAuthorized(request: Request, env: Env): Promise<{ userId: string; admin: boolean } | null> {
  if (env.ADMIN_KEY && request.headers.get("X-Admin-Key") === env.ADMIN_KEY) return { userId: "admin", admin: true };
  const identity = await verifyTelegramInitData(request, env);
  if (!identity) return null;
  const allowlist = String(env.TG_ALLOWED_USERS || "").split(",").map((value) => value.trim()).filter(Boolean);
  return !allowlist.length || allowlist.includes(identity.userId) ? { userId: identity.userId, admin: false } : null;
}

async function supabase(env: Env, method: string, table: string, query = "", body?: unknown): Promise<any[]> {
  if (!env.SUPABASE_URL || !env.SUPABASE_SERVICE_ROLE_KEY) throw new Error("database is not configured");
  const response = await fetch(`${env.SUPABASE_URL.replace(/\/$/, "")}/rest/v1/${table}${query}`, {
    method,
    headers: { apikey: env.SUPABASE_SERVICE_ROLE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`, "content-type": "application/json", Prefer: "return=representation" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`database request failed (${response.status})`);
  const payload: unknown = await response.json().catch(() => []);
  return Array.isArray(payload) ? payload : payload && typeof payload === "object" ? [payload] : [];
}

async function dispatchReport(env: Env, jobId: string): Promise<void> {
  if (!env.GITHUB_DISPATCH_TOKEN || !env.GITHUB_REPOSITORY) throw new Error("report worker is not configured");
  const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/report-worker.yml/dispatches`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "PRStK-Cloudflare-Worker" },
    body: JSON.stringify({ ref: "main", inputs: { job_id: jobId } }),
  });
  if (!response.ok) throw new Error(`report worker dispatch failed (${response.status})`);
}

async function recipientHash(chatId: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(chatId));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

function recipients(env: Env): string[] {
  return [...new Set(String(env.TG_SUBSCRIBERS || env.TELEGRAM_CHAT_IDS || "").split(/[\s,]+/).map((value) => value.trim()).filter((value) => /^-?\d+$/.test(value)))].slice(0, 30);
}

async function sendTelegram(env: Env, report: string, provenance: { traceId: string; alertId?: string; releaseId?: string; snapshotId?: string }): Promise<{ sent: number; total: number; failed: number; receipts: Array<Record<string, unknown>> }> {
  if (!env.TG_TOKEN) throw new Error("Telegram is not configured");
  const target = recipients(env);
  if (!target.length) throw new Error("Telegram recipients are not configured");
  const text = escapeHtml(report);
  const chunks = text.match(/[\s\S]{1,4000}/g) || [text];
  let sent = 0;
  let failed = 0;
  const receipts: Array<Record<string, unknown>> = [];
  for (const chatId of target) {
    const hash = await recipientHash(chatId);
    let messageId: number | undefined;
    let errorClass: string | undefined;
    let status = "failed";
    try {
      for (const chunk of chunks) {
        let response = await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ chat_id: chatId, text: chunk, parse_mode: "HTML", disable_web_page_preview: true }) });
        if (response.status === 429) {
          const payload = await response.clone().json().catch(() => ({})) as Record<string, unknown>;
          const retryAfter = Math.min(10, Math.max(1, Number((payload.parameters as Record<string, unknown> | undefined)?.retry_after || 1)));
          await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000));
          response = await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ chat_id: chatId, text: chunk, parse_mode: "HTML", disable_web_page_preview: true }) });
        }
        if (!response.ok) {
          errorClass = response.status >= 500 ? "temporary_api" : response.status === 403 ? "blocked" : "telegram_api";
          throw new Error(`Telegram request failed (${response.status})`);
        }
        const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
        const result = payload.result as Record<string, unknown> | undefined;
        if (typeof result?.message_id === "number") messageId = result.message_id;
      }
      sent += 1;
      status = "delivered";
    } catch (_) {
      failed += 1;
    }
    receipts.push({ trace_id: provenance.traceId, alert_id: provenance.alertId || null, release_id: provenance.releaseId || null, snapshot_id: provenance.snapshotId || null, recipient_hash: hash, status, message_id: messageId || null, error_class: errorClass || null, sent_at: new Date().toISOString() });
  }
  return { sent, total: target.length, failed, receipts };
}

async function handle(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...cors(request, env), "access-control-allow-methods": "GET,POST,OPTIONS", "access-control-allow-headers": "content-type,authorization,x-admin-key,x-telegram-init-data" } });
  if (url.pathname === "/api/health" && request.method === "GET") {
    let database = "unknown";
    try { await supabase(env, "GET", "system_status", "?select=component,status&limit=1"); database = "ok"; } catch (_) { database = "unavailable"; }
    return json({ ok: database === "ok", service: env.SERVICE_NAME || "PRStK 稜量盤後速覽", api: "ok", database, version: env.VERSION || "worker" });
  }
  if (url.pathname === "/api/report" && request.method === "POST") {
    const identity = await isAuthorized(request, env);
    if (!identity) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
    const payload = await request.json().catch(() => null) as Record<string, unknown> | null;
    const market = String(payload?.market || "");
    if (!payload || !["tw", "us"].includes(market)) return json({ ok: false, error: "INVALID_MARKET" }, 400);
    const rows = await supabase(env, "POST", "report_jobs", "", { market, intro: String(payload.intro || "").slice(0, 2000), outro: String(payload.outro || "").slice(0, 2000), status: "queued", requested_by: identity.userId });
    const job = rows[0] as Job | undefined;
    if (!job?.id) return json({ ok: false, error: "JOB_CREATE_FAILED" }, 503);
    try { await dispatchReport(env, job.id); } catch (error) { await supabase(env, "PATCH", "report_jobs", `?id=eq.${encodeURIComponent(job.id)}`, { status: "failed", error: error instanceof Error ? error.message.slice(0, 240) : "dispatch failed" }); return json({ ok: false, error: "DISPATCH_FAILED", job_id: job.id }, 503); }
    return json({ ok: true, job_id: job.id, status: "queued" }, 202);
  }
  const jobMatch = url.pathname.match(/^\/api\/jobs\/([0-9a-fA-F-]{16,80})$/);
  if (jobMatch && request.method === "GET") {
    if (!await isAuthorized(request, env)) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
    if (!safeId(jobMatch[1])) return json({ ok: false, error: "INVALID_JOB_ID" }, 400);
    const rows = await supabase(env, "GET", "report_jobs", `?id=eq.${encodeURIComponent(jobMatch[1])}&select=*`);
    const job = rows[0] as Job | undefined;
    if (!job) return json({ ok: false, error: "NOT_FOUND" }, 404);
    if (job.status === "completed") { const reports = await supabase(env, "GET", "reports", `?job_id=eq.${encodeURIComponent(job.id)}&select=content,created_at&order=created_at.desc&limit=1`); return json({ ok: true, job_id: job.id, status: job.status, report: reports[0]?.content || "" }); }
    return json({ ok: job.status !== "failed", job_id: job.id, status: job.status, ...(job.status === "failed" ? { error: String(job.error || "report failed").slice(0, 240) } : {}) });
  }
  if (url.pathname === "/api/send" && request.method === "POST") {
    if (!await isAuthorized(request, env)) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
    const payload = await request.json().catch(() => null) as Record<string, unknown> | null;
    const report = typeof payload?.report === "string" ? payload.report.trim() : "";
    if (!report) return json({ ok: false, error: "REPORT_REQUIRED" }, 400);
    const traceId = crypto.randomUUID();
    const result = await sendTelegram(env, report, {
      traceId,
      alertId: typeof payload.alert_id === "string" ? payload.alert_id.slice(0, 160) : undefined,
      releaseId: typeof payload.release_id === "string" ? payload.release_id.slice(0, 160) : undefined,
      snapshotId: typeof payload.snapshot_id === "string" ? payload.snapshot_id.slice(0, 160) : undefined,
    });
    let receiptStatus = "persisted";
    try { await supabase(env, "POST", "delivery_receipts", "", result.receipts); } catch (_) { receiptStatus = "persistence_failed"; }
    return json({ ok: result.failed === 0 && receiptStatus === "persisted", trace_id: traceId, sent: result.sent, total: result.total, failed: result.failed, receipt_status: receiptStatus }, result.failed || receiptStatus !== "persisted" ? 207 : 200);
  }
  return json({ ok: false, error: "NOT_FOUND" }, 404);
}

const handler: ExportedHandler<Env> = {
  async fetch(request, env): Promise<Response> {
    try {
      return withCors(await handle(request, env), request, env);
    } catch (error) {
      return withCors(json({ ok: false, error: error instanceof Error ? error.message.slice(0, 240) : "request failed" }, 500), request, env);
    }
  },
};

export default handler;
