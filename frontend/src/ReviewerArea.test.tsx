import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ReviewerArea from "./ReviewerArea";

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, text: async () => JSON.stringify(body) } as Response;
}

describe("reviewer queue", () => {
  it("shows the ECN number as the queue item's primary label", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).startsWith("/api/reviewer/queue")) {
        return jsonResponse({
          attempts: [{ attempt_id: 17, ecn_number: "4079118", system_decision: "FAIL", review_status: "READY_FOR_REVIEW" }],
          pagination: { page: 1, page_size: 10, total: 1, total_pages: 1 },
        });
      }
      return jsonResponse({});
    }));

    render(<ReviewerArea user={{ id: 4, email: "reviewer@example.com", display_name: "Reviewer", role: "REVIEWER" }} />);

    const ecnLabel = await screen.findByText("4079118", { selector: "strong" });
    expect(ecnLabel).toBeInTheDocument();
    expect(screen.getByText(/Attempt ID 17/)).toBeInTheDocument();
  });
});
