import { reactive } from "vue";

export type User = { id: string; email: string; is_platform_admin: boolean; must_change_password: boolean };
type AuthState = { token: string; user: User | null; tenantId: string | null; clear: () => void };
const stored = sessionStorage.getItem("antler-rag-session");
const initial = stored ? JSON.parse(stored) : {};
export const authState = reactive<AuthState>({ token: initial.token ?? "", user: initial.user ?? null, tenantId: initial.tenantId ?? null, clear() {} });
authState.clear = () => { authState.token = ""; authState.user = null; authState.tenantId = null; sessionStorage.removeItem("antler-rag-session"); };
export function saveAuth(token: string, user: User) { authState.token = token; authState.user = user; sessionStorage.setItem("antler-rag-session", JSON.stringify({ token, user, tenantId: authState.tenantId })); }
export function setTenant(tenantId: string | null) { authState.tenantId = tenantId; sessionStorage.setItem("antler-rag-session", JSON.stringify({ token: authState.token, user: authState.user, tenantId })); }
