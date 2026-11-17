import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import handler from "../src/index.ts";

const originalFetch = globalThis.fetch;
const SECRET = "test-only-shared-secret";

async function sign(body: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return `sha256=${[...new Uint8Array(signature)].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function environment() {
  return {
    DELIVERY_RECEIPT_SHARED_SECRET: SECRET,
    SUPABASE_URL: "https://database.example.test",
    SUPABASE_SERVICE_ROLE_KEY: "test-service-role",
  } as never;
}

async function postAttempt(value: Record<string, unknown>) {
  const body = JSON.stringify(value);
  return handler.fetch(new Request("https://worker.example.test/api/delivery-attempts", {
    method: "POST",
    headers: { "content-type": "application/json", "X-PRSTK-Signature": await sign(body) },
    body,
  }), environment());
}

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("signed Telegram delivery attempt endpoint", () => {
  it("passes only hashed recipient identity to the atomic Supabase transition", async () => {
    let rpcBody: Record<string, unknown> | null = null;
    globalThis.fetch = async (input, init) => {
      assert.equal(String(input), "https://database.example.test/rest/v1/rpc/transition_telegram_delivery_attempt");
      rpcBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return new Response(JSON.stringify({ status: "reserved" }), { status: 200 });
    };
    const response = await postAttempt({
      notification_hash: "a".repeat(64), recipient_hash: "b".repeat(64),
      attempt_id: "2c1a7c50-8015-4c59-b0ac-0f1c1234ab56", operation: "reserve",
      deadline_at: "2026-11-17T12:15:00Z", lease_seconds: 60,
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { ok: true, status: "reserved", message_id: null, retry_after_at: null });
    assert.equal(rpcBody?.p_notification_hash, "a".repeat(64));
    assert.equal(rpcBody?.p_recipient_hash, "b".repeat(64));
    assert.equal("chat_id" in (rpcBody || {}), false);
  });

  it("rejects unsigned-shaped payload extensions before touching Supabase", async () => {
    let databaseCalls = 0;
    globalThis.fetch = async () => {
      databaseCalls += 1;
      return new Response(JSON.stringify({ status: "reserved" }), { status: 200 });
    };
    const response = await postAttempt({
      notification_hash: "a".repeat(64), recipient_hash: "b".repeat(64),
      attempt_id: "2c1a7c50-8015-4c59-b0ac-0f1c1234ab56", operation: "reserve",
      deadline_at: "2026-11-17T12:15:00Z", lease_seconds: 60, chat_id: "raw-private-id",
    });
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { ok: false, error: "INVALID_ATTEMPT_FIELDS" });
    assert.equal(databaseCalls, 0);
  });

  it("rejects fields that do not belong to the requested transition", async () => {
    let databaseCalls = 0;
    globalThis.fetch = async () => {
      databaseCalls += 1;
      return new Response(JSON.stringify({ status: "reserved" }), { status: 200 });
    };
    const response = await postAttempt({
      notification_hash: "a".repeat(64), recipient_hash: "b".repeat(64),
      attempt_id: "2c1a7c50-8015-4c59-b0ac-0f1c1234ab56", operation: "reserve",
      deadline_at: "2026-11-17T12:15:00Z", result: "delivered",
    });
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { ok: false, error: "INVALID_ATTEMPT_FIELDS" });
    assert.equal(databaseCalls, 0);
  });

  it("rejects unknown operations before indexing the transition contract", async () => {
    let databaseCalls = 0;
    globalThis.fetch = async () => {
      databaseCalls += 1;
      return new Response(JSON.stringify({ status: "reserved" }), { status: 200 });
    };
    const response = await postAttempt({
      notification_hash: "a".repeat(64), recipient_hash: "b".repeat(64),
      attempt_id: "2c1a7c50-8015-4c59-b0ac-0f1c1234ab56", operation: "unknown",
    });
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { ok: false, error: "INVALID_ATTEMPT_FIELDS" });
    assert.equal(databaseCalls, 0);
  });

  it("requires outcome-specific evidence before recording a result", async () => {
    let databaseCalls = 0;
    globalThis.fetch = async () => {
      databaseCalls += 1;
      return new Response(JSON.stringify({ status: "delivered" }), { status: 200 });
    };
    const response = await postAttempt({
      notification_hash: "a".repeat(64), recipient_hash: "b".repeat(64),
      attempt_id: "2c1a7c50-8015-4c59-b0ac-0f1c1234ab56", operation: "result",
      result: "delivered",
    });
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { ok: false, error: "INVALID_ATTEMPT_RESULT" });
    assert.equal(databaseCalls, 0);
  });

  it("returns a generic retryable error when durable state is unavailable", async () => {
    globalThis.fetch = async () => new Response("database detail with secret", { status: 503 });
    const response = await postAttempt({
      notification_hash: "a".repeat(64), recipient_hash: "b".repeat(64),
      attempt_id: "2c1a7c50-8015-4c59-b0ac-0f1c1234ab56", operation: "start",
    });
    assert.equal(response.status, 503);
    const body = await response.text();
    assert.match(body, /DELIVERY_GUARD_PERSISTENCE_FAILED/);
    assert.doesNotMatch(body, /database detail|secret/i);
  });
});
