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
  /** Canonical name shared with GitHub Actions; TG_TOKEN remains a legacy alias. */
  TELEGRAM_BOT_TOKEN?: string;
  TG_TOKEN?: string;
  TG_SUBSCRIBERS?: string;
  TELEGRAM_CHAT_IDS?: string;
  TG_ALLOWED_USERS?: string;
  ADMIN_KEY?: string;
  ALLOWED_ORIGINS?: string;
  SERVICE_NAME?: string;
  VERSION?: string;
  /** HMAC secret shared with GitHub Actions for receipt ingestion. */
  DELIVERY_RECEIPT_SHARED_SECRET?: string;
  /** Google Pub/Sub authenticated push contract for Gmail notifications. */
  GMAIL_PUBSUB_AUDIENCE?: string;
  GMAIL_PUBSUB_SERVICE_ACCOUNT?: string;
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

function telegramToken(env: Env): string {
  return String(env.TELEGRAM_BOT_TOKEN || env.TG_TOKEN || "").trim();
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

function base64UrlBytes(value: string): Uint8Array | null {
  try {
    const normalized = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
    const decoded = atob(normalized);
    return Uint8Array.from(decoded, (char) => char.charCodeAt(0));
  } catch (_) {
    return null;
  }
}

function parseJwtPart(value: string): Record<string, unknown> | null {
  const bytes = base64UrlBytes(value);
  if (!bytes) return null;
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch (_) {
    return null;
  }
}

let googleCerts: { expiresAt: number; keys: Array<Record<string, unknown>> } | null = null;

async function verifyGoogleOidc(token: string, env: Env): Promise<Record<string, unknown> | null> {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const header = parseJwtPart(parts[0]);
  const claims = parseJwtPart(parts[1]);
  const signature = base64UrlBytes(parts[2]);
  const kid = typeof header?.kid === "string" ? header.kid : "";
  if (!header || !claims || !signature || header.alg !== "RS256" || !kid) return null;
  const issuer = String(claims.iss || "");
  const audience = String(claims.aud || "");
  const email = String(claims.email || "");
  const exp = Number(claims.exp || 0);
  const issuedAt = Number(claims.iat || 0);
  const now = Math.floor(Date.now() / 1000);
  if (!["accounts.google.com", "https://accounts.google.com"].includes(issuer)) return null;
  if (!env.GMAIL_PUBSUB_AUDIENCE || audience !== env.GMAIL_PUBSUB_AUDIENCE) return null;
  if (!env.GMAIL_PUBSUB_SERVICE_ACCOUNT || email !== env.GMAIL_PUBSUB_SERVICE_ACCOUNT) return null;
  if (claims.email_verified === false || !Number.isFinite(exp) || exp < now - 30 || exp > now + 86400) return null;
  if (Number.isFinite(issuedAt) && issuedAt > now + 60) return null;
  try {
    if (!googleCerts || googleCerts.expiresAt <= Date.now()) {
      const response = await fetch("https://www.googleapis.com/oauth2/v3/certs", { headers: { Accept: "application/json" } });
      if (!response.ok) return null;
      const payload = await response.json() as { keys?: unknown };
      const keys = Array.isArray(payload.keys) ? payload.keys.filter((value): value is Record<string, unknown> => Boolean(value && typeof value === "object")) : [];
      const cacheSeconds = Number(response.headers.get("cache-control")?.match(/max-age=(\d+)/i)?.[1] || 300);
      googleCerts = { keys, expiresAt: Date.now() + Math.min(3600000, Math.max(60000, cacheSeconds * 1000)) };
    }
    const jwk = googleCerts.keys.find((value) => value.kid === kid);
    if (!jwk) return null;
    const key = await crypto.subtle.importKey("jwk", jwk as unknown as JsonWebKey, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, signature, new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
    return valid ? claims : null;
  } catch (_) {
    return null;
  }
}

async function gmailNotification(body: unknown): Promise<{ historyId: string; emailHash: string } | null> {
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const message = (body as Record<string, unknown>).message;
  if (!message || typeof message !== "object" || Array.isArray(message)) return null;
  const encoded = (message as Record<string, unknown>).data;
  if (typeof encoded !== "string" || encoded.length > 8192) return null;
  const bytes = base64UrlBytes(encoded);
  if (!bytes) return null;
  try {
    const payload: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
    const historyId = String((payload as Record<string, unknown>).historyId || "").trim();
    const email = String((payload as Record<string, unknown>).emailAddress || "").trim().toLowerCase();
    if (!/^\d{1,40}$/.test(historyId) || !/^[^@\s]{1,128}@[^@\s]{1,255}$/.test(email)) return null;
    return { historyId, emailHash: hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(email))).slice(0, 32) };
  } catch (_) {
    return null;
  }
}

