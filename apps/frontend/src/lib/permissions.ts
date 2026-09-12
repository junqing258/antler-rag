export type Role = "admin" | "editor" | "viewer";

export function canManageMembers(role: Role | undefined): boolean {
  return role === "admin";
}

export function canManageDocuments(role: Role | undefined): boolean {
  return role === "admin" || role === "editor";
}
