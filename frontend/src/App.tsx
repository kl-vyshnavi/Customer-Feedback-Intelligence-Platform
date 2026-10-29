import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownToLine, ArrowUpRight, BarChart3, Check, ChevronDown, CircleAlert,
  Database, FileText, Filter, LayoutDashboard, LoaderCircle, MessageSquareText, Search,
  ShieldCheck, Sparkles, Upload, WandSparkles,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { API_URL, api, queryString, type Dashboard, type FeedbackItem, type Filters, type ImportBatch, type Issue, type IssueDetail, type Recommendation } from "./api";

type Page = "Dashboard" | "Feedback" | "Issues" | "Recommendations" | "Imports";
const pages: { name: Page; icon: typeof LayoutDashboard }[] = [
  { name: "Dashboard", icon: LayoutDashboard },
  { name: "Feedback", icon: MessageSquareText },
  { name: "Issues", icon: Activity },
  { name: "Recommendations", icon: Sparkles },
  { name: "Imports", icon: Upload },
];

const emptyDashboard: Dashboard = {
  total_feedback: 0,
  issue_group_count: 0,
  recommendation_count: 0,
  sentiment_counts: { positive: 0, neutral: 0, negative: 0 },
  category_counts: {},
  feedback_over_time: [],
  rating_trends: [],
  priority_issues: [],
};

