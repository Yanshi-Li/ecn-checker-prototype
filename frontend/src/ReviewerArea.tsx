import { useEffect, useRef, useState } from "react";

type User = {
  id: number;
  email: string;
  display_name: string;
  role: "TESTER" | "REVIEWER" | "ADMINISTRATOR";
};

type QueuePagination = {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

type QueueAttempt = {
  attempt_id: number;
  system_decision: "PASS" | "FAIL";
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  review_status?: string;
  tester_email?: string;
  tester_name?: string;
  assignment_status?: string;
};

type Finding = {
  category?: string;
  rule_id?: string;
  severity?: string;
  message?: unknown;
  location?: unknown;
  evidence?: unknown;
};

function displayFindingValue(value: unknown, fallback = "") {
  if (value == null || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function packetFrom(payload?: Record<string, unknown>) {
  const packet = payload?.packet;
  return packet && typeof packet === "object" ? packet as Record<string, unknown> : {};
}

function EcnSnapshot({ payload, highlightTarget }: { payload?: Record<string, unknown>; highlightTarget?: string | null }) {
  const packet = packetFrom(payload);
  const header = packet.header && typeof packet.header === "object" ? packet.header as Record<string, unknown> : {};
  const fields = Object.entries(header);
  return fields.length === 0 ? <p className="empty-state">No normalized ECN content was recorded.</p> : <dl className="source-fields">{fields.map(([key, value]) => { const text = `${key} ${displayFindingValue(value)}`; return <div className={highlightTarget && text.toLowerCase().includes(highlightTarget.toLowerCase()) ? "highlighted-source" : ""} key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{displayFindingValue(value, "—")}</dd></div>; })}</dl>;
}

function BomSnapshot({ payload, highlightTarget }: { payload?: Record<string, unknown>; highlightTarget?: string | null }) {
  const packet = packetFrom(payload);
  const rows = Array.isArray(packet.bom) ? packet.bom.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object")) : [];
  if (rows.length === 0) return <p className="empty-state">No normalized BOM content was recorded.</p>;
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return <div className="source-table-wrap"><table className="source-table"><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => { const rowText = Object.values(row).map((value) => displayFindingValue(value)).join(" "); return <tr className={highlightTarget && (rowText.toLowerCase().includes(highlightTarget.toLowerCase()) || String(row.line_number) === highlightTarget) ? "highlighted-source" : ""} key={String(row.line_number ?? index)}>{columns.map((column) => <td key={column}>{displayFindingValue(row[column], "—")}</td>)}</tr>; })}</tbody></table></div>;
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text.trim()) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error("The server returned an invalid response.");
  }
}

type AttemptDetail = QueueAttempt & {
  session_id: number;
  case_id?: number;
  task_name?: string;
  files: Array<{ id: number; role: "ecn" | "bom" | "other"; filename: string; mime_type: string }>;
  findings: Finding[];
  tester_judgement?: "PASS" | "FAIL";
  judgement_explanation?: string;
  reviewer_submission?: { overall_judgement?: "PASS" | "FAIL"; comment?: string } | null;
  payload?: Record<string, unknown>;
};

type RuleJudgement = "CORRECT" | "INCORRECT" | "UNCLEAR" | "NOT_APPLICABLE";

