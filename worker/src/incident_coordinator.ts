/** Durable, serialized incident state and Gmail outbox for PRStK. */

export interface IncidentOpsEnv {
  INCIDENT_REPOSITORY_ID?: string;
  INCIDENT_REPOSITORY?: string;
  INCIDENT_OPS_AUDIENCE?: string;
  INCIDENT_OPS_MODE?: string;
  INCIDENT_RECIPIENT?: string;
  INCIDENT_GMAIL_OAUTH_CLIENT_ID?: string;
  INCIDENT_GMAIL_OAUTH_CLIENT_SECRET?: string;
  INCIDENT_GMAIL_REFRESH_TOKEN?: string;
  INCIDENT_GMAIL_FROM?: string;
  INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_ID?: string;
  INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_SECRET?: string;
  INCIDENT_RECEIPT_GMAIL_REFRESH_TOKEN?: string;
  INCIDENT_RECEIPT_GMAIL_ADDRESS?: string;
  INCIDENT_TELEGRAM_BOT_TOKEN?: string;
  INCIDENT_TELEGRAM_ADMIN_CHAT_ID?: string;
  ADMIN_KEY?: string;
}

const RECIPIENT = "hanjhou2000716@gmail.com";
const SCHEMA = "incident-envelope-v2";
const MAX_MAILS_PER_24H = 100;
const WARN_MAILS_PER_24H = 80;
const UNKNOWN_GRACE_MS = 5 * 60_000;
const OUTBOX_LEASE_MS = 60_000;
const TEXT = new TextEncoder();

