import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const tester = {
  id: 4,
  email: "tester@example.com",
  display_name: "Evaluation Tester",
  role: "TESTER" as const,
};

function jsonResponse(body: unknown, ok = true): Response {
  return {
    ok,
    text: async () => JSON.stringify(body),
  } as Response;
}

describe("tester pre-check workflow", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        switch (String(input)) {
          case "/api/health":
            return jsonResponse({ status: "ok" });
          case "/api/auth/session":
            return jsonResponse({ user: tester });
          case "/api/precheck":
            return jsonResponse({
              decision: "FAIL",
              summary: { total_files: 2, total_issues: 1, errors: 1, warnings: 0 },
              findings: [{ rule: "ECN-H-001", severity: "error", message: "Missing reason for change." }],
              persistence: { saved: true, attempt_id: 82, duration_seconds: 3.2 },
            });
          case "/api/tester/attempts/82/judgement":
            return jsonResponse({ saved: true });
          default:
            return jsonResponse({ attempts: [] });
        }
      }),
    );
  });

  it("uploads ECN and BOM files, then shows the returned decision and explanation", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Check an ECN before submission" })).toBeInTheDocument();
    expect(screen.getByText("AI ECN Checker")).toBeInTheDocument();
    await user.upload(screen.getByLabelText(/ECN file/), new File(["ecn data"], "change.csv", { type: "text/csv" }));
    await user.upload(screen.getByLabelText(/BOM file/), new File(["bom data"], "parts.csv", { type: "text/csv" }));
    const runButton = screen.getByRole("button", { name: "Run pre-check" });
    expect(runButton).toBeEnabled();
    fireEvent.submit(runButton.closest("form")!);

    expect(fetch).toHaveBeenCalledWith("/api/precheck", expect.objectContaining({ method: "POST" }));
    expect(await screen.findByRole("heading", { name: "FAIL — action needed" })).toBeInTheDocument();
    expect(screen.getAllByText("Missing reason for change.")).toHaveLength(2);
    expect(screen.getByText("Add the required fields to the ECN header.")).toBeInTheDocument();
    expect(screen.getByText("Evaluation saved for reviewer follow-up.")).toBeInTheDocument();

    const precheckRequest = vi.mocked(fetch).mock.calls.find(([input]) => input === "/api/precheck");
    expect(precheckRequest?.[1]?.method).toBe("POST");
    expect(precheckRequest?.[1]?.body).toBeInstanceOf(FormData);
    const submittedFiles = precheckRequest?.[1]?.body as FormData;
    expect((submittedFiles.get("ecn") as File).name).toBe("change.csv");
    expect((submittedFiles.get("bom") as File).name).toBe("parts.csv");
  });

  it("serializes manual ECN and BOM entry to the same pre-check upload endpoint", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Check an ECN before submission" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manual entry" }));
    await user.type(screen.getByLabelText(/Change notice number/), "ECN-1234567");
    await user.type(screen.getByLabelText(/Name of change/), "Update pump");
    await user.type(screen.getByLabelText(/Reason for change/), "Improve reliability");
    await user.type(screen.getByLabelText(/Description of change/), "Replace the worn pump.");
    await user.type(screen.getByLabelText(/Part number/), "P-001");
    fireEvent.submit(screen.getByRole("button", { name: "Run pre-check" }).closest("form")!);

    expect(await screen.findByRole("heading", { name: "FAIL — action needed" })).toBeInTheDocument();
    const precheckRequest = vi.mocked(fetch).mock.calls.find(([input]) => input === "/api/precheck");
    expect(precheckRequest?.[1]?.method).toBe("POST");
    const submittedFiles = precheckRequest?.[1]?.body as FormData;
    const ecnFile = submittedFiles.get("ecn") as File;
    const bomFile = submittedFiles.get("bom") as File;
    expect(ecnFile.name).toBe("ECN_1234567_manual.csv");
    expect(bomFile.name).toBe("BOM_1234567_manual.csv");
    expect(await ecnFile.text()).toContain("change_notice_number,name_of_change,reason_for_change");
    expect(await ecnFile.text()).toContain('"ECN-1234567","Update pump","Improve reliability"');
    expect(await bomFile.text()).toContain("line_number,part_number,description,quantity,unit,action,parent_part_no");
    expect(await bomFile.text()).toContain('"1","P-001"');
  });

  it("shows manual intake validation errors without sending an incomplete pre-check", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Check an ECN before submission" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manual entry" }));
    fireEvent.submit(screen.getByRole("button", { name: "Run pre-check" }).closest("form")!);

    const validationMessage = await screen.findByRole("alert");
    expect(validationMessage).toHaveTextContent("Change notice number is required.");
    expect(validationMessage).toHaveTextContent("Name of change is required.");
    expect(validationMessage).toHaveTextContent("Reason for change is required.");
    expect(validationMessage).toHaveTextContent("Description of change is required.");
    expect(validationMessage).toHaveTextContent("BOM row 1 requires a part number.");

    await user.type(screen.getByLabelText(/Change notice number/), "ECN-1234567");
    await user.type(screen.getByLabelText(/Name of change/), "Update pump");
    await user.type(screen.getByLabelText(/Reason for change/), "Improve reliability");
    await user.type(screen.getByLabelText(/Description of change/), "Replace the worn pump.");
    await user.type(screen.getByLabelText(/Part number/), "P-001");
    await user.clear(screen.getByLabelText(/Quantity/));
    await user.type(screen.getByLabelText(/Quantity/), "0");
    fireEvent.submit(screen.getByRole("button", { name: "Run pre-check" }).closest("form")!);

    expect(await screen.findByRole("alert")).toHaveTextContent("BOM row 1 quantity must be a positive number.");
    expect(vi.mocked(fetch).mock.calls.some(([input]) => input === "/api/precheck")).toBe(false);
  });

  it("records a tester judgement that disagrees with the system decision", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Check an ECN before submission" })).toBeInTheDocument();
    await user.upload(screen.getByLabelText(/ECN file/), new File(["ecn data"], "change.csv", { type: "text/csv" }));
    fireEvent.submit(screen.getByRole("button", { name: "Run pre-check" }).closest("form")!);

    expect(await screen.findByRole("heading", { name: "FAIL — action needed" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Your overall judgement"), "PASS");
    await user.type(screen.getByLabelText("Explanation"), "The required reason is present in the source document.");
    fireEvent.submit(screen.getByRole("button", { name: "Submit tester judgement" }).closest("form")!);

    expect(await screen.findByRole("status")).toHaveTextContent("Your judgement was saved for evaluation.");
    expect(screen.getByRole("heading", { name: "FAIL — action needed" })).toBeInTheDocument();
    expect(screen.getByLabelText("Your overall judgement")).toHaveValue("PASS");

    const judgementRequest = vi.mocked(fetch).mock.calls.find(
      ([input]) => input === "/api/tester/attempts/82/judgement",
    );
    expect(judgementRequest?.[1]?.method).toBe("POST");
    expect(JSON.parse(String(judgementRequest?.[1]?.body))).toEqual({
      judgement: "PASS",
      explanation: "The required reason is present in the source document.",
      rule_judgements: {},
    });
  });
});
