import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminDashboard from "./AdminDashboard";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, text: async () => JSON.stringify(body) } as Response;
}

describe("administrator account management", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/admin/evaluation-summary")) return jsonResponse({ total_attempts: 0, pass_count: 0, pass_percentage: 0, fail_count: 0, fail_percentage: 0, judged_count: 0, agreement_count: 0, agreement_percentage: 0, average_duration_seconds: 0 });
      if (url.startsWith("/api/admin/evaluation-attempts")) return jsonResponse({ attempts: [] });
      if (url === "/api/admin/reviewers") return jsonResponse({ reviewers: [] });
      if (url === "/api/admin/assignable-attempts") return jsonResponse({ attempts: [] });
      if (url === "/api/admin/disputes") return jsonResponse({ attempts: [] });
      if (url === "/api/admin/review-report") return jsonResponse({});
      if (url === "/api/admin/users") {
        return jsonResponse({ user: { id: 52, email: "new.tester@example.com", display_name: "New Tester", role: "TESTER" } }, true, 201);
      }
      return jsonResponse({});
    }));
  });

  it("paginates dashboard records and identifies assignment/comparison choices by ECN number", async () => {
    const attempts = Array.from({ length: 12 }, (_, index) => ({
      attempt_id: index + 1,
      ecn_number: `ECN-${index + 1}`,
      system_decision: "PASS",
      decision: "PASS",
      source_status: "COMPLETED",
      tester_email: `tester${index + 1}@example.com`,
    }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/admin/evaluation-summary")) return jsonResponse({ total_attempts: 12, pass_count: 12, pass_percentage: 100, fail_count: 0, fail_percentage: 0, judged_count: 0, agreement_count: 0, agreement_percentage: 0, average_duration_seconds: 0 });
      if (url.startsWith("/api/admin/evaluation-attempts")) return jsonResponse({ attempts });
      if (url === "/api/admin/reviewers") return jsonResponse({ reviewers: [] });
      if (url === "/api/admin/assignable-attempts") return jsonResponse({ attempts });
      if (url === "/api/admin/disputes") return jsonResponse({ attempts: [] });
      if (url === "/api/admin/review-report") return jsonResponse({});
      if (url === "/api/admin/attempts/1/comparison") return jsonResponse({ attempt: attempts[0], submissions: [] });
      return jsonResponse({});
    }));

    const user = userEvent.setup();
    render(<AdminDashboard />);

    expect(await screen.findByText("ECN-1", { selector: "td" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(11);
    expect(screen.queryByText("ECN-11", { selector: "td" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("ECN-11", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("ECN-12", { selector: "td" })).toBeInTheDocument();
    expect(screen.queryByText("ECN-1", { selector: "td" })).not.toBeInTheDocument();

    const assignmentSelect = screen.getByLabelText("ECN to assign") as HTMLSelectElement;
        const assignmentOptions = Array.from(assignmentSelect.options).map((option) => option.textContent);
    expect(assignmentOptions).toContain("ECN-1 — PASS — tester1@example.com");
    expect(assignmentOptions.some((label) => label?.includes("Attempt 1"))).toBe(false);

    const comparisonSelect = screen.getByLabelText("ECN for comparison");
    await user.selectOptions(comparisonSelect, "1");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/admin/attempts/1/comparison"));
  });

  it("creates a user with a selected role and reports success without rendering the password", async () => {
    const user = userEvent.setup();
    render(<AdminDashboard />);

    await user.type(screen.getByLabelText("Name"), "New Tester");
    await user.type(screen.getByLabelText("Email"), "new.tester@example.com");
    await user.selectOptions(screen.getByLabelText("Role"), "TESTER");
    await user.type(screen.getByLabelText("Initial password"), "secret-for-new-user");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/admin/users", expect.objectContaining({ method: "POST" })));
    const request = vi.mocked(fetch).mock.calls.find(([input]) => input === "/api/admin/users");
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      email: "new.tester@example.com",
      display_name: "New Tester",
      role: "TESTER",
      password: "secret-for-new-user",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Account created for new.tester@example.com.");
    expect(document.body).not.toHaveTextContent("secret-for-new-user");
  });
});