type Envelope = Record<string, unknown>;
type SqlRow = Record<string, SqlStorageValue>;

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function rows<T extends SqlRow>(cursor: SqlStorageCursor<T>): T[] {
  return cursor.toArray();
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${canonical(object[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", TEXT.encode(value));
  return [...new Uint8Array(digest)].map((part) => part.toString(16).padStart(2, "0")).join("");
}

function validText(value: unknown, limit: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= limit && !/[\u0000-\u001f\u007f]/.test(value);
}

function validTime(value: unknown, required = false): boolean {
  if (value === null || value === "unknown") return !required;
  return typeof value === "string" && value.length <= 80 && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
}

const LIFECYCLE_RANK: Record<string, number> = {
  active: 1, recovery_pending: 2, recovered: 3,
  historical_pending_verification: 4, historical_diagnosed: 5,
};
const SEVERITY_RANK: Record<string, number> = { info: 0, normal: 1, high: 2, critical: 3 };
const EVIDENCE_RANK: Record<string, number> = { unknown: 0, invalid: 0, partial: 1, verified: 2 };

function minIso(left: unknown, right: unknown): string | null {
  const a = typeof left === "string" && Number.isFinite(Date.parse(left)) ? left : null;
  const b = typeof right === "string" && Number.isFinite(Date.parse(right)) ? right : null;
  if (!a) return b;
  if (!b) return a;
  return Date.parse(a) <= Date.parse(b) ? a : b;
}

function maxIso(left: unknown, right: unknown): string | null {
  const a = typeof left === "string" && Number.isFinite(Date.parse(left)) ? left : null;
  const b = typeof right === "string" && Number.isFinite(Date.parse(right)) ? right : null;
  if (!a) return b;
  if (!b) return a;
  return Date.parse(a) >= Date.parse(b) ? a : b;
}

async function validateEnvelope(value: unknown): Promise<Envelope> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("incident_envelope_object_required");
  const input = value as Envelope;
  if (new TextEncoder().encode(JSON.stringify(input)).length > 64_000) throw new Error("incident_envelope_too_large");
  if (input.schema_version !== SCHEMA) throw new Error("incident_envelope_schema_unsupported");
  for (const [field, limit] of [["incident_type", 80], ["component", 80], ["root_cause", 240], ["impact_type", 80]] as const) {
    if (!validText(input[field], limit)) throw new Error(`incident_envelope_${field}_invalid`);
  }
  const incidentIdentity = {
    incident_type: String(input.incident_type).trim().toLowerCase(),
    component: String(input.component).trim().toLowerCase(),
    root_cause: String(input.root_cause).trim().toLowerCase().split(/\s+/).join(" "),
  };
  if (await sha256(canonical(incidentIdentity)) !== input.incident_id) throw new Error("incident_envelope_incident_identity_mismatch");
  if (!/^[0-9a-f]{64}$/.test(String(input.impact_key || ""))) throw new Error("incident_envelope_impact_key_invalid");
  const impact = input.impact as Record<string, unknown> | undefined;
  const impactIdentity = impact && impact.identity && typeof impact.identity === "object" ? impact.identity : null;
  if (!impactIdentity || await sha256(canonical({ type: input.impact_type, identity: impactIdentity })) !== input.impact_key) {
    throw new Error("incident_envelope_impact_identity_mismatch");
  }
  const lifecycle = ["active", "recovery_pending", "recovered", "historical_diagnosed", "historical_pending_verification"];
  const severity = ["critical", "high", "normal", "info"];
  const evidenceStates = ["verified", "partial", "unknown", "invalid"];
  if (!lifecycle.includes(String(input.lifecycle)) || !severity.includes(String(input.severity))) throw new Error("incident_envelope_state_invalid");
  if (!evidenceStates.includes(String(input.evidence_integrity)) || typeof input.new_impact !== "boolean") throw new Error("incident_envelope_evidence_state_invalid");
  if ((input.lifecycle === "historical_diagnosed" || input.lifecycle === "historical_pending_verification") && input.new_impact) {
    throw new Error("incident_envelope_historical_new_impact_conflict");
  }
  if (!Number.isSafeInteger(input.generation) || Number(input.generation) < 1 || !Number.isSafeInteger(input.state_version) || Number(input.state_version) < 1) {
    throw new Error("incident_envelope_version_invalid");
  }
  const times = input.times as Record<string, unknown> | undefined;
  if (!times || !validTime(times.observed_at, true) || !validTime(times.first_detected_at) || !validTime(times.source_occurred_at)) {
    throw new Error("incident_envelope_times_invalid");
  }
  if (!Array.isArray(input.evidence) || input.evidence.length === 0 || input.evidence.length > 100) throw new Error("incident_envelope_evidence_invalid");
  for (const entry of input.evidence as Array<Record<string, unknown>>) {
    if (!entry || !validText(entry.repository, 200) || !validText(entry.workflow, 200)) throw new Error("incident_envelope_evidence_identity_invalid");
    if (!Number.isSafeInteger(entry.run_id) || Number(entry.run_id) < 1 || !Number.isSafeInteger(entry.attempt) || Number(entry.attempt) < 1) throw new Error("incident_envelope_evidence_run_invalid");
    if (!/^[0-9a-f]{40,64}$/i.test(String(entry.sha || ""))) throw new Error("incident_envelope_evidence_sha_invalid");
    if (entry.artifact_id !== null && entry.artifact_id !== undefined && (!Number.isSafeInteger(entry.artifact_id) || Number(entry.artifact_id) < 1)) throw new Error("incident_envelope_artifact_id_invalid");
    if (entry.artifact_digest !== null && entry.artifact_digest !== undefined && !/^sha256:[0-9a-f]{64}$/.test(String(entry.artifact_digest))) throw new Error("incident_envelope_artifact_digest_invalid");
    if (input.evidence_integrity === "verified" && (!entry.artifact_id || !entry.artifact_digest)) throw new Error("incident_envelope_verified_artifact_identity_missing");
  }
  if (!Array.isArray(input.issue_numbers) || (input.issue_numbers as unknown[]).some((number) => !Number.isSafeInteger(number) || Number(number) < 1)) {
    throw new Error("incident_envelope_issue_numbers_invalid");
  }
  return input;
}

function base64Bytes(value: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < value.length; index += 0x8000) binary += String.fromCharCode(...value.subarray(index, index + 0x8000));
  return btoa(binary);
}

function b64url(value: string): string {
  return base64Bytes(TEXT.encode(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function decodePart(value: string): Record<string, unknown> | null {
  try {
    const decoded = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
    const parsed: unknown = JSON.parse(decoded);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch (_) {
    return null;
  }
}

let githubJwks: { keys: JsonWebKey[]; expires: number } | null = null;

export async function verifyGitHubOidc(token: string, env: IncidentOpsEnv, allowedWorkflows: string[]): Promise<Record<string, unknown> | null> {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const header = decodePart(parts[0]);
  const claims = decodePart(parts[1]);
  let signature: Uint8Array;
  try {
    const signatureRaw = atob(parts[2].replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - parts[2].length % 4) % 4));
    signature = Uint8Array.from(signatureRaw, (char) => char.charCodeAt(0));
  } catch (_) {
    return null;
  }
  if (!header || !claims || header.alg !== "RS256" || typeof header.kid !== "string") return null;
  const now = Math.floor(Date.now() / 1000);
  const audiences = Array.isArray(claims.aud) ? claims.aud.map(String) : [String(claims.aud || "")];
  const workflowRef = String(claims.workflow_ref || "");
  if (!env.INCIDENT_OPS_AUDIENCE || !env.INCIDENT_REPOSITORY_ID || !env.INCIDENT_REPOSITORY) return null;
  if (claims.iss !== "https://token.actions.githubusercontent.com" || !audiences.includes(env.INCIDENT_OPS_AUDIENCE)) return null;
  if (String(claims.repository_id || "") !== env.INCIDENT_REPOSITORY_ID || String(claims.repository || "").toLowerCase() !== env.INCIDENT_REPOSITORY.toLowerCase()) return null;
  if (claims.ref !== "refs/heads/main" || !allowedWorkflows.some((workflow) => workflowRef === `${env.INCIDENT_REPOSITORY}/${workflow}@refs/heads/main`)) return null;
  if (!/^\d{1,24}$/.test(String(claims.run_id || "")) || !/^[1-9]\d{0,5}$/.test(String(claims.run_attempt || "")) || !/^[0-9a-f]{40}$/i.test(String(claims.sha || ""))) return null;
  if (Number(claims.exp || 0) < now - 30 || Number(claims.nbf || 0) > now + 60) return null;
  try {
    if (!githubJwks || githubJwks.expires <= Date.now()) {
      const response = await fetch("https://token.actions.githubusercontent.com/.well-known/jwks", { headers: { Accept: "application/json" } });
      if (!response.ok) return null;
      const payload = await response.json() as { keys?: JsonWebKey[] };
      githubJwks = { keys: Array.isArray(payload.keys) ? payload.keys : [], expires: Date.now() + 300_000 };
    }
    const jwk = githubJwks.keys.find((row) => (row as JsonWebKey & { kid?: string }).kid === header.kid);
    if (!jwk) return null;
    const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, signature, TEXT.encode(`${parts[0]}.${parts[1]}`));
    return valid ? claims : null;
  } catch (_) {
    return null;
  }
}

function windowKey(now: Date): string {
  const value = new Date(now);
  value.setUTCMinutes(value.getUTCMinutes() < 30 ? 0 : 30, 0, 0);
  return value.toISOString();
}

function safeHeader(value: string): string {
  return value.replace(/[\r\n\u0000-\u001f\u007f]/g, " ").trim();
}

function headerHasAddress(value: string, expected: string): boolean {
  const addresses = value.match(/[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,63}/gi) || [];
  return addresses.some((address) => address.toLowerCase() === expected.toLowerCase());
}

function encodedWord(value: string): string {
  const bytes = TEXT.encode(value);
  const maxBytes = 30;
  const chunks: Uint8Array[] = [];
  let current: number[] = [];
  for (const byte of bytes) {
    if (current.length && current.length >= maxBytes && (byte & 0xc0) !== 0x80) {
      chunks.push(new Uint8Array(current));
      current = [];
    }
    current.push(byte);
  }
  if (current.length) chunks.push(new Uint8Array(current));
  return chunks.map((chunk) => `=?UTF-8?B?${base64Bytes(chunk)}?=`).join("\r\n ");
}

function wrapBase64(value: string): string {
  return value.match(/.{1,76}/g)?.join("\r\n") || "";
}

function definitePreSendFailure(error: unknown): boolean {
  const message = error instanceof Error ? error.message : "";
  return message === "gmail_oauth_secrets_missing" || message === "gmail_oauth_refresh_rejected"
    || message === "gmail_oauth_access_token_missing" || message === "incident_gmail_sender_address_invalid"
    || message.startsWith("gmail_oauth_refresh_http_");
}

export class IncidentCoordinator {
  private readonly state: DurableObjectState;
  private readonly env: IncidentOpsEnv;

  constructor(state: DurableObjectState, env: IncidentOpsEnv) {
    this.state = state;
    this.env = env;
    const schema = `
      CREATE TABLE IF NOT EXISTS incidents (
        incident_id TEXT PRIMARY KEY, incident_type TEXT NOT NULL, component TEXT NOT NULL,
        root_cause TEXT NOT NULL, lifecycle TEXT NOT NULL, severity TEXT NOT NULL,
        generation INTEGER NOT NULL, state_version INTEGER NOT NULL,
        first_detected_at TEXT, observed_at TEXT NOT NULL, evidence_integrity TEXT NOT NULL,
        issue_numbers_json TEXT NOT NULL, last_notified_state_version INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS impacts (
        incident_id TEXT NOT NULL, impact_key TEXT NOT NULL, impact_type TEXT NOT NULL,
        impact_json TEXT NOT NULL, lifecycle TEXT NOT NULL, first_detected_at TEXT,
        observed_at TEXT NOT NULL, source_occurred_at TEXT, evidence_integrity TEXT NOT NULL,
        PRIMARY KEY (incident_id, impact_key)
      );
      CREATE TABLE IF NOT EXISTS incident_transitions (
        transition_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, generation INTEGER NOT NULL,
        state_version INTEGER NOT NULL, lifecycle TEXT NOT NULL, severity TEXT NOT NULL,
        disposition TEXT NOT NULL, observed_at TEXT NOT NULL, envelope_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS evidence (
        evidence_key TEXT PRIMARY KEY, incident_id TEXT NOT NULL, impact_key TEXT NOT NULL,
        repository TEXT NOT NULL, workflow TEXT NOT NULL, run_id INTEGER NOT NULL,
        attempt INTEGER NOT NULL, sha TEXT NOT NULL, artifact_id INTEGER,
        artifact_digest TEXT, observed_at TEXT NOT NULL, envelope_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS outbox (
        decision_key TEXT PRIMARY KEY, delivery_id TEXT NOT NULL UNIQUE,
        mode TEXT NOT NULL, window_key TEXT NOT NULL, state TEXT NOT NULL,
        message_id TEXT NOT NULL, content_sha256 TEXT NOT NULL, draft_id TEXT,
        gmail_message_id TEXT, reserved_at TEXT NOT NULL, updated_at TEXT NOT NULL, sent_at TEXT,
        inbox_verified_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        fallback_sent INTEGER NOT NULL DEFAULT 0, payload_json TEXT NOT NULL,
        lease_until TEXT, inbox_verification_state TEXT NOT NULL DEFAULT 'awaiting_inbox',
        inbox_last_checked_at TEXT, inbox_last_error TEXT,
        last_error TEXT
      );
      CREATE TABLE IF NOT EXISTS receipts (
        delivery_id TEXT PRIMARY KEY, gmail_message_id TEXT NOT NULL,
        receipt_state TEXT NOT NULL, observed_at TEXT NOT NULL, evidence_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS migration_snapshots (
        snapshot_id TEXT PRIMARY KEY, source TEXT NOT NULL, content_sha256 TEXT NOT NULL,
        imported_at TEXT NOT NULL, payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'importing', processed_count INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS shadow_decisions (
        decision_key TEXT PRIMARY KEY, mode TEXT NOT NULL, window_key TEXT NOT NULL,
        created_at TEXT NOT NULL, payload_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS legacy_confirmed_windows (
        decision_key TEXT PRIMARY KEY, window_key TEXT NOT NULL,
        recipient_hash TEXT NOT NULL, source TEXT NOT NULL,
        snapshot_id TEXT NOT NULL, confirmed_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS admin_fallbacks (
        delivery_id TEXT PRIMARY KEY, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_error TEXT
      );
      CREATE TABLE IF NOT EXISTS coordinator_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    `;
    for (const statement of schema.split(";").map((item) => item.trim()).filter(Boolean)) this.state.storage.sql.exec(statement);
    const outboxColumns = new Set(rows(this.state.storage.sql.exec<SqlRow>("PRAGMA table_info(outbox)")).map((row) => String(row.name)));
    if (!outboxColumns.has("lease_until")) this.state.storage.sql.exec("ALTER TABLE outbox ADD COLUMN lease_until TEXT");
    if (!outboxColumns.has("inbox_verification_state")) this.state.storage.sql.exec("ALTER TABLE outbox ADD COLUMN inbox_verification_state TEXT NOT NULL DEFAULT 'awaiting_inbox'");
    if (!outboxColumns.has("inbox_last_checked_at")) this.state.storage.sql.exec("ALTER TABLE outbox ADD COLUMN inbox_last_checked_at TEXT");
    if (!outboxColumns.has("inbox_last_error")) this.state.storage.sql.exec("ALTER TABLE outbox ADD COLUMN inbox_last_error TEXT");
    const migrationColumns = new Set(rows(this.state.storage.sql.exec<SqlRow>("PRAGMA table_info(migration_snapshots)")).map((row) => String(row.name)));
    if (!migrationColumns.has("status")) this.state.storage.sql.exec("ALTER TABLE migration_snapshots ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'");
    if (!migrationColumns.has("processed_count")) this.state.storage.sql.exec("ALTER TABLE migration_snapshots ADD COLUMN processed_count INTEGER NOT NULL DEFAULT 0");
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/internal/liveness" && request.method === "GET") {
        return response({ ok: true, component: "incident-coordinator", observed_at: new Date().toISOString() });
      }
      if (url.pathname === "/internal/evidence" && request.method === "POST") return await this.ingest(await request.json());
      if (url.pathname === "/internal/import" && request.method === "POST") return await this.importSnapshot(await request.json());
      if (url.pathname === "/internal/mail/verify" && request.method === "POST") return await this.verifyMail(await request.json());
      if (url.pathname === "/internal/mail-receipt" && request.method === "POST") return await this.recordReceipt(await request.json());
      if (url.pathname === "/internal/pending-receipts" && request.method === "GET") return this.pendingReceipts();
      if (url.pathname === "/internal/outbox/state" && request.method === "GET") return this.outboxState();
      if (url.pathname === "/internal/health" && request.method === "GET") return this.health();
      if (url.pathname === "/internal/tick" && request.method === "POST") return await this.tick();
      return response({ ok: false, error: "NOT_FOUND" }, 404);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "incident_coordinator_failed";
      return response({ ok: false, error: reason.slice(0, 180) }, 503);
    }
  }

  private async ingest(payload: unknown): Promise<Response> {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return response({ ok: false, error: "incident_envelope_batch_invalid" }, 400);
    const request = payload as Record<string, unknown>;
    const producerMode = String(request.producer_mode || "");
    const configuredMode = String(this.env.INCIDENT_OPS_MODE || "shadow").trim().toLowerCase();
    if (!new Set(["shadow", "live"]).has(producerMode) || producerMode !== configuredMode) {
      return response({ ok: false, error: "incident_ops_mode_mismatch" }, 409);
    }
    const list = request.envelopes;
    if (!Array.isArray(list) || list.length > 100) return response({ ok: false, error: "incident_envelope_batch_invalid" }, 400);
    const accepted: string[] = [];
    for (const raw of list) {
      const envelope = await validateEnvelope(raw);
      if (String((envelope.evidence as Array<Record<string, unknown>>)[0].repository).toLowerCase() !== String(this.env.INCIDENT_REPOSITORY || "").toLowerCase()) {
        return response({ ok: false, error: "incident_envelope_repository_mismatch" }, 403);
      }
      await this.storeEnvelope(envelope);
      accepted.push(String(envelope.impact_key));
      if (envelope.lifecycle === "active" && envelope.severity === "critical"
        && envelope.new_impact === true && envelope.evidence_integrity === "verified") {
        if (this.outboundEnabled()) await this.reserveCritical(envelope);
        else await this.recordShadowDecision(`critical|${String(envelope.incident_id)}|${String(envelope.generation)}`, "immediate_critical", String((envelope.times as Record<string, unknown>).observed_at), { impact_key: envelope.impact_key });
      }
    }
    return response({ ok: true, accepted_count: accepted.length, impact_keys: accepted });
  }

  private async storeEnvelope(envelope: Envelope, suppressNotification = false): Promise<void> {
    const incidentId = String(envelope.incident_id);
    const impactKey = String(envelope.impact_key);
    const time = envelope.times as Record<string, unknown>;
    const evidence = envelope.evidence as Array<Record<string, unknown>>;
    const issueNumbers = [...new Set(envelope.issue_numbers as number[])];
    const evidenceRows = await Promise.all(evidence.map(async (item) => ({
      item,
      key: await sha256(canonical({
        repository: item.repository, workflow: item.workflow, run_id: item.run_id,
        attempt: item.attempt, sha: item.sha, artifact_id: item.artifact_id || null,
        artifact_digest: item.artifact_digest || null,
      })),
    })));
    const now = new Date().toISOString();

    // All state transitions and evidence inserts commit together. The Durable
    // Object transaction is synchronous so no request can interleave between
    // the version check and the writes.
    this.state.storage.transactionSync(() => {
      const prior = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM incidents WHERE incident_id=?", incidentId))[0];
      const priorImpact = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM impacts WHERE incident_id=? AND impact_key=?", incidentId, impactKey))[0];
      const isNewImpact = !priorImpact && envelope.new_impact === true;
      const priorGeneration = Number(prior?.generation || 0);
      const generation = prior ? priorGeneration + (isNewImpact ? 1 : 0) : Number(envelope.generation);
      const priorLifecycle = String(prior?.lifecycle || "");
      const incomingLifecycle = String(envelope.lifecycle);
      const priorIsHistorical = priorLifecycle.startsWith("historical_");
      const incomingIsHistorical = incomingLifecycle.startsWith("historical_");
      const lifecycleAllowed = !prior || isNewImpact || (
        (priorIsHistorical && incomingIsHistorical && incomingLifecycle === priorLifecycle)
        || (!priorIsHistorical && !incomingIsHistorical
          && (LIFECYCLE_RANK[incomingLifecycle] || 0) >= (LIFECYCLE_RANK[priorLifecycle] || 0))
      );
      const versionAdvanced = !prior || Number(envelope.state_version) > Number(prior.state_version);
      const nextLifecycle = !prior ? incomingLifecycle
        : lifecycleAllowed && (versionAdvanced || isNewImpact) ? incomingLifecycle : priorLifecycle;
      const priorSeverity = String(prior?.severity || "info");
      const incomingSeverity = String(envelope.severity);
      const nextSeverity = !prior || (SEVERITY_RANK[incomingSeverity] || 0) > (SEVERITY_RANK[priorSeverity] || 0)
        ? incomingSeverity : priorSeverity;
      const priorEvidence = String(prior?.evidence_integrity || "unknown");
      const incomingEvidence = String(envelope.evidence_integrity);
      const nextEvidence = !prior || (EVIDENCE_RANK[incomingEvidence] || 0) > (EVIDENCE_RANK[priorEvidence] || 0)
        ? incomingEvidence : priorEvidence;
      const mergedIssues = [...new Set([
        ...(prior ? JSON.parse(String(prior.issue_numbers_json || "[]")) as number[] : []), ...issueNumbers,
      ])].sort((a, b) => a - b);
      let addedEvidence = false;
      for (const { item, key } of evidenceRows) {
        const existing = rows(this.state.storage.sql.exec<SqlRow>("SELECT evidence_key FROM evidence WHERE evidence_key=?", key)).length > 0;
        this.state.storage.sql.exec(
        `INSERT OR IGNORE INTO evidence (evidence_key,incident_id,impact_key,repository,workflow,run_id,attempt,sha,artifact_id,artifact_digest,observed_at,envelope_json)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`,
          key, incidentId, impactKey, item.repository, item.workflow, item.run_id, item.attempt, item.sha,
          item.artifact_id || null, item.artifact_digest || null, time.observed_at, JSON.stringify(envelope),
        );
        if (!existing) addedEvidence = true;
      }
      const priorIssues = prior ? JSON.parse(String(prior.issue_numbers_json || "[]")) as number[] : [];
      const issuesChanged = mergedIssues.length !== priorIssues.length;
      const lifecycleChanged = Boolean(prior && nextLifecycle !== priorLifecycle);
      const stateChanged = !prior || lifecycleChanged || nextSeverity !== priorSeverity
        || nextEvidence !== priorEvidence || isNewImpact || issuesChanged || addedEvidence;
      const stateVersion = prior ? Number(prior.state_version) + (stateChanged ? 1 : 0) : Number(envelope.state_version);
      const lastNotifiedVersion = Math.max(Number(prior?.last_notified_state_version || 0), suppressNotification ? stateVersion : 0);
      const firstDetected = minIso(prior?.first_detected_at, time.first_detected_at === "unknown" ? null : time.first_detected_at);
      const observedAt = maxIso(prior?.observed_at, time.observed_at) || time.observed_at;
      this.state.storage.sql.exec(
        `INSERT INTO incidents (incident_id,incident_type,component,root_cause,lifecycle,severity,generation,state_version,first_detected_at,observed_at,evidence_integrity,issue_numbers_json,last_notified_state_version,updated_at)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
         ON CONFLICT(incident_id) DO UPDATE SET lifecycle=excluded.lifecycle,severity=excluded.severity,generation=excluded.generation,state_version=excluded.state_version,first_detected_at=excluded.first_detected_at,observed_at=excluded.observed_at,evidence_integrity=excluded.evidence_integrity,issue_numbers_json=excluded.issue_numbers_json,updated_at=excluded.updated_at`,
        incidentId, envelope.incident_type, envelope.component, envelope.root_cause, nextLifecycle, nextSeverity,
        generation, stateVersion, firstDetected, observedAt, nextEvidence, JSON.stringify(mergedIssues),
        lastNotifiedVersion, stateChanged ? now : String(prior?.updated_at || now),
      );

      const priorImpactLifecycle = String(priorImpact?.lifecycle || "");
      const impactLifecycleAllowed = !priorImpact || isNewImpact || (
        !priorImpactLifecycle.startsWith("historical_") && !incomingIsHistorical
        && (LIFECYCLE_RANK[incomingLifecycle] || 0) >= (LIFECYCLE_RANK[priorImpactLifecycle] || 0)
      );
      const impactLifecycle = !priorImpact ? incomingLifecycle
        : impactLifecycleAllowed && (versionAdvanced || isNewImpact) ? incomingLifecycle : priorImpactLifecycle;
      const impactFirstDetected = minIso(priorImpact?.first_detected_at, time.first_detected_at === "unknown" ? null : time.first_detected_at);
      const impactObserved = maxIso(priorImpact?.observed_at, time.observed_at) || time.observed_at;
      const priorImpactEvidence = String(priorImpact?.evidence_integrity || "unknown");
      const impactEvidence = (EVIDENCE_RANK[incomingEvidence] || 0) > (EVIDENCE_RANK[priorImpactEvidence] || 0)
        ? incomingEvidence : priorImpactEvidence;
      this.state.storage.sql.exec(
        `INSERT INTO impacts (incident_id,impact_key,impact_type,impact_json,lifecycle,first_detected_at,observed_at,source_occurred_at,evidence_integrity)
         VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(incident_id,impact_key) DO UPDATE SET lifecycle=excluded.lifecycle,first_detected_at=excluded.first_detected_at,observed_at=excluded.observed_at,evidence_integrity=excluded.evidence_integrity`,
        incidentId, impactKey, envelope.impact_type, JSON.stringify(envelope.impact), impactLifecycle,
        impactFirstDetected, impactObserved,
        time.source_occurred_at === "unknown" ? null : time.source_occurred_at, impactEvidence,
      );
      const disposition = !prior ? "created" : generation > priorGeneration ? "new_generation"
        : stateChanged ? "state_advanced" : "evidence_replay";
      const transitionId = `${incidentId}:${generation}:${stateVersion}:${impactKey}:${evidenceRows.map(({ key }) => key).sort().join(",")}`;
      this.state.storage.sql.exec(
        `INSERT OR IGNORE INTO incident_transitions (transition_id,incident_id,generation,state_version,lifecycle,severity,disposition,observed_at,envelope_json)
         VALUES (?,?,?,?,?,?,?,?,?)`,
        transitionId, incidentId, generation, stateVersion, nextLifecycle, nextSeverity, disposition,
        time.observed_at, JSON.stringify(envelope),
      );
    });
  }

  private async reserveCritical(envelope: Envelope): Promise<void> {
    const incidentId = String(envelope.incident_id);
    const row = rows(this.state.storage.sql.exec<SqlRow>("SELECT generation FROM incidents WHERE incident_id=?", incidentId))[0];
    const generation = Number(row?.generation || envelope.generation);
    const key = `critical|${incidentId}|${generation}|${await sha256(RECIPIENT)}`;
    const payload = { items: [{
      incident_id: incidentId, component: envelope.component, root_cause: envelope.root_cause,
      severity: envelope.severity, lifecycle: envelope.lifecycle,
      issue_numbers: envelope.issue_numbers, impact_key: envelope.impact_key,
    }], incident_versions: [{ incident_id: incidentId, state_version: Number(envelope.state_version) }],
    subject: `[PRStK 異常] ${String(envelope.component)}：新重大影響`, mode: "immediate_critical" };
    await this.reserveDecision(key, "immediate_critical", new Date().toISOString(), payload);
  }

  private async reserveDecision(key: string, mode: string, window: string, payload: Record<string, unknown>): Promise<void> {
    const now = new Date().toISOString();
    const deliveryId = await sha256(key);
    const messageId = `<${deliveryId}@prstk.invalid>`;
    const content = this.renderText(payload);
    const subject = String(payload.subject || "[PRStK] 通知");
    const contentHash = await sha256(canonical({ recipient: RECIPIENT, messageId, subject, content }));
    const mailConfigMissing = !this.env.INCIDENT_GMAIL_OAUTH_CLIENT_ID || !this.env.INCIDENT_GMAIL_OAUTH_CLIENT_SECRET
      || !this.env.INCIDENT_GMAIL_REFRESH_TOKEN || !this.env.INCIDENT_GMAIL_FROM
      || !this.env.INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_ID || !this.env.INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_SECRET
      || !this.env.INCIDENT_RECEIPT_GMAIL_REFRESH_TOKEN || !this.env.INCIDENT_RECEIPT_GMAIL_ADDRESS;
    const reservation = this.state.storage.transactionSync(() => {
      if (rows(this.state.storage.sql.exec<SqlRow>("SELECT decision_key FROM legacy_confirmed_windows WHERE decision_key=?", key)).length) {
        return { created: false, capped: false, legacyConfirmed: true, configMissing: false };
      }
      const existing = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE decision_key=?", key))[0];
      if (existing) return {
        created: false,
        capped: String(existing.state) === "failed_not_sent" && String(existing.last_error || "").includes("rolling_24h_mail_limit"),
        legacyConfirmed: false,
        configMissing: String(existing.state) === "failed_not_sent" && String(existing.last_error || "").includes("required_gmail_oauth_secrets_missing"),
      };
      const mailCount = Number(rows(this.state.storage.sql.exec<SqlRow>(
        "SELECT COUNT(*) AS n FROM outbox WHERE reserved_at >= ?", new Date(Date.now() - 86400_000).toISOString(),
      ))[0]?.n || 0);
      const capped = mailCount >= MAX_MAILS_PER_24H;
      const configMissing = !capped && mailConfigMissing;
      const initialState = capped || configMissing ? "failed_not_sent" : "reserved";
      this.state.storage.sql.exec(
        `INSERT INTO outbox (decision_key,delivery_id,mode,window_key,state,message_id,content_sha256,reserved_at,updated_at,payload_json,last_error)
         VALUES (?,?,?,?,?,?,?,?,?,?,?)`,
        key, deliveryId, mode, window, initialState, messageId, contentHash, now, now,
        JSON.stringify({ ...payload, subject, content }), capped ? "rolling_24h_mail_limit_reached" : configMissing ? "required_gmail_oauth_secrets_missing" : null,
      );
      return { created: true, capped, legacyConfirmed: false, configMissing };
    });
    if (reservation.legacyConfirmed) return;
    const current = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE decision_key=?", key))[0];
    if (current && ["reserved", "draft_creating", "draft_ready", "sending", "reconciling", "delivery_unknown"].includes(String(current.state))) {
      await this.advanceOutbox(current);
    } else if (reservation.created && reservation.capped) {
      await this.notifyAdminFallback("PRStK Gmail 每 24 小時安全上限已達 100 封；本決策未寄出，請檢查通知量。", deliveryId);
    } else if (reservation.created && reservation.configMissing) {
      await this.notifyAdminFallback("PRStK 集中郵件尚未具備完整寄件及收件匣核驗授權；本決策已保留但未寄出。", `config:${deliveryId}`);
    } else if (reservation.created && !reservation.capped) {
      const mailCount = Number(rows(this.state.storage.sql.exec<SqlRow>(
        "SELECT COUNT(*) AS n FROM outbox WHERE reserved_at >= ?", new Date(Date.now() - 86400_000).toISOString(),
      ))[0]?.n || 0);
      if (mailCount >= WARN_MAILS_PER_24H) await this.notifyQuotaWarningOnce();
    }
  }

  private claimOutbox(deliveryId: string, expectedState: string, nextState: string): SqlRow | null {
    const now = new Date().toISOString();
    return this.state.storage.transactionSync(() => {
      const row = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE delivery_id=?", deliveryId))[0];
      if (!row || String(row.state) !== expectedState) return null;
      this.state.storage.sql.exec(
        "UPDATE outbox SET state=?,updated_at=?,lease_until=?,attempts=attempts+1 WHERE delivery_id=? AND state=?",
        nextState, now, new Date(Date.now() + OUTBOX_LEASE_MS).toISOString(), deliveryId, expectedState,
      );
      return rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE delivery_id=?", deliveryId))[0] || null;
    });
  }

  private async clearOutboxLease(deliveryId: string, state: string, reason: string | null = null): Promise<void> {
    this.state.storage.sql.exec(
      "UPDATE outbox SET state=?,updated_at=?,lease_until=NULL,last_error=? WHERE delivery_id=?",
      state, new Date().toISOString(), reason ? reason.slice(0, 180) : null, deliveryId,
    );
  }

  private renderText(payload: Record<string, unknown>): string {
    if (payload.mode === "owner_link_verification") {
      return [
        "PRStK 告警郵件鏈路驗證",
        "",
        "這是一封由管理員明確觸發的驗證郵件，不代表市場事件或正式事故。",
        `驗證身份：${String(payload.verification_id || "未知")}`,
        "寄件核實與收件匣實收核實分開記錄。",
      ].join("\n");
    }
    const lines = ["PRStK 集中事故通知", "", "此郵件只代表列出的事故證據與通知決策。寄件核實不等於收件匣核實。"];
    for (const item of (payload.items as Array<Record<string, unknown>> || [])) {
      lines.push("", `元件：${String(item.component || "未知")}`, `狀態：${String(item.lifecycle || "未知")}`,
        `根因：${String(item.root_cause || "未知")}`, `事故：${String(item.incident_id || "未知")}`,
        `影響鍵：${String(item.impact_key || "未知")}`, `Issue：${Array.isArray(item.issue_numbers) ? item.issue_numbers.join(", ") : "無"}`);
    }
    return lines.join("\n");
  }

  private mimeMessage(messageId: string, subject: string, content: string): string {
    const from = safeHeader(String(this.env.INCIDENT_GMAIL_FROM || ""));
    if (!/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$/.test(from)) {
      throw new Error("incident_gmail_sender_address_invalid");
    }
    const safeSubject = encodedWord(subject);
    const body = wrapBase64(base64Bytes(TEXT.encode(content)));
    return [
      `From: ${from}`, `To: ${RECIPIENT}`, `Subject: ${safeSubject}`, `Message-ID: ${messageId}`,
      "MIME-Version: 1.0", "Content-Type: text/plain; charset=UTF-8", "Content-Transfer-Encoding: base64", "",
      body,
    ].join("\r\n");
  }

  private async gmailAccessToken(): Promise<string> {
    const { INCIDENT_GMAIL_OAUTH_CLIENT_ID: clientId, INCIDENT_GMAIL_OAUTH_CLIENT_SECRET: clientSecret, INCIDENT_GMAIL_REFRESH_TOKEN: refreshToken } = this.env;
    if (!clientId || !clientSecret || !refreshToken || !this.env.INCIDENT_GMAIL_FROM) throw new Error("gmail_oauth_secrets_missing");
    const body = new URLSearchParams({ client_id: clientId, client_secret: clientSecret, refresh_token: refreshToken, grant_type: "refresh_token" });
    const response = await fetch("https://oauth2.googleapis.com/token", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body, signal: AbortSignal.timeout(10_000) });
    if (!response.ok) throw new Error(response.status === 400 ? "gmail_oauth_refresh_rejected" : `gmail_oauth_refresh_http_${response.status}`);
    const payload = await response.json() as { access_token?: string };
    if (!payload.access_token) throw new Error("gmail_oauth_access_token_missing");
    return payload.access_token;
  }

  private async gmailRequest(path: string, token: string, init: RequestInit = {}): Promise<Response> {
    return fetch(`https://gmail.googleapis.com/gmail/v1/users/me/${path}`, {
      ...init, signal: init.signal || AbortSignal.timeout(10_000),
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json", ...(init.headers || {}) },
    });
  }

  private async advanceOutbox(row: SqlRow): Promise<void> {
    const state = String(row.state);
    if (state === "delivery_unknown" || state === "sending" || state === "reconciling" || state === "draft_creating") {
      await this.reconcileUnknown(row);
      return;
    }
    if (state === "reserved") {
      await this.createDraft(row);
      return;
    }
    if (state === "draft_ready") await this.sendDraft(row);
  }

  private async createDraft(row: SqlRow): Promise<void> {
    const deliveryId = String(row.delivery_id);
    const claimed = this.claimOutbox(deliveryId, "reserved", "draft_creating");
    if (!claimed) return;
    try {
      const token = await this.gmailAccessToken();
      const payload = JSON.parse(String(claimed.payload_json)) as Record<string, unknown>;
      const raw = this.mimeMessage(String(claimed.message_id), String(payload.subject || "[PRStK] 通知"), String(payload.content || ""));
      const response = await this.gmailRequest("drafts", token, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ message: { raw: b64url(raw) } }) });
      if (!response.ok) {
        if (response.status >= 500 || response.status === 429) await this.clearOutboxLease(deliveryId, "delivery_unknown", `gmail_draft_http_${response.status}`);
        else await this.clearOutboxLease(deliveryId, "failed_not_sent", `gmail_draft_http_${response.status}`);
        if (response.status < 500 && response.status !== 429) await this.notifyAdminFallback(`PRStK Gmail 草稿建立明確失敗 (${response.status})。`, deliveryId);
        return;
      }
      const result = await response.json() as { id?: string };
      if (!result.id) {
        await this.clearOutboxLease(deliveryId, "delivery_unknown", "gmail_draft_id_missing");
        return;
      }
      this.state.storage.sql.exec("UPDATE outbox SET state='draft_ready',draft_id=?,updated_at=?,lease_until=NULL,last_error=NULL WHERE delivery_id=? AND state='draft_creating'", result.id, new Date().toISOString(), deliveryId);
      const updated = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE delivery_id=?", deliveryId))[0];
      if (updated?.state === "draft_ready" && updated.draft_id === result.id) await this.sendDraft(updated);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "gmail_draft_transport_unknown";
      await this.clearOutboxLease(deliveryId, definitePreSendFailure(error) ? "failed_not_sent" : "delivery_unknown", reason);
      if (definitePreSendFailure(error)) await this.notifyAdminFallback(`PRStK Gmail 草稿建立前的帳號授權失敗 (${reason})。`, deliveryId);
    }
  }

  private async sendDraft(row: SqlRow): Promise<void> {
    const deliveryId = String(row.delivery_id);
    const claimed = this.claimOutbox(deliveryId, "draft_ready", "sending");
    if (!claimed) return;
    const draftId = String(claimed.draft_id || "");
    if (!draftId) {
      await this.clearOutboxLease(deliveryId, "delivery_unknown", "gmail_draft_identity_missing");
      return;
    }
    try {
      const token = await this.gmailAccessToken();
      const response = await this.gmailRequest("drafts/send", token, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id: draftId }) });
      if (!response.ok) {
        if (response.status >= 500 || response.status === 429 || response.status === 404) await this.clearOutboxLease(deliveryId, "delivery_unknown", `gmail_send_http_${response.status}`);
        else {
          await this.clearOutboxLease(deliveryId, "failed_not_sent", `gmail_send_http_${response.status}`);
          await this.notifyAdminFallback(`PRStK Gmail 草稿寄送明確遭拒 (${response.status})。`, deliveryId);
        }
        return;
      }
      const sent = await response.json() as { id?: string; labelIds?: string[] };
      if (!sent.id) {
        await this.clearOutboxLease(deliveryId, "delivery_unknown", "gmail_send_response_unverified");
        return;
      }
      const verify = await this.gmailRequest(`messages/${encodeURIComponent(sent.id)}?format=metadata&metadataHeaders=Message-ID`, token);
      const detail = verify.ok ? await verify.json() as { id?: string; labelIds?: string[]; payload?: { headers?: Array<{ name?: string; value?: string }> } } : null;
      const header = detail?.payload?.headers?.find((item) => String(item.name || "").toLowerCase() === "message-id")?.value;
      if (!detail || detail.id !== sent.id || !detail.labelIds?.includes("SENT") || header !== String(row.message_id)) {
        await this.clearOutboxLease(deliveryId, "delivery_unknown", "gmail_sent_readback_mismatch");
        return;
      }
      await this.markSent(row, sent.id);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "gmail_send_transport_unknown";
      await this.clearOutboxLease(deliveryId, definitePreSendFailure(error) ? "failed_not_sent" : "delivery_unknown", reason);
      if (definitePreSendFailure(error)) await this.notifyAdminFallback(`PRStK Gmail 寄送前的帳號授權失敗 (${reason})。`, deliveryId);
    }
  }

  private async reconcileUnknown(row: SqlRow): Promise<void> {
    const deliveryId = String(row.delivery_id);
    const claimed = this.state.storage.transactionSync(() => {
      const current = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE delivery_id=?", deliveryId))[0];
      if (!current || !["sending", "draft_creating", "delivery_unknown", "reconciling"].includes(String(current.state))) return null;
      const leaseUntil = Date.parse(String(current.lease_until || ""));
      if (Number.isFinite(leaseUntil) && leaseUntil > Date.now()) return null;
      const now = new Date().toISOString();
      this.state.storage.sql.exec(
        "UPDATE outbox SET state='reconciling',updated_at=?,lease_until=?,attempts=attempts+1 WHERE delivery_id=?",
        now, new Date(Date.now() + OUTBOX_LEASE_MS).toISOString(), deliveryId,
      );
      return rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE delivery_id=?", deliveryId))[0] || null;
    });
    if (!claimed) return;
    try {
      const token = await this.gmailAccessToken();
      const query = new URLSearchParams({ q: `in:sent rfc822msgid:${String(claimed.message_id).slice(1, -1)}`, maxResults: "10" });
      const found = await this.gmailRequest(`messages?${query.toString()}`, token);
      if (!found.ok) {
        await this.clearOutboxLease(deliveryId, "delivery_unknown", `gmail_sent_search_http_${found.status}`);
        return;
      }
      const list = await found.json() as { messages?: Array<{ id?: string }> };
      for (const candidate of list.messages || []) {
        if (!candidate.id) continue;
        const detailResponse = await this.gmailRequest(`messages/${encodeURIComponent(candidate.id)}?format=metadata&metadataHeaders=Message-ID`, token);
        if (!detailResponse.ok) {
          await this.clearOutboxLease(deliveryId, "delivery_unknown", `gmail_sent_readback_http_${detailResponse.status}`);
          return;
        }
        const detail = await detailResponse.json() as { id?: string; labelIds?: string[]; payload?: { headers?: Array<{ name?: string; value?: string }> } };
        const header = detail.payload?.headers?.find((item) => String(item.name || "").toLowerCase() === "message-id")?.value;
        if (header === String(claimed.message_id) && detail.labelIds?.includes("SENT")) {
          await this.markSent(claimed, String(detail.id || candidate.id));
          return;
        }
      }
      // If draft creation or its response was interrupted, search by the
      // immutable RFC Message-ID. A uniquely matched draft is safe to resume;
      // never build a second draft with a new identity.
      const draftsQuery = new URLSearchParams({ q: `rfc822msgid:${String(claimed.message_id).slice(1, -1)}`, maxResults: "10" });
      const draftsResponse = await this.gmailRequest(`drafts?${draftsQuery.toString()}`, token);
      if (!draftsResponse.ok) {
        await this.clearOutboxLease(deliveryId, "delivery_unknown", `gmail_draft_search_http_${draftsResponse.status}`);
        return;
      }
      const drafts = await draftsResponse.json() as { drafts?: Array<{ id?: string }> };
      const matching: Array<{ id: string }> = [];
      for (const draft of drafts.drafts || []) {
        if (!draft.id) continue;
        const detailResponse = await this.gmailRequest(`drafts/${encodeURIComponent(draft.id)}?format=full`, token);
        if (!detailResponse.ok) {
          await this.clearOutboxLease(deliveryId, "delivery_unknown", `gmail_draft_readback_http_${detailResponse.status}`);
          return;
        }
        const detail = await detailResponse.json() as { id?: string; message?: { payload?: { headers?: Array<{ name?: string; value?: string }> } } };
        const header = detail.message?.payload?.headers?.find((item) => String(item.name || "").toLowerCase() === "message-id")?.value;
        if (detail.id === draft.id && header === String(claimed.message_id)) matching.push({ id: draft.id });
      }
      if (matching.length === 1) {
        this.state.storage.sql.exec("UPDATE outbox SET state='draft_ready',draft_id=?,updated_at=?,lease_until=NULL,last_error=NULL WHERE delivery_id=? AND state='reconciling'", matching[0].id, new Date().toISOString(), deliveryId);
        const updated = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE delivery_id=?", deliveryId))[0];
        if (updated) await this.sendDraft(updated);
        return;
      }
      if (matching.length > 1) {
        await this.clearOutboxLease(deliveryId, "delivery_unknown", "gmail_draft_identity_ambiguous");
        return;
      }
    } catch (error) {
      // Keep the same fixed delivery identity in delivery_unknown; never blind-resend.
      const reason = error instanceof Error ? error.message.replace(/[\r\n\u0000-\u001f]/g, " ").slice(0, 120) : "unknown";
      await this.clearOutboxLease(deliveryId, "delivery_unknown", `gmail_readback_error:${reason}`);
      return;
    }
    const updatedAt = Date.parse(String(claimed.reserved_at));
    await this.clearOutboxLease(deliveryId, "delivery_unknown", "gmail_readback_not_found_or_unavailable");
    if (Number.isFinite(updatedAt) && Date.now() - updatedAt >= UNKNOWN_GRACE_MS) {
      await this.notifyAdminFallback(`PRStK Gmail 寄送結果五分鐘仍無法核實；此決策已停止自動重寄。 delivery_id=${deliveryId}`, `send:${deliveryId}`);
      this.state.storage.sql.exec("UPDATE outbox SET fallback_sent=1 WHERE delivery_id=?", deliveryId);
    }
  }

  private async markSent(row: SqlRow, gmailMessageId: string): Promise<void> {
    const now = new Date().toISOString();
    const payload = JSON.parse(String(row.payload_json)) as { incident_versions?: Array<{ incident_id: string; state_version: number }> };
    this.state.storage.transactionSync(() => {
      this.state.storage.sql.exec("UPDATE outbox SET state='sent_verified',gmail_message_id=?,sent_at=?,updated_at=?,lease_until=NULL,last_error=NULL WHERE delivery_id=? AND state IN ('sending','reconciling')", gmailMessageId, now, now, row.delivery_id);
      for (const item of payload.incident_versions || []) {
        this.state.storage.sql.exec("UPDATE incidents SET last_notified_state_version=MAX(last_notified_state_version,?) WHERE incident_id=?", item.state_version, item.incident_id);
      }
    });
  }

  private async setOutbox(deliveryId: string, state: string, reason: string): Promise<void> {
    this.state.storage.sql.exec("UPDATE outbox SET state=?,updated_at=?,lease_until=NULL,last_error=? WHERE delivery_id=?", state, new Date().toISOString(), reason.slice(0, 180), deliveryId);
  }

  private async notifyAdminFallback(message: string, deliveryId: string): Promise<void> {
    const now = new Date().toISOString();
    const claimed = this.state.storage.transactionSync(() => {
      if (rows(this.state.storage.sql.exec<SqlRow>("SELECT delivery_id FROM admin_fallbacks WHERE delivery_id=?", deliveryId)).length) return false;
      this.state.storage.sql.exec(
        "INSERT INTO admin_fallbacks (delivery_id,status,created_at,updated_at,last_error) VALUES (?,?,?,?,NULL)",
        deliveryId, "reserved", now, now,
      );
      return true;
    });
    if (!claimed) return;
    const token = String(this.env.INCIDENT_TELEGRAM_BOT_TOKEN || "").trim();
    const admin = String(this.env.INCIDENT_TELEGRAM_ADMIN_CHAT_ID || "").trim();
    if (!token || !/^\d+$/.test(admin)) {
      this.state.storage.sql.exec("UPDATE admin_fallbacks SET status='not_configured',updated_at=?,last_error=? WHERE delivery_id=?", new Date().toISOString(), "telegram_admin_secret_missing", deliveryId);
      return;
    }
    try {
      const result = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id: admin, text: `${message}\nkey=${deliveryId}`, disable_web_page_preview: true }),
        signal: AbortSignal.timeout(8000),
      });
      this.state.storage.sql.exec(
        "UPDATE admin_fallbacks SET status=?,updated_at=?,last_error=? WHERE delivery_id=?",
        result.ok ? "sent" : "failed_not_sent", new Date().toISOString(), result.ok ? null : `telegram_http_${result.status}`, deliveryId,
      );
    } catch (error) {
      const reason = error instanceof Error ? error.message : "telegram_transport_unknown";
      this.state.storage.sql.exec("UPDATE admin_fallbacks SET status='delivery_unknown',updated_at=?,last_error=? WHERE delivery_id=?", new Date().toISOString(), reason.slice(0, 180), deliveryId);
    }
  }

  private async notifyQuotaWarningOnce(): Promise<void> {
    const day = new Date().toISOString().slice(0, 10);
    const key = `quota-warning:${day}`;
    if (rows(this.state.storage.sql.exec<SqlRow>("SELECT key FROM coordinator_meta WHERE key=?", key)).length) return;
    await this.notifyAdminFallback("PRStK Gmail 24 小時用量已達 80 封；依安全上限不會啟用付費或超額扣款。", key);
    this.state.storage.sql.exec("INSERT OR IGNORE INTO coordinator_meta (key,value) VALUES (?,?)", key, new Date().toISOString());
  }

  private async tick(): Promise<Response> {
    const now = new Date();
    const window = windowKey(now);
    const active = rows(this.state.storage.sql.exec<SqlRow>(
      `SELECT incident_id,component,root_cause,lifecycle,severity,generation,state_version,issue_numbers_json
       FROM incidents WHERE lifecycle IN ('active','recovery_pending')
       ORDER BY severity='critical' DESC, updated_at ASC LIMIT 100`,
    ));
    const recovered = rows(this.state.storage.sql.exec<SqlRow>(
      `SELECT incident_id,component,root_cause,lifecycle,severity,generation,state_version,issue_numbers_json
       FROM incidents WHERE lifecycle='recovered' AND state_version>last_notified_state_version ORDER BY updated_at ASC LIMIT 100`,
    ));
    const items = [...active, ...recovered].map((row) => ({
      incident_id: row.incident_id, component: row.component, root_cause: row.root_cause,
      lifecycle: row.lifecycle, severity: row.severity, generation: row.generation,
      state_version: row.state_version, issue_numbers: JSON.parse(String(row.issue_numbers_json || "[]")),
    }));
    if (items.length) {
      const recipientKey = await sha256(RECIPIENT);
      const key = `ordinary|${window}|gmail|${recipientKey}`;
      const versions = items.map((item) => ({ incident_id: item.incident_id, state_version: item.state_version }));
      const payload = {
        mode: "half_hour_digest", subject: `[PRStK] 事故摘要 ${window}`, items,
        incident_versions: versions,
      };
      if (this.outboundEnabled()) await this.reserveDecision(key, "half_hour_digest", window, payload);
      else await this.recordShadowDecision(key, "half_hour_digest", window, { ...payload, recipient: RECIPIENT });
    }
    await this.reconcileUnknownRows();
    const receiptCheck = await this.verifyPendingReceipts();
    return response({ ok: true, window_key: window, active_incidents: active.length, recovery_notices: recovered.length, inbox_receipts_checked: receiptCheck.checked, inbox_receipts_verified: receiptCheck.verified });
  }

  private async reconcileUnknownRows(): Promise<void> {
    const pending = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT * FROM outbox WHERE state IN ('reserved','draft_creating','draft_ready','sending','reconciling','delivery_unknown') ORDER BY reserved_at LIMIT 20",
    ));
    for (const row of pending) await this.advanceOutbox(row);
  }

  private async verifyPendingReceipts(): Promise<{ checked: number; verified: number }> {
    const pending = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT delivery_id FROM outbox WHERE state='sent_verified' AND inbox_verified_at IS NULL ORDER BY sent_at LIMIT 20",
    ));
    let verified = 0;
    for (const row of pending) {
      const result = await this.verifyInboxReceipt(String(row.delivery_id || ""));
      if (result.receipt_state === "inbox_verified") verified += 1;
    }
    return { checked: pending.length, verified };
  }

  private async receiptAccessToken(): Promise<string> {
    const { INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_ID: clientId, INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_SECRET: clientSecret, INCIDENT_RECEIPT_GMAIL_REFRESH_TOKEN: refreshToken } = this.env;
    if (!clientId || !clientSecret || !refreshToken || !this.env.INCIDENT_RECEIPT_GMAIL_ADDRESS) throw new Error("gmail_receipt_oauth_secrets_missing");
    const body = new URLSearchParams({ client_id: clientId, client_secret: clientSecret, refresh_token: refreshToken, grant_type: "refresh_token" });
    const response = await fetch("https://oauth2.googleapis.com/token", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body, signal: AbortSignal.timeout(10_000) });
    if (!response.ok) throw new Error(response.status === 400 ? "gmail_receipt_oauth_refresh_rejected" : `gmail_receipt_oauth_refresh_http_${response.status}`);
    const payload = await response.json() as { access_token?: string };
    if (!payload.access_token) throw new Error("gmail_receipt_oauth_access_token_missing");
    return payload.access_token;
  }

  private async verifyInboxReceipt(deliveryId: string): Promise<Record<string, unknown>> {
    if (!/^[0-9a-f]{64}$/.test(deliveryId)) return { ok: false, error: "receipt_delivery_id_invalid" };
    const row = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE delivery_id=?", deliveryId))[0];
    if (!row || row.state !== "sent_verified" || !row.gmail_message_id) return { ok: false, error: "receipt_not_bound_to_sent_message" };
    if (row.inbox_verified_at) return { ok: true, delivery_id: deliveryId, receipt_state: "inbox_verified", idempotent: true };
    const checkedAt = new Date().toISOString();
    const sentAt = Date.parse(String(row.sent_at || ""));
    const aged = Number.isFinite(sentAt) && Date.now() - sentAt >= UNKNOWN_GRACE_MS;
    const setReceiptState = (state: string, reason: string | null) => this.state.storage.sql.exec(
      "UPDATE outbox SET inbox_verification_state=?,inbox_last_checked_at=?,inbox_last_error=?,updated_at=? WHERE delivery_id=?",
      state, checkedAt, reason, checkedAt, deliveryId,
    );
    try {
      const token = await this.receiptAccessToken();
      const profileResponse = await this.gmailRequest("profile", token);
      const profile = profileResponse.ok ? await profileResponse.json() as { emailAddress?: string } : null;
      if (!profile?.emailAddress || profile.emailAddress.toLowerCase() !== String(this.env.INCIDENT_RECEIPT_GMAIL_ADDRESS || "").toLowerCase()
        || profile.emailAddress.toLowerCase() !== RECIPIENT) {
        setReceiptState("verification_unavailable", "gmail_receipt_account_identity_mismatch");
        if (aged) await this.notifyAdminFallback("PRStK 收件匣回執帳號身份不符；郵件寄件已核實，但收件匣尚未核實。", `receipt:${deliveryId}`);
        return { ok: false, error: "gmail_receipt_account_identity_mismatch", receipt_state: "verification_unavailable" };
      }
      const rfcMessageId = String(row.message_id || "");
      const query = new URLSearchParams({
        q: `in:inbox to:${RECIPIENT} rfc822msgid:${rfcMessageId.slice(1, -1)}`,
        maxResults: "50",
      });
      const search = await this.gmailRequest(`messages?${query.toString()}`, token);
      if (!search.ok) {
        setReceiptState("verification_unavailable", `gmail_inbox_search_http_${search.status}`);
        if (aged) await this.notifyAdminFallback("PRStK 收件匣查核服務目前不可用；郵件寄件已核實，沒有自動重寄。", `receipt:${deliveryId}`);
        return { ok: false, error: `gmail_inbox_search_http_${search.status}`, receipt_state: "verification_unavailable" };
      }
      const found = await search.json() as { messages?: Array<{ id?: string }>; nextPageToken?: string; resultSizeEstimate?: number };
      if (found.nextPageToken || Number(found.resultSizeEstimate || 0) > (found.messages || []).length) {
        setReceiptState("verification_incomplete", "gmail_inbox_search_result_truncated");
        if (aged) await this.notifyAdminFallback("PRStK 收件匣回執結果超過單次查核範圍；已保留未確認狀態，沒有自動重寄。", `receipt:${deliveryId}`);
        return { ok: false, delivery_id: deliveryId, receipt_state: "verification_incomplete" };
      }
      const matches: Array<{ gmailMessageId: string; evidence: Record<string, unknown> }> = [];
      for (const candidate of found.messages || []) {
        if (!candidate.id) continue;
        const params = new URLSearchParams({ format: "metadata" });
        for (const name of ["Message-ID", "To", "Delivered-To", "From"]) params.append("metadataHeaders", name);
        const detailResponse = await this.gmailRequest(`messages/${encodeURIComponent(candidate.id)}?${params.toString()}`, token);
        if (!detailResponse.ok) {
          setReceiptState("verification_unavailable", `gmail_inbox_readback_http_${detailResponse.status}`);
          if (aged) await this.notifyAdminFallback("PRStK 收件匣回執查核未完成；郵件寄件已核實，沒有自動重寄。", `receipt:${deliveryId}`);
          return { ok: false, error: `gmail_inbox_readback_http_${detailResponse.status}`, receipt_state: "verification_unavailable" };
        }
        const detail = await detailResponse.json() as {
          id?: string; labelIds?: string[];
          payload?: { headers?: Array<{ name?: string; value?: string }> };
        };
        const header = (name: string) => detail.payload?.headers?.find((item) => String(item.name || "").toLowerCase() === name.toLowerCase())?.value || "";
        const toHeader = header("To").toLowerCase();
        const deliveredTo = header("Delivered-To").toLowerCase();
        const fromHeader = header("From");
        const toMatches = headerHasAddress(toHeader, RECIPIENT) || deliveredTo === RECIPIENT;
        if (detail.id === candidate.id && detail.labelIds?.includes("INBOX")
          && header("Message-ID") === rfcMessageId && toMatches && headerHasAddress(fromHeader, String(this.env.INCIDENT_GMAIL_FROM || ""))) {
          const evidence: Record<string, unknown> = {
            receipt_state: "inbox_verified", delivery_id: deliveryId, gmail_message_id: detail.id,
            rfc_message_id: rfcMessageId, recipient: RECIPIENT, to: RECIPIENT,
            from: this.env.INCIDENT_GMAIL_FROM, inbox_label: true, observed_at: checkedAt,
          };
          matches.push({ gmailMessageId: detail.id, evidence });
        }
      }
      if (matches.length > 1) {
        const evidence = { delivery_id: deliveryId, receipt_state: "duplicate_inbox_messages", gmail_message_ids: matches.map((item) => item.gmailMessageId), observed_at: checkedAt };
        setReceiptState("duplicate_inbox_messages", "multiple_inbox_messages_match_one_delivery_id");
        this.state.storage.sql.exec(
          "INSERT OR REPLACE INTO receipts (delivery_id,gmail_message_id,receipt_state,observed_at,evidence_json) VALUES (?,?,?,?,?)",
          deliveryId, matches[0].gmailMessageId, "duplicate_inbox_messages", checkedAt, JSON.stringify(evidence),
        );
        await this.notifyAdminFallback("PRStK 收件匣找到多封具有相同固定 Message-ID 的郵件；可能發生重送，請人工核對。", `duplicate:${deliveryId}`);
        return { ok: false, delivery_id: deliveryId, receipt_state: "duplicate_inbox_messages", matching_messages: matches.length };
      }
      if (matches.length === 1) {
        const { gmailMessageId, evidence } = matches[0];
        this.state.storage.transactionSync(() => {
          this.state.storage.sql.exec(
            "UPDATE outbox SET inbox_verified_at=?,inbox_verification_state='inbox_verified',inbox_last_checked_at=?,inbox_last_error=NULL,updated_at=? WHERE delivery_id=? AND state='sent_verified'",
            checkedAt, checkedAt, checkedAt, deliveryId,
          );
          this.state.storage.sql.exec(
            "INSERT OR REPLACE INTO receipts (delivery_id,gmail_message_id,receipt_state,observed_at,evidence_json) VALUES (?,?,?,?,?)",
            deliveryId, gmailMessageId, "inbox_verified", checkedAt, JSON.stringify(evidence),
          );
        });
        return { ok: true, delivery_id: deliveryId, receipt_state: "inbox_verified", gmail_message_id: gmailMessageId };
      }
      setReceiptState(aged ? "not_visible_after_grace" : "awaiting_inbox", null);
      if (aged) await this.notifyAdminFallback("PRStK Gmail 寄件已核實，但五分鐘後仍未在收件匣找到同一 Message-ID；已停止自動重寄。", `receipt:${deliveryId}`);
      return { ok: true, delivery_id: deliveryId, receipt_state: aged ? "not_visible_after_grace" : "awaiting_inbox" };
    } catch (error) {
      const reason = error instanceof Error ? error.message.slice(0, 160) : "gmail_inbox_verification_unknown";
      setReceiptState("verification_unavailable", reason);
      if (aged) await this.notifyAdminFallback("PRStK 收件匣回執五分鐘仍無法核實；郵件寄件已核實，沒有自動重寄。", `receipt:${deliveryId}`);
      return { ok: false, delivery_id: deliveryId, receipt_state: "verification_unavailable", error: reason };
    }
  }

  private async recordReceipt(payload: unknown): Promise<Response> {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return response({ ok: false, error: "receipt_invalid" }, 400);
    const value = payload as Record<string, unknown>;
    const deliveryId = String(value.delivery_id || "");
    if (Object.keys(value).some((key) => key !== "delivery_id") || !/^[0-9a-f]{64}$/.test(deliveryId)) {
      return response({ ok: false, error: "receipt_contract_invalid" }, 400);
    }
    return response(await this.verifyInboxReceipt(deliveryId));
  }

  private async importSnapshot(payload: unknown): Promise<Response> {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return response({ ok: false, error: "legacy_snapshot_invalid" }, 400);
    const value = payload as Record<string, unknown>;
    const source = String(value.source || "");
    const snapshotId = String(value.snapshot_id || "");
    const snapshot = value.snapshot;
    if (!new Set(["github-incident-notification-journal", "github-incident-issues"]).has(source)
      || !/^[A-Za-z0-9:_-]{1,160}$/.test(snapshotId) || !snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      return response({ ok: false, error: "legacy_snapshot_identity_invalid" }, 400);
    }
    let raw = canonical(snapshot);
    if (TEXT.encode(raw).length > 240_000) return response({ ok: false, error: "legacy_snapshot_too_large" }, 413);
    let digest = await sha256(raw);
    let valueSnapshot = snapshot as Record<string, unknown>;
    if (valueSnapshot.schema_version !== "incident-legacy-import-v1") return response({ ok: false, error: "legacy_snapshot_schema_unsupported" }, 400);
    if (source === "github-incident-notification-journal") {
      const generation = valueSnapshot.journal_generation;
      const journalDigest = String(valueSnapshot.journal_body_sha256 || "");
      const sourceRepository = String(valueSnapshot.source_repository || "");
      if (typeof generation !== "number" || !Number.isSafeInteger(generation) || generation < 0
        || !/^[0-9a-f]{64}$/.test(journalDigest)
        || sourceRepository.toLowerCase() !== String(this.env.INCIDENT_REPOSITORY || "").toLowerCase()
        || Number(valueSnapshot.source_repository_id) !== Number(this.env.INCIDENT_REPOSITORY_ID || 0)
        || snapshotId !== `journal-${generation}-${journalDigest.slice(0, 32)}`) {
        return response({ ok: false, error: "legacy_snapshot_source_identity_invalid" }, 400);
      }
    }
    const confirmedWindows = valueSnapshot.confirmed_windows;
    const importedIncidents = valueSnapshot.incidents;
    if (!Array.isArray(confirmedWindows) || confirmedWindows.length > 256
      || (importedIncidents !== undefined && (!Array.isArray(importedIncidents) || importedIncidents.length > 100))) {
      return response({ ok: false, error: "legacy_snapshot_contents_invalid" }, 400);
    }
    const recipientHash = await sha256(RECIPIENT);
    const normalizedWindows: Array<{ decisionKey: string; windowKey: string; confirmedAt: string }> = [];
    for (const row of confirmedWindows) {
      if (!row || typeof row !== "object" || Array.isArray(row)) return response({ ok: false, error: "legacy_confirmed_window_invalid" }, 400);
      const item = row as Record<string, unknown>;
      const windowKey = String(item.window_key || "");
      const confirmedAt = String(item.confirmed_at || "");
      const channel = String(item.channel || "");
      const status = String(item.status || "");
      const suppliedRecipientHash = String(item.recipient_hash || "");
      const decisionKey = String(item.decision_key || "");
      if (!validTime(windowKey, true) || !validTime(confirmedAt, true) || channel !== "gmail" || status !== "confirmed"
        || suppliedRecipientHash !== recipientHash
        || decisionKey !== `ordinary|${windowKey}|gmail|${recipientHash}`) {
        return response({ ok: false, error: "legacy_confirmed_window_contract_invalid" }, 400);
      }
      normalizedWindows.push({ decisionKey, windowKey, confirmedAt });
    }
    const envelopes: Array<{ envelope: Envelope; suppressNotification: boolean }> = [];
    for (const row of (importedIncidents || []) as Array<unknown>) {
      if (!row || typeof row !== "object" || Array.isArray(row)) return response({ ok: false, error: "legacy_incident_invalid" }, 400);
      const item = row as Record<string, unknown>;
      const envelope = await validateEnvelope(item.envelope);
      if (String((envelope.evidence as Array<Record<string, unknown>>)[0].repository).toLowerCase() !== String(this.env.INCIDENT_REPOSITORY || "").toLowerCase()) {
        return response({ ok: false, error: "incident_envelope_repository_mismatch" }, 403);
      }
      if (typeof item.suppress_notification !== "boolean") return response({ ok: false, error: "legacy_incident_notification_policy_missing" }, 400);
      envelopes.push({ envelope, suppressNotification: item.suppress_notification });
    }
    const existing = rows(this.state.storage.sql.exec<SqlRow>("SELECT content_sha256,payload_json,status,processed_count FROM migration_snapshots WHERE snapshot_id=?", snapshotId))[0];
    if (existing) {
      const priorRaw = String(existing.payload_json || "");
      let prior: Record<string, unknown>;
      try { prior = JSON.parse(priorRaw) as Record<string, unknown>; }
      catch (_) { return response({ ok: false, error: "legacy_snapshot_saved_payload_invalid" }, 500); }
      const sameJournalIdentity = source === "github-incident-notification-journal"
        && prior.source_repository === valueSnapshot.source_repository
        && prior.journal_generation === valueSnapshot.journal_generation
        && prior.journal_body_sha256 === valueSnapshot.journal_body_sha256;
      if (existing.content_sha256 !== digest && !sameJournalIdentity) return response({ ok: false, error: "legacy_snapshot_conflict" }, 409);
      // Reuse the exact first-seen payload after an ambiguous response. This
      // makes reruns resume the same import, even when the new Actions run ID differs.
      raw = priorRaw;
      digest = String(existing.content_sha256);
      valueSnapshot = prior;
    }
    const effectiveConfirmedWindows = valueSnapshot.confirmed_windows as Array<Record<string, unknown>>;
    const effectiveIncidents = (valueSnapshot.incidents || []) as Array<Record<string, unknown>>;
    this.state.storage.transactionSync(() => {
      this.state.storage.sql.exec("INSERT OR IGNORE INTO migration_snapshots (snapshot_id,source,content_sha256,imported_at,payload_json,status,processed_count) VALUES (?,?,?,?,?,'importing',0)", snapshotId, source, digest, new Date().toISOString(), raw);
      for (const window of (existing ? [] : normalizedWindows)) {
        this.state.storage.sql.exec(
          "INSERT OR IGNORE INTO legacy_confirmed_windows (decision_key,window_key,recipient_hash,source,snapshot_id,confirmed_at) VALUES (?,?,?,?,?,?)",
          window.decisionKey, window.windowKey, recipientHash, source, snapshotId, window.confirmedAt,
        );
      }
    });
    const latest = rows(this.state.storage.sql.exec<SqlRow>("SELECT status,processed_count FROM migration_snapshots WHERE snapshot_id=?", snapshotId))[0];
    if (String(latest?.status || "") !== "completed") {
      for (let index = 0; index < effectiveIncidents.length; index++) {
        const imported = effectiveIncidents[index] as Record<string, unknown>;
        await this.storeEnvelope(imported.envelope as Envelope, imported.suppress_notification as boolean);
        this.state.storage.sql.exec(
          "UPDATE migration_snapshots SET processed_count=MAX(processed_count,?) WHERE snapshot_id=?",
          index + 1, snapshotId,
        );
      }
      this.state.storage.sql.exec("UPDATE migration_snapshots SET status='completed',processed_count=? WHERE snapshot_id=?", effectiveIncidents.length, snapshotId);
    }
    return response({
      ok: true, snapshot_id: snapshotId, content_sha256: digest, idempotent: Boolean(existing),
      status: "completed",
      confirmed_windows_imported: effectiveConfirmedWindows.length, incidents_imported: effectiveIncidents.length,
      recovery_proof_1145: (valueSnapshot.recovery_proof_1145 as Record<string, unknown> | undefined)?.status || "unverified",
    });
  }

  private async verifyMail(payload: unknown): Promise<Response> {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return response({ ok: false, error: "mail_verification_request_invalid" }, 400);
    const request = payload as Record<string, unknown>;
    const verificationId = String(request.verification_id || "");
    if (request.confirmation !== "SEND_ONE_VERIFICATION_EMAIL"
      || !/^[A-Za-z0-9][A-Za-z0-9_-]{15,63}$/.test(verificationId)) {
      return response({ ok: false, error: "mail_verification_confirmation_invalid" }, 400);
    }
    const recipientHash = await sha256(RECIPIENT);
    const decisionKey = `owner_link_verification|${verificationId}|${recipientHash}`;
    await this.reserveDecision(decisionKey, "owner_link_verification", `verification:${verificationId}`, {
      mode: "owner_link_verification",
      verification_id: verificationId,
      subject: "[PRStK 鏈路驗證] 管理員測試郵件",
      items: [],
    });
    const row = rows(this.state.storage.sql.exec<SqlRow>("SELECT * FROM outbox WHERE decision_key=?", decisionKey))[0];
    if (!row) return response({ ok: false, error: "mail_verification_outbox_missing" }, 503);
    return response({
      ok: true,
      verification_id: verificationId,
      delivery_id: row.delivery_id,
      state: row.state,
      message_id: row.message_id,
      content_sha256: row.content_sha256,
      recipient: RECIPIENT,
      delivery_verified: row.state === "sent_verified",
      inbox_verified: row.inbox_verified_at !== null && row.inbox_verified_at !== undefined,
    });
  }

  private outboxState(): Response {
    const pending = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT decision_key,delivery_id,mode,window_key,state,message_id,gmail_message_id,content_sha256,draft_id,reserved_at,updated_at,sent_at,inbox_verified_at,inbox_verification_state,inbox_last_checked_at,inbox_last_error,attempts,fallback_sent,last_error FROM outbox ORDER BY reserved_at DESC LIMIT 100",
    ));
    const incidents = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT incident_id,incident_type,component,root_cause,lifecycle,severity,generation,state_version,first_detected_at,observed_at,evidence_integrity,issue_numbers_json AS issue_numbers,updated_at FROM incidents ORDER BY updated_at DESC LIMIT 200",
    ));
    const shadowDecisions = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT decision_key,mode,window_key,created_at,payload_json FROM shadow_decisions ORDER BY created_at DESC LIMIT 100",
    ));
    const adminFallbacks = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT delivery_id,status,created_at,updated_at,last_error FROM admin_fallbacks ORDER BY created_at DESC LIMIT 100",
    ));
    const transitions = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT transition_id,incident_id,generation,state_version,lifecycle,severity,disposition,observed_at FROM incident_transitions ORDER BY observed_at DESC LIMIT 500",
    ));
    const migrationSnapshots = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT snapshot_id,source,content_sha256,imported_at,status,processed_count FROM migration_snapshots ORDER BY imported_at DESC LIMIT 50",
    ));
    const legacyConfirmed = Number(rows(this.state.storage.sql.exec<SqlRow>("SELECT COUNT(*) AS n FROM legacy_confirmed_windows"))[0]?.n || 0);
    return response({ ok: true, incidents, transitions, outbox: pending, shadow_decisions: shadowDecisions, admin_fallbacks: adminFallbacks, migration_snapshots: migrationSnapshots, legacy_confirmed_windows: legacyConfirmed });
  }

  private pendingReceipts(): Response {
    const pending = rows(this.state.storage.sql.exec<SqlRow>(
      `SELECT delivery_id,message_id,mode,window_key,sent_at,inbox_verification_state,inbox_last_checked_at FROM outbox
       WHERE state='sent_verified' AND inbox_verified_at IS NULL ORDER BY sent_at LIMIT 100`,
    ));
    return response({ ok: true, recipient: RECIPIENT, pending });
  }

  private async health(): Promise<Response> {
    const outbox = rows(this.state.storage.sql.exec<SqlRow>("SELECT state,COUNT(*) AS n FROM outbox GROUP BY state"));
    const rolling = Number(rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT COUNT(*) AS n FROM outbox WHERE reserved_at>=?", new Date(Date.now() - 86400_000).toISOString(),
    ))[0]?.n || 0);
    const unknown = Number(rows(this.state.storage.sql.exec<SqlRow>("SELECT COUNT(*) AS n FROM outbox WHERE state='delivery_unknown'"))[0]?.n || 0);
    const adminFallbackCounts = rows(this.state.storage.sql.exec<SqlRow>("SELECT status,COUNT(*) AS n FROM admin_fallbacks GROUP BY status"));
    let gmailAuth = "not_configured";
    const configured = Boolean(this.env.INCIDENT_GMAIL_OAUTH_CLIENT_ID && this.env.INCIDENT_GMAIL_OAUTH_CLIENT_SECRET && this.env.INCIDENT_GMAIL_REFRESH_TOKEN && this.env.INCIDENT_GMAIL_FROM);
    if (configured) {
      try {
        const token = await this.gmailAccessToken();
        const profile = await this.gmailRequest("profile", token);
        const value = profile.ok ? await profile.json() as { emailAddress?: string } : null;
        if (!value?.emailAddress || value.emailAddress.toLowerCase() !== String(this.env.INCIDENT_GMAIL_FROM || "").toLowerCase()) gmailAuth = "account_identity_mismatch";
        else gmailAuth = "refresh_and_account_verified";
      } catch (error) {
        gmailAuth = error instanceof Error ? error.message.slice(0, 100) : "gmail_auth_unverified";
      }
    }
    let receiptAuth = "not_configured";
    const receiptConfigured = Boolean(this.env.INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_ID && this.env.INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_SECRET
      && this.env.INCIDENT_RECEIPT_GMAIL_REFRESH_TOKEN && this.env.INCIDENT_RECEIPT_GMAIL_ADDRESS);
    if (receiptConfigured) {
      try {
        const token = await this.receiptAccessToken();
        const profile = await this.gmailRequest("profile", token);
        const value = profile.ok ? await profile.json() as { emailAddress?: string } : null;
        if (!value?.emailAddress || value.emailAddress.toLowerCase() !== String(this.env.INCIDENT_RECEIPT_GMAIL_ADDRESS || "").toLowerCase()
          || value.emailAddress.toLowerCase() !== RECIPIENT) receiptAuth = "account_identity_mismatch";
        else receiptAuth = "readonly_account_verified";
      } catch (error) {
        receiptAuth = error instanceof Error ? error.message.slice(0, 100) : "gmail_receipt_auth_unverified";
      }
    }
    const inboxStates = rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT inbox_verification_state AS state,COUNT(*) AS n FROM outbox WHERE state='sent_verified' GROUP BY inbox_verification_state",
    ));
    const shadow = rows(this.state.storage.sql.exec<SqlRow>("SELECT mode,COUNT(*) AS n FROM shadow_decisions GROUP BY mode"));
    const telegramConfigured = Boolean(this.env.INCIDENT_TELEGRAM_BOT_TOKEN && this.env.INCIDENT_TELEGRAM_ADMIN_CHAT_ID);
    const liveMode = this.outboundEnabled();
    const staleReceiptCutoff = new Date(Date.now() - UNKNOWN_GRACE_MS).toISOString();
    const staleReceipts = Number(rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT COUNT(*) AS n FROM outbox WHERE state='sent_verified' AND inbox_verified_at IS NULL AND sent_at<?", staleReceiptCutoff,
    ))[0]?.n || 0);
    const recentFailures = Number(rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT COUNT(*) AS n FROM outbox WHERE state IN ('failed_not_sent','delivery_unknown') AND updated_at>=?",
      new Date(Date.now() - 86_400_000).toISOString(),
    ))[0]?.n || 0);
    const duplicateReceipts = Number(rows(this.state.storage.sql.exec<SqlRow>(
      "SELECT COUNT(*) AS n FROM outbox WHERE inbox_verification_state='duplicate_inbox_messages' AND updated_at>=?",
      new Date(Date.now() - 86_400_000).toISOString(),
    ))[0]?.n || 0);
    const readyToCutover = gmailAuth === "refresh_and_account_verified" && receiptAuth === "readonly_account_verified"
      && telegramConfigured && unknown === 0 && staleReceipts === 0 && recentFailures === 0 && duplicateReceipts === 0;
    const operationalStatus = liveMode ? (readyToCutover ? "ready" : "degraded") : "shadow";
    return response({
      ok: !liveMode || readyToCutover, ready_to_cutover: readyToCutover, operational_status: operationalStatus,
      storage: "durable_object_sqlite", gmail_configured: configured, gmail_auth_status: gmailAuth,
      receipt_gmail_configured: receiptConfigured, receipt_gmail_auth_status: receiptAuth, inbox_verification_counts: inboxStates,
      mode: this.outboundEnabled() ? "live" : "shadow", recipient_fixed: RECIPIENT, rolling_24h_reserved: rolling, rolling_24h_limit: MAX_MAILS_PER_24H,
      quota_warning_threshold: WARN_MAILS_PER_24H, delivery_unknown: unknown, stale_inbox_receipts: staleReceipts,
      recent_send_failures: recentFailures, duplicate_inbox_receipts: duplicateReceipts, outbox_counts: outbox,
      admin_fallback_counts: adminFallbackCounts,
      telegram_admin_fallback_configured: telegramConfigured,
      shadow_decisions: shadow, observed_at: new Date().toISOString(),
    });
  }

  private outboundEnabled(): boolean {
    return String(this.env.INCIDENT_OPS_MODE || "shadow").toLowerCase() === "live";
  }

  private async recordShadowDecision(key: string, mode: string, window: string, payload: Record<string, unknown>): Promise<void> {
    this.state.storage.sql.exec(
      "INSERT OR IGNORE INTO shadow_decisions (decision_key,mode,window_key,created_at,payload_json) VALUES (?,?,?,?,?)",
      key, mode, window, new Date().toISOString(), JSON.stringify(payload),
    );
  }
}
