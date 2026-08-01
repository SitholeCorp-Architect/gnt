// fetchOnboardingCompleted -- gnt login's own read of the same real
// onboarding_completed field the web dashboard gates on now, replacing
// the old "key minted == set up" assumption. Only this helper is under
// test, not the full login() flow (real browser open + network polling +
// spinner timers), same scope-to-the-new-logic reasoning as the rest of
// this PR's tests.
import { afterEach, beforeEach, expect, mock, test } from "bun:test";
import { fetchOnboardingCompleted } from "../src/commands/login.js";

let originalFetch: typeof fetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("returns true once the wizard is actually done", async () => {
  globalThis.fetch = mock(() =>
    Promise.resolve(new Response(JSON.stringify({ onboarding_completed: true }), { status: 200 })),
  ) as unknown as typeof fetch;

  expect(await fetchOnboardingCompleted("gnt_live_test_key")).toBe(true);
});

test("returns false for a real org that hasn't finished the wizard yet", async () => {
  globalThis.fetch = mock(() =>
    Promise.resolve(new Response(JSON.stringify({ onboarding_completed: false }), { status: 200 })),
  ) as unknown as typeof fetch;

  expect(await fetchOnboardingCompleted("gnt_live_test_key")).toBe(false);
});

test("returns null, not false, on a non-2xx response -- unknown isn't the same as not done", async () => {
  globalThis.fetch = mock(() => Promise.resolve(new Response("", { status: 500 }))) as unknown as typeof fetch;

  expect(await fetchOnboardingCompleted("gnt_live_test_key")).toBeNull();
});

test("returns null on a network failure instead of throwing", async () => {
  globalThis.fetch = mock(() => Promise.reject(new Error("network down"))) as unknown as typeof fetch;

  expect(await fetchOnboardingCompleted("gnt_live_test_key")).toBeNull();
});
