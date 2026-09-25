import { useEffect, useState } from "react";

type Reviewer = { id: number; email: string; display_name: string };
type Attempt = { attempt_id: number; system_decision: string; tester_email?: string; tester_name?: string; review_status?: string };
type Dispute = Attempt;
type Comparison = { attempt: Attempt; submissions: Array<{ submission_id: number; display_name: string; email: string; overall_judgement: string; comment?: string; rule_judgements?: Array<{ rule_id: string; judgement: string; comment?: string }> }> };

type Summary = {
  total_attempts: number;
  pass_count: number;
  pass_percentage: number;
  fail_count: number;
  fail_percentage: number;
  judged_count: number;
  agreement_count: number;
  agreement_percentage: number;
  average_duration_seconds: number;
};

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text.trim()) return {} as T;
  return JSON.parse(text) as T;
}

export default function AdminDashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [decision, setDecision] = useState("ALL");
  const [tester, setTester] = useState("");
  const [ecn, setEcn] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reviewers, setReviewers] = useState<Reviewer[]>([]);
  const [assignable, setAssignable] = useState<Attempt[]>([]);
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [selectedAttempt, setSelectedAttempt] = useState("");
  const [selectedReviewer, setSelectedReviewer] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [resolutionComment, setResolutionComment] = useState("");
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [reviewReport, setReviewReport] = useState<{ rule_group_count: number; rule_disagreement_count: number; rule_disagreement_percentage: number; disputed_attempt_count: number } | null>(null);

  async function loadSummary() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ decision, tester, ecn });
      const response = await fetch(`/api/admin/evaluation-summary?${params}`);
      const payload = await readJson<Summary & { error?: string }>(response);
      if (!response.ok) throw new Error(payload.error ?? "The dashboard could not be loaded.");
      setSummary(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The dashboard could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  async function loadAdminTools() {
    try {
      const [reviewerResponse, attemptResponse, disputeResponse, reportResponse] = await Promise.all([
        fetch("/api/admin/reviewers"), fetch("/api/admin/assignable-attempts"), fetch("/api/admin/disputes"), fetch("/api/admin/review-report"),
      ]);
      const reviewerPayload = await readJson<{ reviewers?: Reviewer[] }>(reviewerResponse);
      const attemptPayload = await readJson<{ attempts?: Attempt[] }>(attemptResponse);
      const disputePayload = await readJson<{ attempts?: Dispute[] }>(disputeResponse);
      const reportPayload = await readJson<{ rule_group_count?: number; rule_disagreement_count?: number; rule_disagreement_percentage?: number; disputed_attempt_count?: number }>(reportResponse);
      setReviewers(reviewerPayload.reviewers ?? []); setAssignable(attemptPayload.attempts ?? []); setDisputes(disputePayload.attempts ?? []);
      setReviewReport({ rule_group_count: reportPayload.rule_group_count ?? 0, rule_disagreement_count: reportPayload.rule_disagreement_count ?? 0, rule_disagreement_percentage: reportPayload.rule_disagreement_percentage ?? 0, disputed_attempt_count: reportPayload.disputed_attempt_count ?? 0 });
    } catch { setToolStatus("Administrator tools could not be loaded."); }
  }

  useEffect(() => { void loadSummary(); void loadAdminTools(); }, [decision, tester, ecn]);

  async function assignReviewer() {
    if (!selectedAttempt || !selectedReviewer) return;
    const response = await fetch("/api/admin/assignments", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ attempt_id: selectedAttempt, reviewer_id: selectedReviewer }) });
    const payload = await readJson<{ error?: string }>(response);
    setToolStatus(response.ok ? "Reviewer assigned." : payload.error ?? "Assignment failed.");
    if (response.ok) void loadAdminTools();
  }

  async function openComparison(attemptId: string) {
    const response = await fetch(`/api/admin/attempts/${attemptId}/comparison`);
    const payload = await readJson<Comparison & { error?: string }>(response);
    if (!response.ok) { setToolStatus(payload.error ?? "Comparison could not be loaded."); return; }
    setComparison(payload);
  }

  async function resolveDispute(attemptId: number) {
    const response = await fetch(`/api/admin/attempts/${attemptId}/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ comment: resolutionComment }) });
    const payload = await readJson<{ error?: string }>(response);
    setToolStatus(response.ok ? "Dispute resolved." : payload.error ?? "Dispute could not be resolved.");
    if (response.ok) { setResolutionComment(""); void loadAdminTools(); }
  }

  function exportEvaluation() {
    const params = new URLSearchParams({ decision, tester, ecn });
    window.location.href = `/api/admin/evaluation-export?${params.toString()}`;
  }

  return (
    <section className="dashboard-section" aria-labelledby="dashboard-heading">
      <div className="page-header">
        <div>
          <p className="eyebrow">Administrator</p>
          <h1 id="dashboard-heading">Evaluation dashboard</h1>
          <p className="lede">Monitor system outcomes, checking time, and agreement with tester judgements.</p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void loadSummary()}>Refresh dashboard</button>
      </div>
      <div className="dashboard-filters" aria-label="Dashboard filters">
        <label>Decision<select value={decision} onChange={(event) => setDecision(event.target.value)}><option value="ALL">All decisions</option><option value="PASS">PASS</option><option value="FAIL">FAIL</option></select></label>
        <label>Tester<input value={tester} onChange={(event) => setTester(event.target.value)} placeholder="Name or email" /></label>
        <label>ECN<input value={ecn} onChange={(event) => setEcn(event.target.value)} placeholder="ECN number" /></label>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <p className="empty-state">Loading dashboard…</p>}
      {!loading && summary && <>
        <div className="dashboard-metrics">
          <Metric label="Completed attempts" value={String(summary.total_attempts)} />
          <Metric label="PASS" value={`${summary.pass_percentage}%`} detail={`${summary.pass_count} attempts`} tone="success" />
          <Metric label="FAIL" value={`${summary.fail_percentage}%`} detail={`${summary.fail_count} attempts`} tone="danger" />
          <Metric label="Agreement" value={`${summary.agreement_percentage}%`} detail={`${summary.agreement_count}/${summary.judged_count} judged`} />
          <Metric label="Average checking" value={`${summary.average_duration_seconds}s`} detail="Pre-check start to completion" />
        </div>
        <section className="dashboard-card" aria-label="Pass and fail distribution">
          <div className="section-heading compact"><div><p className="step">System decisions</p><h2>PASS versus FAIL</h2></div><p>{summary.total_attempts} completed attempts</p></div>
          <div className="decision-bar" aria-label={`${summary.pass_percentage}% pass and ${summary.fail_percentage}% fail`}>
            <span className="decision-bar-pass" style={{ width: `${summary.pass_percentage}%` }} />
            <span className="decision-bar-fail" style={{ width: `${summary.fail_percentage}%` }} />
          </div>
          <div className="decision-legend"><span><i className="legend-dot pass-dot" />PASS {summary.pass_percentage}%</span><span><i className="legend-dot fail-dot" />FAIL {summary.fail_percentage}%</span></div>
        </section>
        <p className="dashboard-note">PASS and FAIL percentages use all completed attempts. Agreement uses only attempts where a tester judgement was submitted; {summary.total_attempts - summary.judged_count} judgement{summary.total_attempts - summary.judged_count === 1 ? " is" : "s are"} pending.</p>
      </>}
      <section className="admin-tools" aria-label="Administrator tools">
        <div className="section-heading compact"><div><p className="step">Administration</p><h2>Assignments and reviews</h2></div><button className="secondary-button" type="button" onClick={exportEvaluation}>Export evaluation CSV</button></div>
        {reviewReport && <div className="dashboard-metrics review-report"><Metric label="Rule groups reviewed" value={String(reviewReport.rule_group_count)} /><Metric label="Rule disagreements" value={`${reviewReport.rule_disagreement_percentage}%`} detail={`${reviewReport.rule_disagreement_count} groups`} tone="danger" /><Metric label="Disputed attempts" value={String(reviewReport.disputed_attempt_count)} tone="danger" /></div>}
        <div className="admin-tool-grid">
          <div className="dashboard-card"><h3>Assign reviewers</h3><label>Attempt<select value={selectedAttempt} onChange={(event) => setSelectedAttempt(event.target.value)}><option value="">Choose an attempt</option>{assignable.map((attempt) => <option key={attempt.attempt_id} value={attempt.attempt_id}>Attempt {attempt.attempt_id} — {attempt.system_decision} — {attempt.tester_email}</option>)}</select></label><label>Reviewer<select value={selectedReviewer} onChange={(event) => setSelectedReviewer(event.target.value)}><option value="">Choose a reviewer</option>{reviewers.map((reviewer) => <option key={reviewer.id} value={reviewer.id}>{reviewer.display_name} ({reviewer.email})</option>)}</select></label><button className="primary-button" type="button" onClick={() => void assignReviewer()}>Assign reviewer</button></div>
          <div className="dashboard-card"><h3>Reviewer comparison</h3><label>Attempt<select value={comparison?.attempt.attempt_id ?? ""} onChange={(event) => void openComparison(event.target.value)}><option value="">Choose an attempt</option>{assignable.map((attempt) => <option key={attempt.attempt_id} value={attempt.attempt_id}>Attempt {attempt.attempt_id}</option>)}</select></label>{comparison ? <div className="comparison-table">{comparison.submissions.map((submission) => <article key={submission.submission_id}><strong>{submission.display_name}</strong><span>{submission.overall_judgement}</span><p>{submission.comment || "No comment"}</p>{submission.rule_judgements?.map((rule) => <small key={rule.rule_id}>{rule.rule_id}: {rule.judgement}</small>)}</article>)}</div> : <p className="empty-state">Compare independent reviewer judgements for one attempt.</p>}</div>
          <div className="dashboard-card"><h3>Dispute resolution</h3>{disputes.length === 0 ? <p className="empty-state">No disputed attempts.</p> : disputes.map((dispute) => <article className="dispute-row" key={dispute.attempt_id}><strong>Attempt {dispute.attempt_id}</strong><span>{dispute.tester_email}</span><button className="evidence-link" type="button" onClick={() => void openComparison(String(dispute.attempt_id))}>Compare</button><textarea value={resolutionComment} onChange={(event) => setResolutionComment(event.target.value)} placeholder="Resolution comment" /><button className="secondary-button" type="button" onClick={() => void resolveDispute(dispute.attempt_id)}>Resolve dispute</button></article>)}</div>
        </div>
        {toolStatus && <p className="empty-state" role="status">{toolStatus}</p>}
      </section>
    </section>
  );
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: "success" | "danger" }) {
  return <div className={`dashboard-metric ${tone ?? ""}`}><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
}