export default function App() {
  const [page, setPage] = useState<Page>("Dashboard");
  const [dashboard, setDashboard] = useState<Dashboard>(emptyDashboard);
  const [feedback, setFeedback] = useState<FeedbackItem[]>([]);
  const [feedbackPage, setFeedbackPage] = useState(1);
  const [feedbackPages, setFeedbackPages] = useState(1);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [issueDetail, setIssueDetail] = useState<IssueDetail | null>(null);
  const [issueDetailLoading, setIssueDetailLoading] = useState(false);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [importBatches, setImportBatches] = useState<ImportBatch[]>([]);
  const [filters, setFilters] = useState<Filters>({});
  const [searchDraft, setSearchDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [columnMapping, setColumnMapping] = useState("");
  const [importStatus, setImportStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const filtersQuery = useMemo(() => queryString(filters), [filters]);
  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const suffix = filtersQuery ? `?${filtersQuery}` : "";
      const [dashboardResult, feedbackResult, issueResult, recommendationResult, importResult] = await Promise.all([
        api<Dashboard>(`/dashboard${suffix}`),
        api<{ items: FeedbackItem[]; pages: number }>(`/feedback?page=${feedbackPage}&page_size=25${filtersQuery ? `&${filtersQuery}` : ""}`),
        api<Issue[]>(`/issues${suffix}`),
        api<Recommendation[]>(`/recommendations${suffix}`),
        api<ImportBatch[]>("/imports"),
      ]);
      setDashboard(dashboardResult);
      setFeedback(feedbackResult.items);
      setFeedbackPages(feedbackResult.pages);
      setIssues(issueResult);
      setRecommendations(recommendationResult);
      setImportBatches(importResult);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load data");
    } finally {
      setLoading(false);
    }
  }, [feedbackPage, filtersQuery, refresh]);

  useEffect(() => { void loadData(); }, [loadData]);

  function applySearch(event: React.FormEvent) {
    event.preventDefault();
    setFeedbackPage(1);
    setFilters((current) => ({ ...current, search: searchDraft || undefined }));
  }

  function updateFilter(key: keyof Filters, value: string) {
    setFeedbackPage(1);
    setIssueDetail(null);
    setFilters((current) => ({ ...current, [key]: value || undefined }));
  }

  async function openIssue(issueId: number) {
    setIssueDetailLoading(true);
    setError("");
    try {
      setIssueDetail(await api<IssueDetail>(`/issues/${issueId}${filtersQuery ? `?${filtersQuery}` : ""}`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load issue evidence");
    } finally {
      setIssueDetailLoading(false);
    }
  }

  async function correctFeedback(id: number, field: "sentiment" | "category" | "severity", value: string) {
    try {
      await api<FeedbackItem>(`/feedback/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      setRefresh((current) => current + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Classification correction failed");
    }
  }

  async function uploadFile(file?: File) {
    if (!file) return;
    setBusy(true);
    setImportStatus("");
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      if (columnMapping.trim()) body.append("mapping", columnMapping);
      const result = await api<Record<string, unknown>>("/imports/preview", { method: "POST", body });
      setPreview(result);
      setImportStatus("Preview ready. Review the rows and import summary before confirming.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "CSV preview failed");
    } finally {
      setBusy(false);
    }
  }

  async function confirmImport() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ imported_rows: number; duplicate_rows: number }>("/imports/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ batch_id: preview.batch_id }),
      });
      setImportStatus(`Imported ${result.imported_rows} row(s); skipped ${result.duplicate_rows} duplicate(s).`);
      setPreview(null);
      setRefresh((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Import confirmation failed");
    } finally {
      setBusy(false);
    }
  }

  async function download(path: string) {
    try {
      const response = await fetch(`${API_URL}/api/v1${path}`);
      if (!response.ok) throw new Error(`Export failed (${response.status})`);
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = path.includes("issues") ? "issue_priorities.csv" : "feedback_export.csv";
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not download export");
    }
  }

  const negative = dashboard.sentiment_counts.negative ?? 0;
  const negativeShare = dashboard.total_feedback ? Math.round((negative / dashboard.total_feedback) * 100) : 0;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={19} strokeWidth={2.5} /></div>
          <div><strong>signal desk</strong><span>FEEDBACK INTELLIGENCE</span></div>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {pages.map(({ name, icon: Icon }) => (
            <button key={name} className={`nav-item ${page === name ? "active" : ""}`} onClick={() => setPage(name)}>
              <Icon size={17} /><span>{name}</span>{name === "Issues" && issues.length > 0 && <span className="nav-count">{issues.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-card"><ShieldCheck size={17} /><span>Your feedback stays in your workspace.</span></div>
          <div className="user-row"><div className="avatar">SD</div><div><strong>Local workspace</strong><span>Personal account</span></div><ChevronDown size={15} /></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumbs">Workspace <span>/</span> <strong>{page}</strong></div>
          <div className="topbar-right"><span className="status-dot" /> Local data <span className="topbar-divider" /><button className="icon-button" aria-label="Export feedback" onClick={() => void download(`/exports/feedback.csv${filtersQuery ? `?${filtersQuery}` : ""}`)}><ArrowDownToLine size={17} /></button></div>
        </header>
        <div className="page-wrap">
          {error && <div className="alert error-alert" role="alert"><CircleAlert size={18} />{error}<button onClick={() => setError("")}>Dismiss</button></div>}
          {(page === "Issues" || page === "Recommendations") && <FilterControls filters={filters} updateFilter={updateFilter} />}
          {page === "Dashboard" && <DashboardPage dashboard={dashboard} negativeShare={negativeShare} loading={loading} onNavigate={setPage} filters={filters} updateFilter={updateFilter} />}
          {page === "Feedback" && <FeedbackPage feedback={feedback} loading={loading} filters={filters} searchDraft={searchDraft} setSearchDraft={setSearchDraft} applySearch={applySearch} updateFilter={updateFilter} page={feedbackPage} pages={feedbackPages} onPageChange={setFeedbackPage} onCorrect={correctFeedback} download={() => void download(`/exports/feedback.csv${filtersQuery ? `?${filtersQuery}` : ""}`)} />}
          {page === "Issues" && <IssuesPage issues={issues} loading={loading} detail={issueDetail} detailLoading={issueDetailLoading} onIssueSelect={openIssue} onBack={() => setIssueDetail(null)} download={() => void download(`/exports/issues.csv${filtersQuery ? `?${filtersQuery}` : ""}`)} />}
          {page === "Recommendations" && <RecommendationsPage recommendations={recommendations} loading={loading} />}
          {page === "Imports" && (
            <>
              <ImportsPage preview={preview} status={importStatus} busy={busy} mapping={columnMapping} setMapping={setColumnMapping} onFile={uploadFile} onConfirm={confirmImport} onReset={() => { setPreview(null); setImportStatus(""); }} />
              <ImportHistoryTable batches={importBatches} />
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

function DashboardPage({ dashboard, negativeShare, loading, onNavigate, filters, updateFilter }: { dashboard: Dashboard; negativeShare: number; loading: boolean; onNavigate: (page: Page) => void; filters: Filters; updateFilter: (key: keyof Filters, value: string) => void }) {
  if (loading) return <Loading />;
  return <>
    <PageHeading eyebrow="OVERVIEW" title="Good morning." description="Here's what customers have been telling you." action={<button className="button primary" onClick={() => onNavigate("Imports")}><Upload size={16} /> Import feedback</button>} />
    <FilterControls filters={filters} updateFilter={updateFilter} />
    <div className="kpi-grid">
      <Kpi label="Total feedback" value={dashboard.total_feedback.toLocaleString()} icon={<MessageSquareText size={17} />} detail="Across all imports" />
      <Kpi label="Negative feedback" value={`${negativeShare}%`} icon={<CircleAlert size={17} />} detail={`${dashboard.sentiment_counts.negative ?? 0} items need a closer look`} tone="orange" />
      <Kpi label="Recurring issues" value={dashboard.issue_group_count.toString()} icon={<Activity size={17} />} detail="Grouped by similar wording" tone="blue" />
      <Kpi label="Recommendations" value={dashboard.recommendation_count.toString()} icon={<Sparkles size={17} />} detail="Evidence-backed next steps" tone="purple" />
    </div>
    <div className="dashboard-grid">
      <section className="panel trend-panel">
        <div className="panel-heading"><div><h2>Feedback volume</h2><p>Customer feedback received over time</p></div><span className="panel-tag"><BarChart3 size={14} /> ACTUAL DATA</span></div>
        {dashboard.feedback_over_time.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={dashboard.feedback_over_time} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}><defs><linearGradient id="volumeFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5748c9" stopOpacity={0.19} /><stop offset="95%" stopColor="#5748c9" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#eef0f5" vertical={false} /><XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#9298a8" }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#9298a8" }} /><Tooltip /><Area type="monotone" dataKey="count" stroke="#5748c9" strokeWidth={2.5} fill="url(#volumeFill)" /></AreaChart></ResponsiveContainer></div> : <EmptyState title="No feedback yet" detail="Import customer feedback to see trends here." />}
      </section>
      <section className="panel sentiment-panel">
        <div className="panel-heading"><div><h2>Sentiment</h2><p>Classification of imported feedback</p></div></div>
        {dashboard.total_feedback ? <div className="sentiment-list">{(["negative", "neutral", "positive"] as const).map((sentiment) => {
          const count = dashboard.sentiment_counts[sentiment] ?? 0;
          const pct = Math.round(count / dashboard.total_feedback * 100);
          return <div className="sentiment-row" key={sentiment}><div className="sentiment-label"><span className={`sentiment-dot ${sentiment}`} />{sentiment}<strong>{count}</strong></div><div className="progress-track"><div className={`progress-fill ${sentiment}`} style={{ width: `${pct}%` }} /></div><span className="sentiment-pct">{pct}%</span></div>;
        })}</div> : <EmptyState title="Waiting for feedback" detail="Sentiment appears after your first import." />}
      </section>
    </div>
    <div className="dashboard-grid secondary-grid">
      <section className="panel">
        <div className="panel-heading"><div><h2>Complaint categories</h2><p>Current filtered volume by category</p></div></div>
        {Object.keys(dashboard.category_counts).length ? <div className="category-list">{Object.entries(dashboard.category_counts).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([category, count]) => <div key={category}><span>{category}</span><div className="category-track"><i style={{ width: `${Math.max(4, count / Math.max(...Object.values(dashboard.category_counts)) * 100)}%` }} /></div><strong>{count}</strong></div>)}</div> : <EmptyState title="No categories yet" detail="Category counts appear after feedback is imported." />}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><h2>Rating trend</h2><p>Average rating per day, when ratings are provided</p></div></div>
        {dashboard.rating_trends.length ? <div className="chart rating-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={dashboard.rating_trends} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}><CartesianGrid stroke="#eef0f5" vertical={false} /><XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#9298a8" }} /><YAxis domain={[0, 5]} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#9298a8" }} /><Tooltip /><Area type="monotone" dataKey="average_rating" stroke="#55a787" strokeWidth={2} fill="#eaf5ef" /></AreaChart></ResponsiveContainer></div> : <EmptyState title="No ratings available" detail="Rating trends appear when imported CSV rows include ratings and dates." />}
      </section>
    </div>
    <section className="panel issue-panel"><div className="panel-heading"><div><h2>Highest-priority issues</h2><p>Ranked using frequency, severity, recency, sentiment, and ratings</p></div><button className="text-button" onClick={() => onNavigate("Issues")}>View all <ArrowUpRight size={14} /></button></div>
      {dashboard.priority_issues.length ? <IssueTable issues={dashboard.priority_issues} /> : <EmptyState title="No recurring issues yet" detail="Import feedback to identify patterns worth addressing." />}
    </section>
  </>;
}

function Kpi({ label, value, icon, detail, tone = "green" }: { label: string; value: string; icon: React.ReactNode; detail: string; tone?: string }) {
  return <div className="kpi-card"><div className="kpi-top"><span>{label}</span><span className={`kpi-icon ${tone}`}>{icon}</span></div><div className="kpi-value">{value}</div><div className="kpi-detail">{detail}</div></div>;
}

function FeedbackPage({ feedback, loading, filters, searchDraft, setSearchDraft, applySearch, updateFilter, page, pages, onPageChange, onCorrect, download }: { feedback: FeedbackItem[]; loading: boolean; filters: Filters; searchDraft: string; setSearchDraft: (value: string) => void; applySearch: (event: React.FormEvent) => void; updateFilter: (key: keyof Filters, value: string) => void; page: number; pages: number; onPageChange: (page: number) => void; onCorrect: (id: number, field: "sentiment" | "category" | "severity", value: string) => void; download: () => void }) {
  return <>
    <PageHeading eyebrow="CUSTOMER VOICE" title="Feedback" description="Review original feedback alongside its classification and evidence." action={<button className="button secondary" onClick={download}><ArrowDownToLine size={16} /> Export CSV</button>} />
    <div className="toolbar"><form className="search-box" onSubmit={applySearch}><Search size={16} /><input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="Search customer feedback…" aria-label="Search feedback" /><button type="submit">Search</button></form><Filter size={16} className="filter-icon" /></div>
    <FilterControls filters={filters} updateFilter={updateFilter} />
    <section className="panel table-panel">{loading ? <Loading /> : feedback.length ? <><div className="table-scroll"><table><thead><tr><th>Customer feedback</th><th>Sentiment</th><th>Category</th><th>Severity</th><th>Rating</th><th>Date</th></tr></thead><tbody>{feedback.map((item) => <tr key={item.id}><td className="feedback-cell"><strong>{item.summary}</strong><span>{item.text}</span>{item.product && <small>{item.product}</small>}</td><td><CorrectionSelect label={`Correct sentiment for feedback ${item.id}`} value={item.sentiment} predicted={item.predicted_sentiment} options={["positive", "neutral", "negative"]} onChange={(value) => onCorrect(item.id, "sentiment", value)} /></td><td><CorrectionSelect label={`Correct category for feedback ${item.id}`} value={item.category} predicted={item.predicted_category} options={["pricing", "product quality", "delivery", "customer support", "usability", "billing", "other"]} onChange={(value) => onCorrect(item.id, "category", value)} /></td><td><CorrectionSelect label={`Correct severity for feedback ${item.id}`} value={item.severity} predicted={item.predicted_severity} options={["low", "medium", "high"]} onChange={(value) => onCorrect(item.id, "severity", value)} /></td><td>{item.rating ? `${item.rating} / 5` : "—"}</td><td>{item.received_at ? new Date(item.received_at).toLocaleDateString() : "—"}</td></tr>)}</tbody></table></div><div className="pagination"><span>Page {page} of {Math.max(pages, 1)}</span><div><button className="button secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>Previous</button><button className="button secondary" disabled={page >= pages} onClick={() => onPageChange(page + 1)}>Next</button></div></div></> : <EmptyState title="No matching feedback" detail="Try changing your filters or import a CSV file." />}</section>
  </>;
}

function IssuesPage({ issues, loading, detail, detailLoading, onIssueSelect, onBack, download }: { issues: Issue[]; loading: boolean; detail: IssueDetail | null; detailLoading: boolean; onIssueSelect: (id: number) => void; onBack: () => void; download: () => void }) {
  if (detailLoading) return <Loading />;
  if (detail) return <IssueDetailView issue={detail} onBack={onBack} />;
  return <><PageHeading eyebrow="PATTERNS" title="Recurring issues" description="Similar feedback is grouped using TF-IDF text similarity within each category." action={<button className="button secondary" onClick={download}><ArrowDownToLine size={16} /> Export priorities</button>} />{loading ? <Loading /> : issues.length ? <div className="issue-cards">{issues.map((issue) => <IssueCard key={issue.id} issue={issue} onSelect={onIssueSelect} />)}</div> : <section className="panel"><EmptyState title="No issues to show" detail="Import feedback to discover recurring customer problems." /></section>}</>;
}

function IssueTable({ issues }: { issues: Issue[] }) {
  return <div className="table-scroll"><table><thead><tr><th>Issue</th><th>Category</th><th>Feedback</th><th>Priority</th><th>Score</th></tr></thead><tbody>{issues.slice(0, 5).map((issue) => <tr key={issue.id}><td className="issue-title-cell"><span className="issue-indicator" />{issue.title}</td><td>{issue.category}</td><td>{issue.count}</td><td><Badge value={issue.priority_level} /></td><td className="score-cell">{issue.priority_score}</td></tr>)}</tbody></table></div>;
}

function IssueCard({ issue, onSelect }: { issue: Issue; onSelect: (id: number) => void }) {
  return <article className="panel issue-card"><div className="issue-card-top"><Badge value={issue.priority_level} /><span className="issue-score">{issue.priority_score}<small>/ 100</small></span></div><h2>{issue.title}</h2><p>{issue.count} supporting feedback item(s) · {issue.category}</p><ul>{issue.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>{issue.recommendation && <div className="recommendation-callout"><strong>Suggested action</strong><p>{issue.recommendation.suggested_action}</p></div>}<button className="text-button issue-evidence-button" onClick={() => onSelect(issue.id)}>Inspect supporting feedback <ArrowUpRight size={14} /></button></article>;
}

function IssueDetailView({ issue, onBack }: { issue: IssueDetail; onBack: () => void }) {
  return <>
    <button className="text-button back-button" onClick={onBack}>← Back to issues</button>
    <PageHeading eyebrow="ISSUE DETAIL" title={issue.title} description={`${issue.count} supporting feedback item(s) · ${issue.category}`} />
    <div className="kpi-grid detail-kpis"><Kpi label="Priority score" value={`${issue.priority_score} / 100`} icon={<Activity size={17} />} detail={`Priority ${issue.priority_level}`} tone="blue" /><Kpi label="Supporting feedback" value={issue.feedback.length.toString()} icon={<MessageSquareText size={17} />} detail="Records in this issue group" tone="purple" /></div>
    <div className="dashboard-grid">
      <section className="panel"><div className="panel-heading"><div><h2>Feedback volume</h2><p>Supporting records by day</p></div></div>{issue.feedback_over_time.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={issue.feedback_over_time}><CartesianGrid stroke="#eef0f5" vertical={false} /><XAxis dataKey="date" tickLine={false} axisLine={false} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} /><Tooltip /><Area dataKey="count" stroke="#5748c9" fill="#efedf9" /></AreaChart></ResponsiveContainer></div> : <EmptyState title="No dates available" detail="Date trends require dates in the source CSV." />}</section>
      <section className="panel"><div className="panel-heading"><div><h2>Priority rationale</h2><p>Weighted contributions to the 0–100 score</p></div></div><div className="sentiment-list">{Object.entries(issue.contributions).map(([name, value]) => <div className="component-row" key={name}><span>{name.replaceAll("_", " ")}</span><strong title={`Component ${Math.round(issue.components[name] * 100)}% × weight ${Math.round(issue.weights[name] * 100)}%`}>{(value * 100).toFixed(1)} pts</strong><div className="progress-track"><div className="progress-fill neutral" style={{ width: `${value * 100}%` }} /></div></div>)}</div>{issue.reasons.map((reason) => <p className="detail-reason" key={reason}>{reason}</p>)}</section>
    </div>
    <section className="panel evidence-panel"><div className="panel-heading"><div><h2>Supporting feedback</h2><p>Original customer text and current classification</p></div></div>{issue.feedback.map((item) => <article className="evidence-item" key={item.id}><p>“{item.text}”</p><div><Badge value={item.sentiment} /><Badge value={item.severity} /><span>{item.category}</span><small>{item.received_at ? new Date(item.received_at).toLocaleDateString() : "No date"} · Record #{item.id}</small></div></article>)}</section>
  </>;
}

function RecommendationsPage({ recommendations, loading }: { recommendations: Recommendation[]; loading: boolean }) {
  return <><PageHeading eyebrow="NEXT STEPS" title="Recommendations" description="Practical actions tied to real customer evidence. Outcomes are hypotheses until measured." />{loading ? <Loading /> : recommendations.length ? <div className="recommendation-grid">{recommendations.map((item) => <article className="panel recommendation-card" key={item.id}><div className="recommendation-icon"><WandSparkles size={18} /></div><div className="eyebrow">ISSUE · {item.category}</div><h2>{item.issue_title}</h2><p className="recommendation-problem">{item.problem}</p><div className="evidence-block"><span>WHY IT MATTERS</span><p>{item.why_it_matters}</p><small>Supporting records: {item.feedback_ids.map((id) => `#${id}`).join(", ")}</small></div><div className="action-block"><span>TRY THIS</span><p>{item.suggested_action}</p></div><div className="hypothesis"><Sparkles size={15} /><span>{item.expected_outcome}</span></div><small className="measure-label">Measure: {item.evaluation_method}</small></article>)}</div> : <section className="panel"><EmptyState title="No recommendations yet" detail="Higher-severity patterns generate evidence-linked actions after import." /></section>}</>;
}

function ImportsPage({ preview, status, busy, mapping, setMapping, onFile, onConfirm, onReset }: { preview: Record<string, unknown> | null; status: string; busy: boolean; mapping: string; setMapping: (value: string) => void; onFile: (file?: File) => void; onConfirm: () => void; onReset: () => void }) {
  return <><PageHeading eyebrow="DATA" title="Import feedback" description="Bring customer reviews, surveys, and support conversations into one place." /><div className="import-layout"><section className="panel import-panel"><div className="import-icon"><Database size={22} /></div><h2>Upload a CSV file</h2><p>Preview and validate your data before it is added to the workspace.</p><label className="drop-zone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); onFile(event.dataTransfer.files[0]); }}><input type="file" accept=".csv,text/csv" aria-label="Choose CSV file" onChange={(event) => onFile(event.target.files?.[0])} /><span className="upload-circle"><Upload size={19} /></span><strong>{busy ? "Preparing preview…" : "Choose a CSV file"}</strong><span>or drag and drop here</span><small>CSV files up to 5 MB</small></label><label className="mapping-label">Optional column mapping JSON<input value={mapping} onChange={(event) => setMapping(event.target.value)} placeholder={'{"text":"review_body","rating":"stars"}'} aria-label="Column mapping JSON" /></label><small className="demo-note">The sample file is demo data; no sample metrics are preloaded.</small><a className="sample-link" href={`${API_URL}/api/v1/imports/sample.csv`}><FileText size={15} /> Download a sample CSV</a>{status && <div className="alert success-alert"><Check size={17} />{status}</div>}</section><section className="panel import-guide"><h2>Before you import</h2><div className="guide-item"><span className="guide-number">01</span><div><strong>Include feedback text</strong><p>Common column names like review, comment, or message are detected automatically.</p></div></div><div className="guide-item"><span className="guide-number">02</span><div><strong>Add context when available</strong><p>Date, rating (1–5), product, and customer ID enrich issue prioritization.</p></div></div><div className="guide-item"><span className="guide-number">03</span><div><strong>Review before importing</strong><p>Malformed rows and duplicates are reported before anything is committed.</p></div></div><div className="privacy-note"><ShieldCheck size={17} /><span>Feedback is stored locally in your configured database. Treat uploaded customer data as sensitive.</span></div></section></div>{preview && <section className="panel preview-panel"><div className="panel-heading"><div><h2>Import preview</h2><p>{String(preview.filename)}</p></div><button className="text-button" onClick={onReset}>Discard preview</button></div><div className="preview-stats"><span><strong>{String(preview.valid_rows)}</strong> ready</span><span><strong>{String(preview.rejected_rows)}</strong> rejected</span><span><strong>{String(preview.duplicate_rows)}</strong> duplicates</span></div>{Array.isArray(preview.errors) && preview.errors.length > 0 && <div className="validation-list">{(preview.errors as { row: number; message: string }[]).slice(0, 8).map((item, index) => <div key={`${item.row}-${index}`}><CircleAlert size={14} /> Row {item.row}: {item.message}</div>)}</div>}<div className="table-scroll"><table><thead><tr><th>Feedback text</th><th>Date</th><th>Rating</th><th>Product</th></tr></thead><tbody>{(preview.preview as Record<string, unknown>[]).map((row, index) => <tr key={index}><td>{String(row.text)}</td><td>{row.received_at ? String(row.received_at) : "—"}</td><td>{row.rating ? String(row.rating) : "—"}</td><td>{row.product ? String(row.product) : "—"}</td></tr>)}</tbody></table></div><button className="button primary" disabled={busy || Number(preview.valid_rows) === 0} onClick={onConfirm}>{busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Confirm import</button></section>}</>;
}

function FilterControls({ filters, updateFilter }: { filters: Filters; updateFilter: (key: keyof Filters, value: string) => void }) {
  return <div className="filter-controls" aria-label="Feedback filters">
    <label>From<input type="date" value={filters.start_date ?? ""} onChange={(event) => updateFilter("start_date", event.target.value)} /></label>
    <label>To<input type="date" value={filters.end_date ?? ""} onChange={(event) => updateFilter("end_date", event.target.value)} /></label>
    <label>Sentiment<select value={filters.sentiment ?? ""} onChange={(event) => updateFilter("sentiment", event.target.value)}><option value="">All</option><option value="negative">Negative</option><option value="neutral">Neutral</option><option value="positive">Positive</option></select></label>
    <label>Category<select value={filters.category ?? ""} onChange={(event) => updateFilter("category", event.target.value)}><option value="">All</option>{["pricing", "product quality", "delivery", "customer support", "usability", "billing", "other"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    <label>Severity<select value={filters.severity ?? ""} onChange={(event) => updateFilter("severity", event.target.value)}><option value="">All</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
    <label>Product<input value={filters.product ?? ""} onChange={(event) => updateFilter("product", event.target.value)} placeholder="Any product" /></label>
  </div>;
}

function CorrectionSelect({ label, value, predicted, options, onChange }: { label: string; value: string; predicted: string; options: string[]; onChange: (value: string) => void }) {
  return <div className="correction-select"><select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select>{value !== predicted && <small>Originally: {predicted}</small>}</div>;
}

function ImportHistoryTable({ batches }: { batches: ImportBatch[] }) {
  return <section className="panel imports-history">
    <div className="panel-heading"><div><h2>Import history</h2><p>Previous previews and confirmed imports</p></div></div>
    {batches.length ? <div className="table-scroll"><table><thead><tr><th>File</th><th>Status</th><th>Rows</th><th>Imported</th><th>Rejected</th><th>Duplicates</th><th>Created</th></tr></thead><tbody>{batches.map((batch) => <tr key={batch.id}><td>{batch.filename}</td><td><Badge value={batch.status === "complete" ? "positive" : "neutral"} /></td><td>{batch.total_rows}</td><td>{batch.imported_rows}</td><td>{batch.rejected_rows}</td><td>{batch.duplicate_rows}</td><td>{new Date(batch.created_at).toLocaleString()}</td></tr>)}</tbody></table></div> : <EmptyState title="No imports yet" detail="Your import history will appear here after a CSV preview." />}
  </section>;
}

function Badge({ value }: { value: string }) {
  return <span className={`badge ${value.toLowerCase().replaceAll(" ", "-")}`}>{value}</span>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><div className="empty-icon"><FileText size={19} /></div><strong>{title}</strong><span>{detail}</span></div>;
}

function Loading() {
  return <div className="loading-state"><LoaderCircle className="spin" size={19} /><span>Loading insights…</span></div>;
}
