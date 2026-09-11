import { describe, expect, it } from "vitest";

import { canManageDocuments, canManageMembers } from "../src/lib/permissions";

describe("role display guards", () => {
  it("does not expose member administration to viewers", () => {
    expect(canManageMembers("viewer")).toBe(false);
    expect(canManageMembers("tenant_admin")).toBe(true);
  });

  it("allows document writes only to editor-level roles", () => {
    expect(canManageDocuments("viewer")).toBe(false);
    expect(canManageDocuments("editor")).toBe(true);
  });
});
