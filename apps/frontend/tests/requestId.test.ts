import { afterEach, describe, expect, it, vi } from "vitest";

import { requestId } from "../src/lib/requestId";

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("request id", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("produces a uuid v4 in a secure context", () => {
    expect(requestId()).toMatch(UUID_V4);
  });

  it("still produces a uuid v4 when randomUUID is unavailable", () => {
    // Over plain HTTP from a LAN address crypto.randomUUID is undefined while
    // crypto.getRandomValues remains usable.
    const realCrypto = globalThis.crypto;
    vi.stubGlobal("crypto", {
      getRandomValues: realCrypto.getRandomValues.bind(realCrypto),
    });

    const first = requestId();
    expect(first).toMatch(UUID_V4);
    expect(first).not.toBe(requestId());
  });
});
