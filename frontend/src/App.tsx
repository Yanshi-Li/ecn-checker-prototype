    import { useEffect, useMemo, useState } from "react";
import ReviewerArea from "./ReviewerArea";
import AdminDashboard from "./AdminDashboard";

type Severity = "error" | "warning" | string;

type Finding = {
  rule: string;
  severity: Severity;
  message: string;
};

type User = {
  id: number;
  email: string;
  display_name: string;
  role: "TESTER" | "REVIEWER" | "ADMINISTRATOR";
};

type PrecheckResponse = {
  error?: string;
  decision: "PASS" | "FAIL" | string;
  summary: {
    total_files: number;
    total_issues: number;
    errors: number;
    warnings: number;
  };
  findings: Finding[];
  persistence: {
    saved: boolean;
    message?: string;
    attempt_id?: number;
    duration_seconds?: number;
  };
};

const FIX_HINTS: Record<string, string> = {
  UPLOAD: "Choose a file type supported by this pre-check.",
  "ECN-H-001": "Add the required fields to the ECN header.",
  "ECN-H-002": "Use an ECN number in the required format.",
  "BOM-001": "Add the required columns to the BOM file.",
  "BOM-002": "Use a quantity greater than zero.",
};

function formatRule(rule: string): string {
  return rule === "UPLOAD" ? "File upload" : `Rule ${rule}`;
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

function App() {
  const [ecnFile, setEcnFile] = useState<File | null>(null);
  const [bomFile, setBomFile] = useState<File | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [nextCheckerEmail, setNextCheckerEmail] = useState("");
  const [result, setResult] = useState<PrecheckResponse | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [apiReady, setApiReady] = useState<boolean | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [notificationStatus, setNotificationStatus] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"precheck" | "reviewer" | "dashboard">("precheck");

  useEffect(() => {
    void fetch("/api/health")
      .then((response) => setApiReady(response.ok))
      .catch(() => setApiReady(false));
    void fetch("/api/auth/session")
      .then(async (response) => {
        if (response.ok) {
          const payload = await readJson<{ user: User }>(response);
          setUser(payload.user);
        }
      })
      .finally(() => setAuthLoading(false));
  }, []);

  const findings = useMemo(() => result?.findings ?? [], [result]);
  const isPass = result?.decision === "PASS";
  const testerEmail = user?.email ?? "";

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginError(null);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: loginEmail.trim(), password: loginPassword }),
      });
      const payload = await readJson<{ error?: string; user?: User }>(response);
      if (!response.ok || !payload.user) throw new Error(payload.error ?? "Login could not be completed.");
      setUser(payload.user);
      setLoginPassword("");
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Login could not be completed.");
    }
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    setUser(null);
    setResult(null);
  }

  async function runPrecheck(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ecnFile) {
      setRequestError("Choose an ECN file before running the pre-check.");
      return;
    }
    if (!user || !["TESTER", "ADMINISTRATOR"].includes(user.role)) {
      setRequestError("Sign in with a tester or administrator account to run a pre-check.");
      return;
    }

    setSubmitting(true);
    setRequestError(null);
    setResult(null);
    setSelectedFinding(null);
    setNotificationStatus(null);

    const formData = new FormData();
    formData.append("ecn", ecnFile);
    if (bomFile) {
      formData.append("bom", bomFile);
    }

    try {
      const response = await fetch("/api/precheck", { method: "POST", body: formData });
      const payload = await readJson<PrecheckResponse>(response);
      if (!response.ok || payload.error) {
        throw new Error(payload.error ?? "The pre-check could not be completed.");
      }
      setResult(payload);
      setSelectedFinding(payload.findings[0] ?? null);
    } catch (error) {
      setRequestError(
        error instanceof Error ? error.message : "The pre-check could not be completed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function sendReport() {
    if (!result?.persistence.attempt_id) return;
    const recipient = isPass ? nextCheckerEmail.trim() : testerEmail.trim();
    if (!recipient) {
      setNotificationStatus("Enter the next checker's email before sending this passed result.");
      return;
    }
    setNotificationStatus("Sending validation report…");
    try {
      const response = await fetch("/api/notification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          attempt_id: result.persistence.attempt_id,
          recipient,
        }),
      });
      const payload = await readJson<{ error?: string; message?: string }>(response);
      if (!response.ok || payload.error) throw new Error(payload.error ?? "Email could not be sent.");
      setNotificationStatus(payload.message ?? "Validation report sent.");
    } catch (error) {
      setNotificationStatus(error instanceof Error ? error.message : "Email could not be sent.");
    }
  }

  function downloadReport() {
    if (!result) return;
    const lines = [
      "ECN Pre-check report",
      "",
      `Decision: ${isPass ? "PASS" : "FAIL"}`,
      `Files checked: ${result.summary.total_files}`,
      `Errors: ${result.summary.errors}`,
      `Warnings: ${result.summary.warnings}`,
      "",
      ...result.findings.map(
        (finding) => `[${finding.severity.toUpperCase()}] ${finding.rule}: ${finding.message}`,
      ),
    ];
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "ecn-precheck-report.txt";
    link.click();
    URL.revokeObjectURL(url);
  }

  if (authLoading) {
    return <main className="login-shell"><p>Checking your sign-in session…</p></main>;
  }

  if (!user) {
    return (
      <main className="login-shell">
        <form className="login-card" onSubmit={login}>
          <div className="brand-mark">ECN</div>
          <p className="eyebrow">ECN Checker</p>
          <h1>Sign in to pre-check</h1>
          <p className="lede">Use the account created for your evaluation role.</p>
          <label htmlFor="login-email">Email</label>
          <input id="login-email" type="email" required value={loginEmail} onChange={(event) => setLoginEmail(event.target.value)} />
          <label htmlFor="login-password">Password</label>
          <input id="login-password" type="password" required value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} />
          {loginError && <p className="form-error" role="alert">{loginError}</p>}
          <button className="primary-button" type="submit">Sign in</button>
        </form>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand-mark">ECN</div>
        <div className="brand">
          <strong>ECN Checker</strong>
          <span>Pre-check workspace</span>
        </div>
        <nav>
          <button className={`nav-item ${activeTab === "precheck" ? "active" : ""}`} type="button" onClick={() => setActiveTab("precheck")}>New pre-check</button>
          {["REVIEWER", "ADMINISTRATOR"].includes(user.role) && <button className={`nav-item ${activeTab === "reviewer" ? "active" : ""}`} type="button" onClick={() => setActiveTab("reviewer")}>Reviewer queue</button>}
          {user.role === "ADMINISTRATOR" && <button className={`nav-item ${activeTab === "dashboard" ? "active" : ""}`} type="button" onClick={() => setActiveTab("dashboard")}>Admin dashboard</button>}
        </nav>
        <div className="connection-status">
          <span className={`status-dot ${apiReady ? "online" : "offline"}`} />
          {apiReady === null ? "Connecting to validation API…" : apiReady ? "Validation API connected" : "Start Flask on port 5000"}
        </div>
      </aside>

      <section className="content">
        {activeTab !== "reviewer" && activeTab !== "dashboard" && <header className="page-header">
          <div>
            <p className="eyebrow">ECN creator</p>
            <h1>Check an ECN before submission</h1>
            <p className="lede">Upload an ECN and optional BOM. We will show the outcome and the next action clearly.</p>
          </div>
          <div className="signed-in-user">
            <span>Signed in as</span>
            <strong>{user.display_name}</strong>
            <small>{user.email}</small>
            <button type="button" onClick={() => void logout()}>Sign out</button>
          </div>
        </header>}

        {activeTab === "dashboard" && user.role === "ADMINISTRATOR" ? <AdminDashboard /> : activeTab === "reviewer" && ["REVIEWER", "ADMINISTRATOR"].includes(user.role) ? <ReviewerArea user={user} /> : <>
        <section className="upload-card" id="new-precheck" aria-labelledby="upload-heading">
          <div className="section-heading">
            <div>
              <p className="step">Step 1</p>
              <h2 id="upload-heading">Choose files</h2>
            </div>
            <p>ECN is required. BOM is optional.</p>
          </div>
          <form onSubmit={runPrecheck}>
            <div className="file-grid">
              <FileInput
                id="ecn-file"
                label="ECN file"
                required
                accept=".csv,.xls,.xlsx,.xlsm,.pdf,.eml,.txt"
                file={ecnFile}
                onChange={setEcnFile}
              />
              <FileInput
                id="bom-file"
                label="BOM file"
                accept=".csv,.xls,.xlsx,.xlsm,.pdf"
                file={bomFile}
                onChange={setBomFile}
              />
            </div>
            {requestError && <p className="form-error" role="alert">{requestError}</p>}
            <button className="primary-button" type="submit" disabled={submitting || apiReady === false}>
              {submitting ? "Running pre-check…" : "Run pre-check"}
            </button>
          </form>
        </section>

        {result && (
          <section id="results" className="results-section" aria-live="polite">
            <div className={`decision-card ${isPass ? "pass" : "fail"}`}>
              <div>
                <p className="eyebrow">Pre-check result</p>
                <h2>{isPass ? "PASS — ready for the next checker" : "FAIL — action needed"}</h2>
                <p>
                  {isPass
                    ? "No blocking issues were found. Review any warnings before sharing the result."
                    : "Resolve the blocking issues below, then run the pre-check again."}
                </p>
              </div>
              <div className="result-actions">
                <button className="secondary-button" type="button" onClick={downloadReport}>Download report</button>
                {result.persistence.saved && (isPass ? (
                  <div className="next-checker-action">
                    <label htmlFor="next-checker-email">Next checker email</label>
                    <input
                      id="next-checker-email"
                      type="email"
                      value={nextCheckerEmail}
                      onChange={(event) => setNextCheckerEmail(event.target.value)}
                      placeholder="checker@example.com"
                    />
                    <button className="secondary-button" type="button" onClick={() => void sendReport()}>
                      Send to next checker
                    </button>
                  </div>
                ) : (
                  <button className="secondary-button" type="button" onClick={() => void sendReport()}>
                    Email result to me
                  </button>
                ))}
              </div>
            </div>

            {!result.persistence.saved && <p className="form-error" role="status">{result.persistence.message ?? "The result is available, but the evaluation was not saved."}</p>}
            {result.persistence.saved && <p className="empty-state">Evaluation saved for reviewer follow-up.</p>}
            {notificationStatus && <p className="empty-state" role="status">{notificationStatus}</p>}

            <div className="metric-grid" aria-label="Pre-check summary">
              <Metric label="Files checked" value={String(result.summary.total_files)} />
              <Metric label="Blocking issues" value={String(result.summary.errors)} tone={result.summary.errors ? "danger" : "success"} />
              <Metric label="Warnings" value={String(result.summary.warnings)} />
              <Metric label="Findings" value={String(result.summary.total_issues)} />
            </div>

            <div className="findings-layout">
              <section className="finding-list" aria-labelledby="findings-heading">
                <div className="section-heading compact">
                  <div><p className="step">Step 2</p><h2 id="findings-heading">Review findings</h2></div>
                  <p>{findings.length} item{findings.length === 1 ? "" : "s"}</p>
                </div>
                {findings.length === 0 ? (
                  <p className="empty-state">No findings. This pre-check is ready to share.</p>
                ) : findings.map((finding, index) => (
                  <button
                    className={`finding-row ${finding.severity} ${selectedFinding === finding ? "selected" : ""}`}
                    type="button"
                    key={`${finding.rule}-${index}`}
                    onClick={() => setSelectedFinding(finding)}
                  >
                    <span className="severity-dot" />
                    <span><strong>{formatRule(finding.rule)}</strong><small>{finding.message}</small></span>
                  </button>
                ))}
              </section>
              <section className="finding-detail" aria-labelledby="detail-heading">
                <p className="step">Selected finding</p>
                {selectedFinding ? (
                  <>
                    <h2 id="detail-heading">{formatRule(selectedFinding.rule)}</h2>
                    <span className={`pill ${selectedFinding.severity}`}>{selectedFinding.severity}</span>
                    <h3>What happened</h3>
                    <p>{selectedFinding.message}</p>
                    <h3>What to do next</h3>
                    <p>{FIX_HINTS[selectedFinding.rule] ?? "Review the source file, correct the issue, and run the pre-check again."}</p>
                  </>
                ) : <p id="detail-heading" className="empty-state">Select a finding to see its explanation.</p>}
              </section>
            </div>
          </section>
        )}
        </>}
      </section>
    </main>
  );
}

type FileInputProps = {
  id: string;
  label: string;
  required?: boolean;
  accept: string;
  file: File | null;
  onChange: (file: File | null) => void;
};

function FileInput({ id, label, required = false, accept, file, onChange }: FileInputProps) {
  return (
    <label className="file-input" htmlFor={id}>
      <span className="file-label">{label} {required && <em>Required</em>}</span>
      <span className="file-description">{file ? file.name : "Choose a file or drag it here"}</span>
      <span className="file-action">Browse files</span>
      <input id={id} type="file" required={required} accept={accept} onChange={(event) => onChange(event.target.files?.[0] ?? null)} />
    </label>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "danger" | "success" }) {
  return <div className={`metric ${tone ?? ""}`}><span>{label}</span><strong>{value}</strong></div>;
}

export default App;
