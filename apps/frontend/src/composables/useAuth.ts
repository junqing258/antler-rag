import { reactive } from "vue";

export type User = {
  id: string;
  email: string;
  role: "admin" | "editor" | "viewer";
  must_change_password: boolean;
};
type AuthState = {
  token: string;
  user: User | null;
  clear: () => void;
};
const stored = sessionStorage.getItem("antler-rag-session");
const initial = stored ? JSON.parse(stored) : {};
export const authState = reactive<AuthState>({
  token: initial.token ?? "",
  user: initial.user ?? null,
  clear() {},
});
authState.clear = () => {
  authState.token = "";
  authState.user = null;
  sessionStorage.removeItem("antler-rag-session");
};
export function saveAuth(token: string, user: User) {
  authState.token = token;
  authState.user = user;
  sessionStorage.setItem(
    "antler-rag-session",
    JSON.stringify({ token, user }),
  );
}
