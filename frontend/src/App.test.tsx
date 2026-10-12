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
    const runButton = screen.getByRole("button", { name: "Run Pre-check" });
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
    await user.click(screen.getByRole("button", { name: "Manual Entry" }));
    await user.type(screen.getByLabelText(/Change notice number/), "ECN-1234567");
    await user.type(screen.getByLabelText(/Name of change/), "Update pump");
    await user.type(screen.getByLabelText(/Reason for change/), "Improve reliability");
        await user.type(screen.getByLabelText(/Description of change/), "Replace the worn pump.");
    await user.click(screen.getByRole("button", { name: "Add BOM row" }));
    await user.type(screen.getByLabelText(/Part number/), "P-001");
    fireEvent.submit(screen.getByRole("button", { name: "Run Pre-check" }).closest("form")!);

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

  it("submits a valid manual ECN without a BOM and shows the saved result", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Check an ECN before submission" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manual Entry" }));
    await user.type(screen.getByLabelText(/Change notice number/), "ECN-1234567");
    await user.type(screen.getByLabelText(/Name of change/), "Update pump");
    await user.type(screen.getByLabelText(/Reason for change/), "Improve reliability");
    await user.type(screen.getByLabelText(/Description of change/), "Replace the worn pump.");
    fireEvent.submit(screen.getByRole("button", { name: "Run Pre-check" }).closest("form")!);

    expect(await screen.findByRole("heading", { name: "FAIL — action needed" })).toBeInTheDocument();
    expect(screen.getByText("Evaluation saved for reviewer follow-up.")).toBeInTheDocument();
    const precheckRequest = vi.mocked(fetch).mock.calls.find(([input]) => input === "/api/precheck");
    const submittedFiles = precheckRequest?.[1]?.body as FormData;
    expect(submittedFiles.get("ecn")).toBeInstanceOf(File);
    expect(submittedFiles.get("bom")).toBeNull();
  });

  it("shows manual intake validation errors without sending an incomplete pre-check", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Check an ECN before submission" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Manual Entry" }));
    fireEvent.submit(screen.getByRole("button", { name: "Run Pre-check" }).closest("form")!);

    const validationMessage = await screen.findByRole("alert");
    expect(validationMessage).toHaveTextContent("Change notice number is required.");
    expect(validationMessage).toHaveTextContent("Name of change is required.");
    expect(validationMessage).toHaveTextContent("Reason for change is required.");
        expect(validationMessage).toHaveTextContent("Description of change is required.");
    expect(validationMessage).not.toHaveTextContent("BOM row");

    await user.type(screen.getByLabelText(/Change notice number/), "ECN-1234567");
    await user.type(screen.getByLabelText(/Name of change/), "Update pump");
    await user.type(screen.getByLabelText(/Reason for change/), "Improve reliability");
    await user.type(screen.getByLabelText(/Description of change/), "Replace the worn pump.");
    await user.click(screen.getByRole("button", { name: "Add BOM row" }));
    await user.clear(screen.getByLabelText(/Quantity/));
    await user.type(screen.getByLabelText(/Quantity/), "0");
    fireEvent.submit(screen.getByRole("button", { name: "Run Pre-check" }).closest("form")!);

    expect(await screen.findByRole("alert")).toHaveTextContent("BOM row 1 quantity must be a positive number.");
    expect(vi.mocked(fetch).mock.calls.some(([input]) => input === "/api/precheck")).toBe(false);
  });

  it("shows tester evaluation records in pages of ten", async () => {
    const attempts = Array.from({ length: 12 }, (_, index) => ({
      attempt_id: index + 1,
      ecn_number: `ECN-${index + 1}`,
      source_status: "COMPLETED",
      decision: "PASS",
    }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/health") return jsonResponse({ status: "ok" });
      if (String(input) === "/api/auth/session") return jsonResponse({ user: tester });
      if (String(input).startsWith("/api/tester/evaluation-attempts")) return jsonResponse({ attempts });
      return jsonResponse({});
    }));

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("ECN-1")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(11);
    expect(screen.queryByText("ECN-11")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("ECN-11")).toBeInTheDocument();
    expect(screen.getByText("ECN-12")).toBeInTheDocument();
    expect(screen.queryByText("ECN-1", { selector: "td" })).not.toBeInTheDocument();
  });

  it("opens a tester-owned attempt and shows its saved result and rule evidence", async () => {
    const user = userEvent.setup();
    const detail = {
      attempt_id: 19,
      ecn_number: "4079118",
      system_decision: "FAIL",
      duration_seconds: 2.4,
      files: [{ id: 1, role: "ecn", filename: "ecn.csv", mime_type: "text/csv" }],
      findings: [{ rule_id: "H01", severity: "ERROR", message: "Reason for change is missing.", location: "header.reason_for_change", evidence: "" }],
      payload: { packet: { header: { change_notice_number: "4079118", name_of_change: "Pump update" }, bom: [{ part_number: "P-1", quantity: "1" }] } },
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/health") return jsonResponse({ status: "ok" });
      if (String(input) === "/api/auth/session") return jsonResponse({ user: tester });
      if (String(input).startsWith("/api/tester/evaluation-attempts")) {
        return jsonResponse({ attempts: [{ attempt_id: 19, ecn_number: "4079118", source_status: "DRAFT", decision: "FAIL" }] });
      }
      if (String(input) === "/api/tester/attempts/19") return jsonResponse(detail);
      return jsonResponse({});
    }));

    render(<App />);

    await user.click(await screen.findByRole("button", { name: /View results for ECN 4079118/ }));

        expect(fetch).toHaveBeenCalledWith("/api/tester/attempts/19");
    expect(await screen.findByRole("heading", { name: "System result: FAIL" })).toBeInTheDocument();
    expect(screen.getByText("Checking time: 2.40 seconds")).toBeInTheDocument();
    expect(screen.getByText("Reason for change is missing.")).toBeInTheDocument();
    expect(screen.getByText(/Source files: ecn.csv \(ecn, text\/csv\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "ECN content" }));
    expect(screen.getByText("Pump update")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "BOM content" }));
    expect(screen.getByText("P-1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit tester judgement" })).not.toBeInTheDocument();
  });

  it("records a tester judgement that disagrees with the system decision", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Check an ECN before submission" })).toBeInTheDocument();
    await user.upload(screen.getByLabelText(/ECN file/), new File(["ecn data"], "change.csv", { type: "text/csv" }));
    fireEvent.submit(screen.getByRole("button", { name: "Run Pre-check" }).closest("form")!);

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
