import { reactive } from "vue";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export type User = {
  id: string;
  email: string;
  role: "admin" | "editor" | "viewer";
  must_change_password: boolean;
};
export const authState = reactive({
  token: "",
  user: null as User | null,
  async clear() {
    authState.token = "";
    authState.user = null;
    await client?.auth.signOut({ scope: "local" });
  },
});
let client: SupabaseClient | undefined;
let initializing: Promise<SupabaseClient> | undefined;

export function supabase(): Promise<SupabaseClient> {
  if (!initializing) {
    initializing = (async () => {
      const response = await fetch("/api/v1/auth/config");
      if (!response.ok) throw new Error("登录服务尚未配置，请联系管理员。");
      const config = await response.json();
      client = createClient(config.url, config.publishableKey, {
        auth: {
          autoRefreshToken: true,
          persistSession: true,
          detectSessionInUrl: false,
          storageKey: "antler-rag-supabase",
        },
      });
      client.auth.onAuthStateChange((_event, session) => {
        authState.token = session?.access_token ?? "";
        if (!session) authState.user = null;
      });
      return client;
    })().catch((error) => {
      initializing = undefined;
      throw error;
    });
  }
  return initializing;
}

export async function accessToken() {
  const { data, error } = await (await supabase()).auth.getSession();
  if (error) throw error;
  authState.token = data.session?.access_token ?? "";
  return authState.token;
}

export async function loadProfile() {
  const token = await accessToken();
  if (!token) return;
  const response = await fetch("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const payload = await response.json();
  if (!response.ok) {
    if (response.status === 401 || response.status === 403)
      await authState.clear();
    throw new Error(payload.message || "无法读取账号信息");
  }
  authState.user = payload.user;
}
