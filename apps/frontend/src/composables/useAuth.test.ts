import { beforeEach, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  getSession: vi.fn(),
  signOut: vi.fn(),
  onAuthStateChange: vi.fn(),
}));
vi.mock("@supabase/supabase-js", () => ({
  createClient: vi.fn(() => ({ auth })),
}));

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue({
        ok: true,
        json: async () => ({
          url: "https://auth.test",
          publishableKey: "public",
        }),
      }),
  );
  auth.getSession.mockResolvedValue({
    data: { session: { access_token: "refreshed" } },
    error: null,
  });
});

it("reads the current SDK token for requests and never restores legacy sessions", async () => {
  const { authState, accessToken } = await import("./useAuth");
  expect(authState.token).toBe("");
  expect(await accessToken()).toBe("refreshed");
  auth.getSession.mockResolvedValue({
    data: { session: { access_token: "new-token" } },
    error: null,
  });
  expect(await accessToken()).toBe("new-token");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("clears local sessions and preserves other Antler sessions", async () => {
  const { authState, accessToken } = await import("./useAuth");
  await accessToken();
  await authState.clear();
  expect(authState.token).toBe("");
  expect(authState.user).toBeNull();
  expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
});

it("retries configuration after failure without allowing access", async () => {
  const { supabase } = await import("./useAuth");
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false } as Response);
  await expect(supabase()).rejects.toThrow("登录服务尚未配置");
  await expect(supabase()).resolves.toBeDefined();
});

it("rejects disabled or expired sessions before loading a profile", async () => {
  const { loadProfile, authState } = await import("./useAuth");
  vi.mocked(fetch)
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        url: "https://auth.test",
        publishableKey: "public",
      }),
    } as Response)
    .mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ message: "disabled" }),
    } as Response);
  await expect(loadProfile()).rejects.toThrow("disabled");
  expect(authState.token).toBe("");
  expect(auth.signOut).toHaveBeenCalled();
});