async function verifyTelegramInitData(request: Request, env: Env): Promise<{ userId: string; username?: string } | null> {
  const supplied = request.headers.get("X-Telegram-Init-Data") || request.headers.get("Authorization")?.replace(/^tma\s+/i, "") || "";
  const token = telegramToken(env);
  if (!supplied || !token) return null;
  const params = new URLSearchParams(supplied);
  const hash = params.get("hash");
  const authDate = Number(params.get("auth_date") || 0);
  if (!hash || !Number.isFinite(authDate) || Math.abs(Date.now() / 1000 - authDate) > 86400) return null;
  params.delete("hash");
  const dataCheck = [...params.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => `${key}=${value}`).join("\n");
  const secret = await hmac("WebAppData", token);
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

async function supabase(env: Env, method: string, table: string, query = "", body?: unknown, prefer = "return=representation"): Promise<any[]> {
  if (!env.SUPABASE_URL || !env.SUPABASE_SERVICE_ROLE_KEY) throw new Error("database is not configured");
  const response = await fetch(`${env.SUPABASE_URL.replace(/\/$/, "")}/rest/v1/${table}${query}`, {
    method,
    headers: { apikey: env.SUPABASE_SERVICE_ROLE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`, "content-type": "application/json", Prefer: prefer },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`database request failed (${response.status})`);
  const payload: unknown = await response.json().catch(() => []);
  return Array.isArray(payload) ? payload : payload && typeof payload === "object" ? [payload] : [];
}

function boundedString(value: unknown, max = 240): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed && trimmed.length <= max ? trimmed : null;
}

function boundedHashes(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > 200) return null;
  const values = value.map((item) => boundedString(item, 128));
  return values.every((item): item is string => Boolean(item)) ? values : null;
}

function boundedNotificationKeys(value: unknown, limit = 200): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value
    .map((item) => boundedString(item, 160))
    .filter((item): item is string => Boolean(item)))]
    .slice(0, Math.max(1, Math.min(200, limit)));
}

function validCount(value: unknown): number | null {
  return Number.isInteger(value) && Number(value) >= 0 && Number(value) <= 100000 ? Number(value) : null;
}

async function signatureFor(secret: string, body: string): Promise<string> {
  return `sha256=${hex(await hmac(secret, body))}`;
}

async function verifyReceiptSignature(request: Request, body: string, secret: string): Promise<boolean> {
  const supplied = request.headers.get("X-PRSTK-Signature") || "";
  if (!/^sha256=[0-9a-f]{64}$/i.test(supplied)) return false;
  const expected = await signatureFor(secret, body);
  const left = new TextEncoder().encode(supplied.toLowerCase());
  const right = new TextEncoder().encode(expected);
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

function normalizeReceipt(input: unknown): Record<string, unknown> | null {
  if (!input || typeof input !== "object" || Array.isArray(input)) return null;
  const value = input as Record<string, unknown>;
  const traceId = boundedString(value.trace_id, 160);
  const kind = boundedString(value.receipt_kind, 32);
  const origin = boundedString(value.receipt_origin, 32);
  const mode = boundedString(value.delivery_mode, 32);
  const status = boundedString(value.delivery_status, 32);
  const releaseId = boundedString(value.release_id, 160);
  const snapshotId = boundedString(value.snapshot_id, 160);
  const alertId = value.alert_id == null ? null : boundedString(value.alert_id, 160);
  const delivered = validCount(value.delivered_count);
  const failed = validCount(value.failed_count);
  const failedHashes = boundedHashes(value.failed_recipient_hashes);
  const notificationKeys = boundedHashes(value.notification_keys);
  if (!traceId || !kind || !origin || !mode || !status || !releaseId || !snapshotId || delivered === null || failed === null || !failedHashes || !notificationKeys) return null;
  if (!['production', 'photo_smoke', 'creator'].includes(kind) || origin !== 'github_actions' || !['text', 'photo'].includes(mode) || !['delivered', 'partial', 'failed'].includes(status)) return null;
  if (failed === 0 && failedHashes.length > 0) return null;
  if (status === "delivered" && failed > 0) return null;
  if (status === "failed" && delivered > 0) return null;
  return {
    trace_id: traceId,
    receipt_kind: kind,
    receipt_origin: origin,
    alert_id: alertId,
    release_id: releaseId,
    snapshot_id: snapshotId,
    delivery_mode: mode,
    delivery_status: status,
    delivered_count: delivered,
    failed_count: failed,
    failed_recipient_hashes: failedHashes,
    notification_keys: notificationKeys,
    renderer_error_type: value.renderer_error_type == null ? null : boundedString(value.renderer_error_type, 160),
    financialjuice_delivery_trace: value.financialjuice_delivery_trace && typeof value.financialjuice_delivery_trace === "object" && !Array.isArray(value.financialjuice_delivery_trace) ? value.financialjuice_delivery_trace : null,
    reported_at: value.reported_at == null ? null : boundedString(value.reported_at, 64),
  };
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

async function verifyGetSignature(request: Request, secret: string): Promise<boolean> {
  const supplied = request.headers.get("X-PRSTK-Signature") || "";
  if (!/^sha256=[0-9a-f]{64}$/i.test(supplied)) return false;
  const url = new URL(request.url);
  const target = `${url.pathname}${url.search}`;
  const expected = await signatureFor(secret, `GET\n${target}`);
  const left = new TextEncoder().encode(supplied.toLowerCase());
  const right = new TextEncoder().encode(expected);
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

async function dispatchGmailHistorySync(env: Env, historyId: string): Promise<void> {
  if (!env.GITHUB_DISPATCH_TOKEN || !env.GITHUB_REPOSITORY) throw new Error("gmail sync is not configured");
  const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/gmail-history-sync.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "PRStK-Cloudflare-Worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs: { history_id: historyId } }),
  });
  if (!response.ok) throw new Error(`gmail sync dispatch failed (${response.status})`);
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
  const token = telegramToken(env);
  if (!token) throw new Error("Telegram is not configured");
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
        let response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ chat_id: chatId, text: chunk, parse_mode: "HTML", disable_web_page_preview: true }) });
        if (response.status === 429) {
          const payload = await response.clone().json().catch(() => ({})) as Record<string, unknown>;
          const retryAfter = Math.min(10, Math.max(1, Number((payload.parameters as Record<string, unknown> | undefined)?.retry_after || 1)));
          await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000));
          response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ chat_id: chatId, text: chunk, parse_mode: "HTML", disable_web_page_preview: true }) });
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
    return json({
      ok: database === "ok",
      service: env.SERVICE_NAME || "PRStK 稜量盤後速覽",
      api: "ok",
      database,
      version: env.VERSION || "worker",
      receipt: {
        backend: "supabase",
        configured: Boolean(String(env.DELIVERY_RECEIPT_SHARED_SECRET || "").trim()),
      },
    });
  }
  if (url.pathname === "/external-observations" && request.method === "GET") {
    const secret = String(env.DELIVERY_RECEIPT_SHARED_SECRET || "").trim();
    if (!secret || !await verifyGetSignature(request, secret)) return json({ ok: false, error: "UNAUTHORIZED" }, 401);
    const limit = Math.min(500, Math.max(1, Number(url.searchParams.get("limit") || 100)));
    if (!Number.isInteger(limit)) return json({ ok: false, error: "INVALID_LIMIT" }, 400);
    try {
      const rows = await supabase(env, "GET", "gmail_public_observations", `?select=payload_json&order=created_at.desc,observation_id.desc&limit=${limit}`);
      const observations = rows
        .map((row) => row && typeof row === "object" ? (row as Record<string, unknown>).payload_json : null)
        .filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object" && !Array.isArray(row) && (row as Record<string, unknown>).public_safe === true));
      return json({ status: observations.length ? "ready" : "no_event", observations, count: observations.length });
    } catch (_) {
      return json({ ok: false, error: "OBSERVATIONS_UNAVAILABLE" }, 503);
    }
  }
  if (url.pathname === "/api/delivery-receipt" && request.method === "POST") {
    const secret = String(env.DELIVERY_RECEIPT_SHARED_SECRET || "").trim();
    if (!secret) return json({ ok: false, error: "RECEIPT_NOT_CONFIGURED" }, 503);
    const body = await request.text();
    if (body.length > 32768) return json({ ok: false, error: "PAYLOAD_TOO_LARGE" }, 413);
    if (!await verifyReceiptSignature(request, body, secret)) return json({ ok: false, error: "INVALID_SIGNATURE" }, 401);
    let input: unknown;
    try { input = JSON.parse(body); } catch (_) { return json({ ok: false, error: "INVALID_JSON" }, 400); }
    const receipt = normalizeReceipt(input);
    if (!receipt) return json({ ok: false, error: "INVALID_RECEIPT" }, 400);
    try {
      await supabase(env, "POST", "delivery_receipt_events", "?on_conflict=trace_id", receipt, "resolution=merge-duplicates,return=representation");
    } catch (_) {
      return json({ ok: false, error: "RECEIPT_PERSISTENCE_FAILED" }, 503);
    }
    return json({ ok: true, trace_id: receipt.trace_id, receipt_status: "persisted", receipt_backend: "supabase" });
  }
  if (url.pathname === "/api/gmail-pubsub" && request.method === "POST") {
    const authorization = request.headers.get("Authorization") || "";
    if (!authorization.toLowerCase().startsWith("bearer ")) return json({ ok: false, error: "UNAUTHENTICATED_PUBSUB" }, 401);
    const claims = await verifyGoogleOidc(authorization.slice(7).trim(), env);
    if (!claims) return json({ ok: false, error: "INVALID_PUBSUB_ID_TOKEN" }, 401);
    const body = await request.json().catch(() => null);
    const notification = await gmailNotification(body);
    if (!notification) return json({ ok: false, error: "INVALID_GMAIL_NOTIFICATION" }, 400);
    const rows = await supabase(env, "POST", "gmail_pubsub_events", "?on_conflict=history_id", {
      history_id: notification.historyId,
      gmail_address_hash: notification.emailHash,
      dispatch_status: "pending",
    }, "resolution=ignore-duplicates,return=representation");
    if (rows.length === 0) {
      const existing = await supabase(env, "GET", "gmail_pubsub_events", `?history_id=eq.${encodeURIComponent(notification.historyId)}&select=dispatch_status&limit=1`);
      if (String(existing[0]?.dispatch_status || "pending") === "dispatched") return new Response(null, { status: 204 });
    }
    try {
      await dispatchGmailHistorySync(env, notification.historyId);
      await supabase(env, "PATCH", "gmail_pubsub_events", `?history_id=eq.${encodeURIComponent(notification.historyId)}`, { dispatch_status: "dispatched", processed_at: new Date().toISOString(), dispatch_error: null }, "return=minimal");
      await supabase(env, "POST", "gmail_watch_state", "?on_conflict=id", { id: "primary", pending_history_id: notification.historyId, last_notification_at: new Date().toISOString() }, "resolution=merge-duplicates,return=minimal");
      return new Response(null, { status: 204 });
    } catch (_) {
      await supabase(env, "PATCH", "gmail_pubsub_events", `?history_id=eq.${encodeURIComponent(notification.historyId)}`, { dispatch_status: "failed", dispatch_error: "dispatch_failed" }, "return=minimal").catch(() => undefined);
      return json({ ok: false, error: "GMAIL_SYNC_DISPATCH_FAILED" }, 503);
    }
  }
  if (url.pathname === "/api/creator-delivery-history" && request.method === "POST") {
    const secret = String(env.DELIVERY_RECEIPT_SHARED_SECRET || "").trim();
    if (!secret) return json({ ok: false, error: "RECEIPT_NOT_CONFIGURED" }, 503);
    const body = await request.text();
    if (body.length > 4096) return json({ ok: false, error: "PAYLOAD_TOO_LARGE" }, 413);
    if (!await verifyReceiptSignature(request, body, secret)) return json({ ok: false, error: "INVALID_SIGNATURE" }, 401);
    let input: unknown;
    try { input = JSON.parse(body); } catch (_) { return json({ ok: false, error: "INVALID_JSON" }, 400); }
    const requestBody = input && typeof input === "object" && !Array.isArray(input) ? input as Record<string, unknown> : {};
    if (requestBody.receipt_kind !== "creator") return json({ ok: false, error: "INVALID_RECEIPT_KIND" }, 400);
    const limit = validCount(requestBody.limit) ?? 200;
    try {
      const rows = await supabase(env, "GET", "delivery_receipt_events", `?receipt_kind=eq.creator&select=notification_keys&order=received_at.desc&limit=${Math.min(200, Math.max(1, limit))}`);
      const keys = boundedNotificationKeys(rows.flatMap((row) => row && typeof row === "object" ? (row as Record<string, unknown>).notification_keys : []), limit);
      return json({ ok: true, notification_keys: keys, receipt_backend: "supabase" });
    } catch (_) {
      return json({ ok: false, error: "RECEIPT_HISTORY_UNAVAILABLE" }, 503);
    }
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
      alertId: typeof payload?.alert_id === "string" ? payload.alert_id.slice(0, 160) : undefined,
      releaseId: typeof payload?.release_id === "string" ? payload.release_id.slice(0, 160) : undefined,
      snapshotId: typeof payload?.snapshot_id === "string" ? payload.snapshot_id.slice(0, 160) : undefined,
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
