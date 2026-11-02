import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { DatabaseSync } from "node:sqlite";
import { IncidentCoordinator } from "../src/incident_coordinator.ts";
import handler from "../src/index.ts";

const REPOSITORY = "hanjhou2000716/prstklab-stk-detector";
const RECIPIENT = "hanjhou2000716@gmail.com";
const originalFetch = globalThis.fetch;

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const row = value as Record<string, unknown>;
    return `{${Object.keys(row).sort().map((key) => `${JSON.stringify(key)}:${canonical(row[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function hash(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

async function envelope(lifecycle: string, stateVersion: number, observedAt: string, newImpact = false) {
  const incidentIdentity = {
    incident_type: "monitor_failure", component: "official_monitor", root_cause: "pagination_identity_invalid",
  };
  const impactIdentity = { run_id: 41291664641, attempt: 1, slot: "official-monitor" };
  const impactType = "source_run";
  return {
    schema_version: "incident-envelope-v2",
    incident_id: await hash(canonical(incidentIdentity)),
    incident_type: "monitor_failure", component: "official_monitor", root_cause: "pagination_identity_invalid",
    impact_key: await hash(canonical({ type: impactType, identity: impactIdentity })),
    impact_type: impactType,
    impact: { identity: impactIdentity, description: "Bounded synthetic test evidence." },
    evidence: [{
      repository: REPOSITORY, workflow: ".github/workflows/official-event-monitor.yml",
      run_id: 41291664641, attempt: 1, sha: "a".repeat(40), artifact_id: 13077677142,
      artifact_digest: `sha256:${"b".repeat(64)}`,
    }],
    times: { first_detected_at: "2026-11-01T09:06:51Z", observed_at: observedAt, source_occurred_at: "unknown" },
    severity: "high", lifecycle, evidence_integrity: "verified", new_impact: newImpact,
    generation: 1, state_version: stateVersion, issue_numbers: [1144],
    compatibility: { adapter: "incident-envelope-v2", legacy_source: null },
  };
}

function makeCoordinator(env: Record<string, string> = {}) {
  const db = new DatabaseSync(":memory:");
  const sql = {
    exec(query: string, ...parameters: unknown[]) {
      const statement = db.prepare(query);
      const normalized = query.trimStart().toUpperCase();
      const result = /^(SELECT|PRAGMA|WITH)\b/.test(normalized)
        ? statement.all(...parameters)
        : (statement.run(...parameters), []);
      return { toArray: () => result };
    },
  };
  const state = {
    storage: {
      sql,
      transactionSync<T>(callback: () => T): T {
        db.exec("BEGIN IMMEDIATE");
        try {
          const result = callback();
          db.exec("COMMIT");
          return result;
        } catch (error) {
          db.exec("ROLLBACK");
          throw error;
        }
      },
    },
  };
  const coordinator = new IncidentCoordinator(state as never, {
    INCIDENT_REPOSITORY: REPOSITORY,
    INCIDENT_REPOSITORY_ID: "1309835643",
    INCIDENT_OPS_MODE: "live",
    INCIDENT_GMAIL_OAUTH_CLIENT_ID: "client-id",
    INCIDENT_GMAIL_OAUTH_CLIENT_SECRET: "client-secret",
    INCIDENT_GMAIL_REFRESH_TOKEN: "refresh-token",
    INCIDENT_GMAIL_FROM: "alerts@example.com",
    INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_ID: "recipient-client-id",
    INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_SECRET: "recipient-client-secret",
    INCIDENT_RECEIPT_GMAIL_REFRESH_TOKEN: "recipient-refresh-token",
    INCIDENT_RECEIPT_GMAIL_ADDRESS: RECIPIENT,
    ...env,
  });
  return { coordinator, db };
}

async function call(coordinator: IncidentCoordinator, path: string, body?: unknown, method?: string): Promise<Record<string, unknown>> {
  const result = await coordinator.fetch(new Request(`https://coordinator${path}`, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }));
  const value = await result.json() as Record<string, unknown>;
  assert.ok(result.status < 400, JSON.stringify(value));
  return value;
}

describe("public liveness", () => {
  it("exposes only a minimal public coordinator status without requiring the market database", async () => {
    const { coordinator } = makeCoordinator({ INCIDENT_OPS_MODE: "shadow" });
    const namespace = {
      idFromName: () => "repo-1309835643",
      get: () => ({ fetch: (input: RequestInfo | URL, init?: RequestInit) => coordinator.fetch(new Request(input, init)) }),
    };
    const response = await handler.fetch(new Request("https://worker.example.workers.dev/public/ops/liveness"), {
      INCIDENT_COORDINATOR: namespace,
      INCIDENT_REPOSITORY_ID: "1309835643",
      INCIDENT_REPOSITORY: REPOSITORY,
    } as never);
    const value = await response.json() as Record<string, unknown>;
    assert.equal(response.status, 200, JSON.stringify(value));
    assert.equal(value.ok, true);
    assert.equal(value.component, "incident-coordinator");
    assert.equal(typeof value.observed_at, "string");
    assert.deepEqual(Object.keys(value).sort(), ["component", "observed_at", "ok"]);
    assert.equal(response.headers.get("x-robots-tag"), "noindex, nofollow");
  });

  it("fails closed when the Durable Object binding is absent", async () => {
    const response = await handler.fetch(new Request("https://worker.example.workers.dev/public/ops/liveness"), {} as never);
    assert.equal(response.status, 503);
    assert.equal((await response.json() as Record<string, unknown>).ok, false);
  });
});

function mockGmail(options: {
  loseDraftResponse?: boolean;
  loseSendResponse?: boolean;
  send404AfterAcceptance?: boolean;
  wrongInboxRecipient?: boolean;
  duplicateInboxCopies?: number;
} = {}) {
  const drafts = new Map<string, string>();
  const sent = new Map<string, string>();
  const calls = { draftCreates: 0, sends: 0, urls: [] as string[] };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || "GET";
    calls.urls.push(`${method} ${url}`);
    if (url === "https://oauth2.googleapis.com/token") {
      const body = new URLSearchParams(String(init?.body || ""));
      return Response.json({ access_token: body.get("client_id") === "recipient-client-id" ? "recipient-access-token" : "sender-access-token" });
    }
    if (url.endsWith("/profile")) {
      const recipient = new Headers(init?.headers).get("Authorization") === "Bearer recipient-access-token";
      return Response.json({ emailAddress: recipient ? RECIPIENT : "alerts@example.com" });
    }
    if (url.includes("/drafts/send")) {
      calls.sends += 1;
      const inputBody = JSON.parse(String(init?.body || "{}")) as { id?: string };
      const raw = drafts.get(String(inputBody.id));
      if (!raw) return Response.json({ error: { message: "draft not found" } }, { status: 404 });
      const id = `sent-${calls.sends}`;
      drafts.delete(String(inputBody.id));
      sent.set(id, raw);
      if (options.loseSendResponse) throw new TypeError("simulated response lost after acceptance");
      if (options.send404AfterAcceptance) return Response.json({ error: { message: "draft no longer exists" } }, { status: 404 });
      return Response.json({ id });
    }
    if (url.includes("/drafts?") && method === "GET") {
      return Response.json({ drafts: [...drafts.keys()].map((id) => ({ id })) });
    }
    if (url.includes("/drafts/") && method === "GET") {
      const id = decodeURIComponent(url.split("/drafts/")[1].split("?")[0]);
      const raw = drafts.get(id) || "";
      const messageId = raw.match(/^Message-ID: (.+)$/m)?.[1] || "";
      return Response.json({ id, message: { payload: { headers: [{ name: "Message-ID", value: messageId }] } } });
    }
    if (url.endsWith("/drafts") && method === "POST") {
      calls.draftCreates += 1;
      const inputBody = JSON.parse(String(init?.body || "{}")) as { message?: { raw?: string } };
      const raw = Buffer.from(String(inputBody.message?.raw || ""), "base64url").toString("utf8");
      const id = `draft-${calls.draftCreates}`;
      drafts.set(id, raw);
      if (options.loseDraftResponse) throw new TypeError("simulated response lost after draft creation");
      return Response.json({ id });
    }
    if (url.includes("/messages?") && method === "GET") {
      const recipient = new Headers(init?.headers).get("Authorization") === "Bearer recipient-access-token";
      if (recipient) {
        const count = Math.max(1, Number(options.duplicateInboxCopies || 1));
        return Response.json({ messages: [...sent.keys()].flatMap((id) => Array.from({ length: count }, (_, index) => ({ id: `inbox-${id}-${index + 1}` }))) });
      }
      return Response.json({ messages: [...sent.keys()].map((id) => ({ id })) });
    }
    if (url.includes("/messages/") && method === "GET") {
      const id = decodeURIComponent(url.split("/messages/")[1].split("?")[0]);
      const recipient = new Headers(init?.headers).get("Authorization") === "Bearer recipient-access-token";
      if (recipient) {
        const match = id.match(/^inbox-(sent-\d+)-\d+$/);
        const raw = match ? sent.get(match[1]) || "" : "";
        const messageId = raw.match(/^Message-ID: (.+)$/m)?.[1] || "";
        return Response.json({
          id, labelIds: ["INBOX"], payload: { headers: [
            { name: "Message-ID", value: messageId },
            { name: "To", value: options.wrongInboxRecipient ? "wrong@example.com" : RECIPIENT },
            { name: "Delivered-To", value: options.wrongInboxRecipient ? "wrong@example.com" : RECIPIENT },
            { name: "From", value: "PRStK Alerts <alerts@example.com>" },
          ] },
        });
      }
      const raw = sent.get(id) || "";
      const messageId = raw.match(/^Message-ID: (.+)$/m)?.[1] || "";
      return Response.json({ id, labelIds: ["SENT"], payload: { headers: [{ name: "Message-ID", value: messageId }] } });
    }
    throw new Error(`unhandled mock URL: ${method} ${url}`);
  }) as typeof fetch;
  return { calls, drafts, sent };
}

afterEach(() => { globalThis.fetch = originalFetch; });

describe("IncidentCoordinator durable lifecycle and mail outbox", () => {
  it("rejects evidence when GitHub and Worker cutover modes differ", async () => {
    const { coordinator } = makeCoordinator({ INCIDENT_OPS_MODE: "live" });
    const result = await coordinator.fetch(new Request("https://coordinator/internal/evidence", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ producer_mode: "shadow", envelopes: [] }),
    }));
    assert.equal(result.status, 409);
    assert.deepEqual(await result.json(), { ok: false, error: "incident_ops_mode_mismatch" });
  });

  it("does not let a stale replay downgrade recovered state or reopen its generation", async () => {
    const { coordinator } = makeCoordinator();
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("active", 2, "2026-11-01T09:10:00Z", true)] });
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("recovered", 3, "2026-11-01T09:20:00Z")] });
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("active", 2, "2026-11-01T09:10:00Z", true)] });

    const state = await call(coordinator, "/internal/outbox/state");
    const incident = (state.incidents as Array<Record<string, unknown>>)[0];
    assert.equal(incident.lifecycle, "recovered");
    assert.equal(incident.generation, 1);
    assert.equal(incident.state_version, 3);
    assert.equal(incident.first_detected_at, "2026-11-01T09:06:51Z");
    assert.equal(incident.observed_at, "2026-11-01T09:20:00Z");
  });

  it("resumes the same Gmail draft after its create response is lost", async () => {
    const gmail = mockGmail({ loseDraftResponse: true });
    const { coordinator } = makeCoordinator();
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("active", 1, "2026-11-01T09:10:00Z", true)] });
    await call(coordinator, "/internal/tick", {}, "POST");
    await call(coordinator, "/internal/tick", {}, "POST");

    const state = await call(coordinator, "/internal/outbox/state");
    const row = (state.outbox as Array<Record<string, unknown>>)[0];
    assert.equal(row.state, "sent_verified", JSON.stringify({ row, requests: gmail.calls.urls }));
    assert.equal(gmail.calls.draftCreates, 1);
    assert.equal(gmail.calls.sends, 1);
    assert.equal(gmail.sent.size, 1);
  });

  it("verifies an accepted send after its HTTP response is lost without sending twice", async () => {
    const gmail = mockGmail({ loseSendResponse: true });
    const { coordinator } = makeCoordinator();
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("active", 1, "2026-11-01T09:10:00Z", true)] });
    await call(coordinator, "/internal/tick", {}, "POST");
    await call(coordinator, "/internal/tick", {}, "POST");

    const state = await call(coordinator, "/internal/outbox/state");
    const row = (state.outbox as Array<Record<string, unknown>>)[0];
    assert.equal(row.state, "sent_verified");
    assert.equal(gmail.calls.draftCreates, 1);
    assert.equal(gmail.calls.sends, 1);
    assert.equal(gmail.sent.size, 1);
  });

  it("treats a send 404 as ambiguous and verifies existing sent and inbox copies", async () => {
    const gmail = mockGmail({ send404AfterAcceptance: true });
    const { coordinator } = makeCoordinator();
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("active", 1, "2026-11-01T09:10:00Z", true)] });
    await call(coordinator, "/internal/tick", {}, "POST");
    await call(coordinator, "/internal/tick", {}, "POST");

    const state = await call(coordinator, "/internal/outbox/state");
    const row = (state.outbox as Array<Record<string, unknown>>)[0];
    assert.equal(row.state, "sent_verified");
    assert.equal(row.inbox_verification_state, "inbox_verified");
    assert.equal(gmail.calls.sends, 1);
    assert.equal(gmail.sent.size, 1);
  });

  it("does not claim a recipient receipt when inbox headers identify another recipient", async () => {
    const gmail = mockGmail({ wrongInboxRecipient: true });
    const { coordinator } = makeCoordinator();
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("active", 1, "2026-11-01T09:10:00Z", true)] });
    await call(coordinator, "/internal/tick", {}, "POST");

    const state = await call(coordinator, "/internal/outbox/state");
    const row = (state.outbox as Array<Record<string, unknown>>)[0];
    assert.equal(row.state, "sent_verified");
    assert.equal(row.inbox_verification_state, "awaiting_inbox");
    assert.equal(row.inbox_verified_at, null);
    assert.equal(gmail.calls.sends, 1);
  });

  it("records duplicate inbox copies and emits one deduplicated admin fallback", async () => {
    const gmail = mockGmail({ duplicateInboxCopies: 2 });
    const { coordinator } = makeCoordinator({ INCIDENT_TELEGRAM_BOT_TOKEN: "bot-token", INCIDENT_TELEGRAM_ADMIN_CHAT_ID: "12345678" });
    let telegramPosts = 0;
    const mailFetch = globalThis.fetch;
    const fetchWithTelegram = (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).startsWith("https://api.telegram.org/")) {
        telegramPosts += 1;
        return Response.json({ ok: true, result: { message_id: telegramPosts } });
      }
      return mailFetch(input, init);
    }) as typeof fetch;
    globalThis.fetch = fetchWithTelegram;
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("active", 1, "2026-11-01T09:10:00Z", true)] });
    await call(coordinator, "/internal/tick", {}, "POST");

    const state = await call(coordinator, "/internal/outbox/state");
    const row = (state.outbox as Array<Record<string, unknown>>)[0];
    assert.equal(row.inbox_verification_state, "duplicate_inbox_messages");
    assert.equal(telegramPosts, 1);
    assert.equal(gmail.calls.sends, 1);
  });

  it("sends one fixed-recipient owner verification even in shadow and resumes the same idempotent delivery", async () => {
    const gmail = mockGmail();
    const { coordinator } = makeCoordinator({ INCIDENT_OPS_MODE: "shadow" });
    const request = {
      confirmation: "SEND_ONE_VERIFICATION_EMAIL",
      verification_id: "link-check-20261102-01",
    };
    const first = await call(coordinator, "/internal/mail/verify", request);
    const replay = await call(coordinator, "/internal/mail/verify", request);

    assert.equal(first.state, "sent_verified");
    assert.equal(first.delivery_verified, true);
    assert.equal(first.inbox_verified, false);
    assert.equal(replay.delivery_id, first.delivery_id);
    assert.equal(gmail.calls.draftCreates, 1);
    assert.equal(gmail.calls.sends, 1);
    const raw = [...gmail.sent.values()][0] || "";
    assert.ok(raw.includes(`To: ${RECIPIENT}`));
    const body = raw.split("\r\n\r\n", 2)[1] || "";
    const text = Buffer.from(body.replace(/\r\n/g, ""), "base64").toString("utf8");
    assert.match(text, /管理員明確觸發的驗證郵件/);
    assert.match(text, /link-check-20261102-01/);
  });

  it("rejects owner verification without its explicit send confirmation", async () => {
    const gmail = mockGmail();
    const { coordinator } = makeCoordinator({ INCIDENT_OPS_MODE: "shadow" });
    const response = await coordinator.fetch(new Request("https://coordinator/internal/mail/verify", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ confirmation: "maybe", verification_id: "link-check-20261102-01" }),
    }));
    assert.equal(response.status, 400);
    assert.equal(gmail.calls.draftCreates, 0);
    assert.equal(gmail.calls.sends, 0);
  });

  it("imports confirmed legacy windows as dedupe records without sending", async () => {
    const gmail = mockGmail();
    const { coordinator } = makeCoordinator();
    const now = new Date();
    now.setUTCMinutes(now.getUTCMinutes() < 30 ? 0 : 30, 0, 0);
    const windowKey = now.toISOString();
    const recipientHash = await hash(RECIPIENT);
    const decisionKey = `ordinary|${windowKey}|gmail|${recipientHash}`;
    const snapshot = {
      schema_version: "incident-legacy-import-v1",
      source_repository: REPOSITORY,
      source_repository_id: 1309835643,
      journal_generation: 1,
      journal_body_sha256: "a".repeat(64),
      confirmed_windows: [{
        decision_key: decisionKey, window_key: windowKey, channel: "gmail", recipient_hash: recipientHash,
        status: "confirmed", confirmed_at: "2026-11-01T09:00:00Z",
      }],
      incidents: [],
    };
    const snapshotId = `journal-1-${snapshot.journal_body_sha256.slice(0, 32)}`;
    const imported = await call(coordinator, "/internal/import", {
      source: "github-incident-notification-journal", snapshot_id: snapshotId, snapshot,
    });
    assert.equal(imported.status, "completed");
    // An ambiguous response may lead to a fresh Actions run with changed run
    // metadata. The saved journal identity resumes the first immutable payload.
    const replay = await call(coordinator, "/internal/import", {
      source: "github-incident-notification-journal", snapshot_id: snapshotId,
      snapshot: { ...snapshot, imported_at: "2026-11-02T00:00:00Z" },
    });
    assert.equal(replay.idempotent, true);
    assert.equal(replay.status, "completed");
    await call(coordinator, "/internal/evidence", { producer_mode: "live", envelopes: [await envelope("active", 1, "2026-11-01T09:10:00Z", true)] });
    await call(coordinator, "/internal/tick", {}, "POST");
    assert.equal(gmail.calls.draftCreates, 0);
    assert.equal(gmail.calls.sends, 0);
  });
});
