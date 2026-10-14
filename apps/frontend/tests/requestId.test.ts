import { afterEach, describe, expect, it, vi } from "vitest";

import { requestId } from "../src/lib/requestId";

const SORTABLE_REQUEST_ID = /^\d{14}_[0-9a-f]{8}$/;

describe("request id", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("produces the backend-compatible timestamp and random suffix", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 14, 10, 30, 45));
    expect(requestId()).toMatch(/^20261014103045_[0-9a-f]{8}$/);
  });

  it("uses getRandomValues when randomUUID is unavailable", () => {
    const realCrypto = globalThis.crypto;
    vi.stubGlobal("crypto", {
      getRandomValues: realCrypto.getRandomValues.bind(realCrypto),
    });

    const first = requestId();
    expect(first).toMatch(SORTABLE_REQUEST_ID);
    expect(first).not.toBe(requestId());
  });
});
