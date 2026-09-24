import { useEffect, useState } from "react";

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

  useEffect(() => { void loadSummary(); }, [decision, tester, ecn]);

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
    </section>
  );
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: "success" | "danger" }) {
  return <div className={`dashboard-metric ${tone ?? ""}`}><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
}