export default function ReviewerArea({ user }: { user: User }) {
  const [queue, setQueue] = useState<QueueAttempt[]>([]);
  const [pagination, setPagination] = useState<QueuePagination>({ page: 1, page_size: 10, total: 0, total_pages: 0 });
  const [page, setPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [decisionFilter, setDecisionFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [testerFilter, setTesterFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AttemptDetail | null>(null);
  const [sourceTab, setSourceTab] = useState<"ecn" | "bom" | "evidence">("evidence");
  const [highlightTarget, setHighlightTarget] = useState<string | null>(null);
  const [judgement, setJudgement] = useState<"PASS" | "FAIL">("PASS");
  const [comment, setComment] = useState("");
  const [ruleJudgements, setRuleJudgements] = useState<Record<string, { judgement: RuleJudgement; comment: string }>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const detailRef = useRef<HTMLElement | null>(null);

  async function loadQueue(requestedPage = page) {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(requestedPage),
        page_size: "10",
        decision: decisionFilter,
        review_status: statusFilter,
        tester: testerFilter,
      });
      const response = await fetch(`/api/reviewer/queue?${params.toString()}`);
      const payload = await readJson<{ attempts?: QueueAttempt[]; pagination?: QueuePagination; error?: string }>(response);
      if (!response.ok) throw new Error(payload.error ?? "The reviewer queue could not be loaded.");
      setQueue(payload.attempts ?? []);
      setPagination(payload.pagination ?? { page: requestedPage, page_size: 10, total: 0, total_pages: 0 });
      setPage(requestedPage);
      setPageInput(String(requestedPage));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The reviewer queue could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  function goToTypedPage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requestedPage = Number.parseInt(pageInput, 10);
    if (!Number.isFinite(requestedPage)) {
      setPageInput(String(page));
      return;
    }
    const lastPage = Math.max(1, pagination.total_pages);
    void loadQueue(Math.min(lastPage, Math.max(1, requestedPage)));
  }

  async function openAttempt(attemptId: number) {
    setSelectedId(attemptId);
    setDetail(null);
    setSourceTab("evidence");
    setHighlightTarget(null);
    detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    setStatus(null);
    setError(null);
    try {
      const response = await fetch(`/api/reviewer/attempts/${attemptId}`);
      const payload = await readJson<AttemptDetail & { error?: string }>(response);
      if (!response.ok) throw new Error(payload.error ?? "The evaluation could not be opened.");
      const normalizedDetail = {
        ...payload,
        files: payload.files ?? [],
        findings: payload.findings ?? [],
      };
      setDetail(normalizedDetail);
      setJudgement(normalizedDetail.reviewer_submission?.overall_judgement ?? "PASS");
      setComment(normalizedDetail.reviewer_submission?.comment ?? "");
      const initial: Record<string, { judgement: RuleJudgement; comment: string }> = {};
      normalizedDetail.findings.forEach((finding) => {
        if (finding.rule_id) initial[finding.rule_id] = { judgement: "CORRECT", comment: "" };
      });
      setRuleJudgements(initial);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The evaluation could not be opened.");
    }
  }

  useEffect(() => { void loadQueue(1); }, [decisionFilter, statusFilter, testerFilter]);

  async function submitJudgement(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId) return;
    setStatus("Saving judgement…");
    setError(null);
    try {
      const response = await fetch(`/api/reviewer/attempts/${selectedId}/judgement`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ judgement, comment, rule_judgements: ruleJudgements }),
      });
      const payload = await readJson<{ error?: string; review_status?: { status?: string } }>(response);
      if (!response.ok) throw new Error(payload.error ?? "The judgement could not be saved.");
      setStatus(`Judgement saved${payload.review_status?.status ? ` — ${payload.review_status.status}` : ""}.`);
      await loadQueue();
    } catch (reason) {
      setStatus(null);
      setError(reason instanceof Error ? reason.message : "The judgement could not be saved.");
    }
  }

  return (
    <section className="reviewer-section" aria-labelledby="reviewer-heading">
      <div className="page-header">
        <div>
          <p className="eyebrow">{user.role === "ADMINISTRATOR" ? "Administrator" : "Reviewer"}</p>
          <h1 id="reviewer-heading">Reviewer queue</h1>
          <p className="lede">Review assigned pre-checks without changing the system decision.</p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void loadQueue()}>Refresh queue</button>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="reviewer-layout">
        <section className="review-queue-card" aria-label="Review queue">
          <div className="section-heading compact"><div><p className="step">Reviews</p><h2>Available attempts</h2></div><p>{pagination.total} item{pagination.total === 1 ? "" : "s"}</p></div>
          <div className="queue-filters">
            <label>Decision<select value={decisionFilter} onChange={(event) => setDecisionFilter(event.target.value)}><option value="ALL">All</option><option value="PASS">PASS</option><option value="FAIL">FAIL</option></select></label>
            <label>Review status<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">All</option><option value="READY_FOR_REVIEW">Ready</option><option value="IN_REVIEW">In review</option><option value="REVIEWED">Reviewed</option><option value="DISPUTED">Disputed</option></select></label>
            <label>Tester<input value={testerFilter} onChange={(event) => setTesterFilter(event.target.value)} placeholder="Name or email" /></label>
          </div>
          {loading ? <p className="empty-state">Loading queue…</p> : queue.length === 0 ? <p className="empty-state">{user.role === "ADMINISTRATOR" ? "No completed attempts are available." : "No assigned attempts are waiting for review."}</p> : queue.map((attempt) => (
            <button className={`review-row ${selectedId === attempt.attempt_id ? "selected" : ""}`} type="button" key={attempt.attempt_id} onClick={() => void openAttempt(attempt.attempt_id)}>
              <span><strong>Attempt {attempt.attempt_id}</strong></span>
              <span className={`pill ${attempt.system_decision === "PASS" ? "success" : "error"}`}>{attempt.system_decision}</span>
              <small>{attempt.review_status ?? attempt.assignment_status ?? "ACTIVE"}</small>
            </button>
          ))}
          {pagination.total_pages > 1 && <nav className="pagination" aria-label="Attempt pages"><button type="button" disabled={page <= 1} onClick={() => void loadQueue(page - 1)}>Previous</button><form className="page-jump" onSubmit={goToTypedPage}><label htmlFor="review-page">Page</label><input id="review-page" type="number" min="1" max={pagination.total_pages} value={pageInput} onChange={(event) => setPageInput(event.target.value)} aria-label="Page number" /><span>of {pagination.total_pages}</span><button type="submit">Go</button></form><button type="button" disabled={page >= pagination.total_pages} onClick={() => void loadQueue(page + 1)}>Next</button></nav>}
        </section>
        <section ref={detailRef} className="review-detail-card" aria-label="Review attempt details">
          {!detail ? <p className="empty-state">Select an attempt to inspect its findings.</p> : <>
            <div className="section-heading compact"><div><p className="step">Attempt {detail.attempt_id}</p><h2>System result: {detail.system_decision}</h2></div><span className={`pill ${detail.system_decision === "PASS" ? "success" : "error"}`}>{detail.review_status ?? "ACTIVE"}</span></div>
            <dl className="review-meta"><div><dt>Tester</dt><dd>{detail.tester_name || detail.tester_email}</dd></div><div><dt>Duration</dt><dd>{detail.duration_seconds == null ? "—" : `${Number(detail.duration_seconds).toFixed(2)} seconds`}</dd></div></dl>
            <h3>Source and evidence</h3>
            <div className="source-tabs" role="tablist" aria-label="Attempt source content">
              <button type="button" role="tab" aria-selected={sourceTab === "ecn"} className={sourceTab === "ecn" ? "active" : ""} onClick={() => setSourceTab("ecn")}>ECN content</button>
              <button type="button" role="tab" aria-selected={sourceTab === "bom"} className={sourceTab === "bom" ? "active" : ""} onClick={() => setSourceTab("bom")}>BOM content</button>
              <button type="button" role="tab" aria-selected={sourceTab === "evidence"} className={sourceTab === "evidence" ? "active" : ""} onClick={() => setSourceTab("evidence")}>Rule evidence</button>
            </div>
            {sourceTab === "ecn" && <EcnSnapshot payload={detail.payload} highlightTarget={highlightTarget} />}
            {sourceTab === "bom" && <BomSnapshot payload={detail.payload} highlightTarget={highlightTarget} />}
            {sourceTab === "evidence" && (detail.findings.length === 0 ? <p className="empty-state">No findings were recorded.</p> : <div className="review-findings">{detail.findings.map((finding, index) => { const evidenceTarget = finding.location ?? finding.evidence; const targetText = displayFindingValue(evidenceTarget); const isBom = /bom|row|part|quantity/i.test(targetText); return <article className="review-finding" key={`${finding.rule_id}-${index}`}><strong>{finding.rule_id ?? finding.category ?? "Finding"}</strong><span className={`pill ${(finding.severity ?? "advisory").toLowerCase()}`}>{finding.severity ?? "advisory"}</span><p>{displayFindingValue(finding.message, "No explanation provided.")}</p>{finding.location != null && <small>Location: {displayFindingValue(finding.location)}</small>}{finding.evidence != null && <small>Evidence: {displayFindingValue(finding.evidence)}</small>}{evidenceTarget != null && <button className="evidence-link" type="button" onClick={() => { setHighlightTarget(targetText); setSourceTab(isBom ? "bom" : "ecn"); }}>View source evidence</button>}</article>; })}</div>)}
            <p className="source-file-note">Source files: {detail.files.map((file) => file.filename).join(", ") || "not recorded"}. Reviewers can inspect normalized content above without downloading files.</p>
            <form className="judgement-form" onSubmit={submitJudgement}>
              <h3>Submit your judgement</h3>
              <label htmlFor="overall-judgement">Overall judgement</label>
              <select id="overall-judgement" value={judgement} onChange={(event) => setJudgement(event.target.value as "PASS" | "FAIL")}><option value="PASS">PASS</option><option value="FAIL">FAIL</option></select>
              <label htmlFor="reviewer-comment">Comment</label>
              <textarea id="reviewer-comment" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Explain your judgement" />
              {detail.findings.map((finding, index) => { const id = finding.rule_id ?? `finding-${index}`; const value = ruleJudgements[id] ?? { judgement: "CORRECT" as RuleJudgement, comment: "" }; return <div className="rule-judgement" key={id}><label htmlFor={`rule-${id}`}>{id} judgement</label><select id={`rule-${id}`} value={value.judgement} onChange={(event) => setRuleJudgements({ ...ruleJudgements, [id]: { ...value, judgement: event.target.value as RuleJudgement } })}><option value="CORRECT">CORRECT</option><option value="INCORRECT">INCORRECT</option><option value="UNCLEAR">UNCLEAR</option><option value="NOT_APPLICABLE">NOT_APPLICABLE</option></select><input value={value.comment} onChange={(event) => setRuleJudgements({ ...ruleJudgements, [id]: { ...value, comment: event.target.value } })} placeholder="Rule comment (optional)" /></div>; })}
              <button className="primary-button" type="submit">Save judgement</button>
              {status && <p className="empty-state" role="status">{status}</p>}
            </form>
          </>}
        </section>
      </div>
    </section>
  );
}
