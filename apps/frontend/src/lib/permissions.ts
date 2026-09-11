export type Role = "platform_admin" | "tenant_admin" | "editor" | "viewer";

export function canManageMembers(role: Role | undefined): boolean {
  return role === "platform_admin" || role === "tenant_admin";
}

export function canManageDocuments(role: Role | undefined): boolean {
  return role === "platform_admin" || role === "tenant_admin" || role === "editor";
}
