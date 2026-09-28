import { createContext, useContext, useEffect, useState } from "react";
import { BrowserRouter, Link, NavLink, Navigate, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { checkBackendHealth, type BackendHealth } from "./api/health";
import { mirrorApi, type JsonObject, type LocalSession, type MirrorAppContract } from "./api/data-source";

type Workspace = {
  contract: MirrorAppContract | null;
  session: LocalSession | null;
  busy: boolean;
  theme: "light" | "dark";
  error: string;
  message: string;
  load: () => Promise<void>;
  answer: (cardId: string, optionId: string) => Promise<void>;
  correct: (factId: string, value: string) => Promise<void>;
  setPurpose: (purposeId: string, enabled: boolean) => Promise<void>;
  setTheme: (theme: "light" | "dark") => void;
  forget: () => Promise<void>;
  clearMessage: () => void;
};
const WorkspaceContext = createContext<Workspace | null>(null);
function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("Mirror workspace is unavailable");
  return value;
}

const sections = [
  { to: "/now", label: "NOW" }, { to: "/ahead", label: "AHEAD" },
  { to: "/household", label: "Our household" }, { to: "/what-we-know", label: "What we know" },
];
const govPurpose = "GOV_PROTECT";

function obj(value: unknown): JsonObject { return typeof value === "object" && value !== null && !Array.isArray(value) ? value as JsonObject : {}; }
function rows(value: unknown): JsonObject[] { return Array.isArray(value) ? value.filter((item): item is JsonObject => typeof item === "object" && item !== null && !Array.isArray(item)) : []; }
function list(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function str(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }
function amount(value: unknown): string { return typeof value === "number" ? `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : ""; }

function Header() {
  return <header className="site-header"><nav className="ux4g-navbar" aria-label="Mirror">
    <div className="ux4g-navbar-wrap ux4g-container site-header__inner ux4g-gap-m">
      <Link className="brand-lockup ux4g-gap-s" to="/demo" aria-label="Mirror home"><span className="brand-copy"><span className="brand-name">Mirror</span><span className="brand-caption">Household financial clarity</span></span></Link>
      <ul className="ux4g-navbar-links desktop-navigation ux4g-gap-s" aria-label="Main sections">{sections.map((item) => <li key={item.to}><NavLink to={item.to} className={({ isActive }) => `navigation-link${isActive ? " is-active" : ""}`}>{item.label}</NavLink></li>)}</ul>
      <div className="ux4g-navbar-right"><span className="ux4g-tag-tonal-neutral ux4g-tag-s demo-pill">LOCAL ENGINE DEMO</span></div>
    </div>
  </nav></header>;
}
function MobileNavigation() {
  return <nav className="ux4g-navbar ux4g-navbar-mobile mobile-navigation" aria-label="Main sections"><ul className="ux4g-navbar-links mobile-navigation__links">{sections.map((item) => <li key={item.to}><NavLink to={item.to} className={({ isActive }) => `mobile-navigation__link${isActive ? " is-active" : ""}`}>{item.label === "Our household" ? "Household" : item.label === "What we know" ? "Trust" : item.label}</NavLink></li>)}</ul></nav>;
}
function Disclosure() {
  return <div className="ux4g-alert ux4g-alert-info demo-disclosure" role="note"><span className="ux4g-text-neutral-primary"><strong>Local synthetic replay.</strong> The backend Mirror engine runs on generated sample account records. No bank or AA is connected, and no real household data is used.</span></div>;
}
function BackendStatus() {
  const [status, setStatus] = useState<BackendHealth>("checking");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 3500);
    checkBackendHealth(controller.signal).then((available) => setStatus(available ? "available" : "unavailable"))
      .catch(() => setStatus("unavailable")).finally(() => window.clearTimeout(timeout));
    return () => { controller.abort(); window.clearTimeout(timeout); };
  }, [refresh]);
  const label = status === "checking" ? "Checking local service…" : status === "available" ? "Mirror backend available" : "Mirror backend unavailable";
  return <div className="backend-status" aria-live="polite"><span className="ux4g-body-s-default">{label}. This does not mean a bank is connected.</span><button type="button" className="ux4g-btn ux4g-btn-outline-primary ux4g-btn-md" onClick={() => { setStatus("checking"); setRefresh((n) => n + 1); }}>Check again</button></div>;
}
function WorkspaceNotices() {
  const { error, message, clearMessage } = useWorkspace();
  return <>{error && <div className="ux4g-alert ux4g-alert-warning" role="alert"><span className="ux4g-text-neutral-primary">{error}</span></div>}{message && <div className="ux4g-alert ux4g-alert-info" role="status"><span className="ux4g-text-neutral-primary">{message}</span><button className="ux4g-btn ux4g-btn-outline-primary ux4g-btn-md" onClick={clearMessage}>Dismiss</button></div>}</>;
}
function AppLayout() {
  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to main content</a><Header /><main id="main-content" className="ux4g-container app-main ux4g-grid ux4g-gap-xl"><Disclosure /><BackendStatus /><WorkspaceNotices /><Outlet /></main><footer className="site-footer ux4g-container"><p className="ux4g-body-xs-default">Mirror helps you inspect patterns. Only you or the institution can confirm what happened. Mirror never moves money.</p></footer><MobileNavigation /></div>;
}
function PageHeading({ eyebrow, title, intro }: { eyebrow: string; title: string; intro: string }) {
  return <div className="page-heading ux4g-grid ux4g-gap-m"><p className="ux4g-label-m-strong ux4g-text-brand-primary-default">{eyebrow}</p><h1 className="ux4g-heading-xl-strong">{title}</h1><p className="ux4g-body-l-default">{intro}</p></div>;
}
function JourneyNav({ previous, next }: { previous?: [string, string]; next?: [string, string] }) {
  return <nav className="journey-nav" aria-label="Journey navigation">{previous ? <Link className="ux4g-btn ux4g-btn-outline-primary ux4g-btn-md" to={previous[0]}>← {previous[1]}</Link> : <span />}{next && <Link className="ux4g-btn ux4g-btn-primary ux4g-btn-md" to={next[0]}>{next[1]} →</Link>}</nav>;
}
function EvidenceList({ items }: { items: JsonObject[] }) {
  return <ul className="evidence-list ux4g-grid ux4g-gap-s">{items.map((item, index) => <li key={`${str(item.code)}-${index}`}><span className="ux4g-tag-tonal-neutral ux4g-tag-s">{str(item.class)} · {str(item.badge, "Evidence")}</span><p className="ux4g-body-s-default">{str(item.detail)}</p>{Boolean(item.citation) && <p className="ux4g-body-xs-default">{str(item.citation)}{Boolean(item.source) ? <> · <a href={str(item.source)} target="_blank" rel="noreferrer">Source</a></> : null}</p>}</li>)}</ul>;
}
function LoadingState() {
  return <div className="ux4g-card ux4g-card-outline ux4g-card-vertical" role="status" aria-live="polite"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">Loading the Mirror contract</h2><p className="ux4g-body-m-default">The local engine is preparing its validated view.</p></div></div>;
}
function ContractState() {
  const { busy, load } = useWorkspace();
  if (busy) return <LoadingState />;
  return <div className="ux4g-card ux4g-card-outline ux4g-card-vertical" role="status"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">Mirror view unavailable</h2><p className="ux4g-body-m-default">Check the service message above, then retry the local contract request.</p><button className="ux4g-btn ux4g-btn-outline-primary ux4g-btn-md" onClick={() => void load()}>Try again</button></div></div>;
}
function EmptyState({ title, text }: { title: string; text: string }) {
  return <div className="ux4g-alert ux4g-alert-info" role="status"><span className="ux4g-text-neutral-primary"><strong>{title}</strong> {text}</span></div>;
}
function DemoPage() {
  return <section className="page-stack ux4g-grid ux4g-gap-xl" aria-labelledby="demo-title"><div className="intro-copy ux4g-grid ux4g-gap-m"><p className="ux4g-label-m-strong ux4g-text-brand-primary-default">A LOCAL ENGINE WALK-THROUGH</p><h1 id="demo-title" className="ux4g-heading-xl-strong">See the patterns across a household.</h1><p className="ux4g-body-l-default">This version runs the existing Mirror rules and contract against a synthetic AA-shaped dataset. Answers and privacy choices are validated and saved by the local backend.</p><Link className="ux4g-btn ux4g-btn-primary ux4g-btn-md" to="/connect">Open the local demo</Link></div><div className="ux4g-grid ux4g-gap-m journey-preview">{[["01 · Understand", "Review the evidence", "Open the backend generated NOW view and inspect why each item appears."], ["02 · Identify", "Look ahead", "Review conditional dates and household patterns from the engine contract."], ["03 · Act", "Keep control", "Submit bounded answers, change a purpose, correct a fact, and remove saved demo state."]].map(([tag, title, text]) => <article className="ux4g-card ux4g-card-solid ux4g-card-vertical" key={tag}><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><span className="ux4g-tag-tonal-neutral ux4g-tag-s">{tag}</span><h2 className="ux4g-title-m-strong">{title}</h2><p className="ux4g-body-m-default">{text}</p></div></article>)}</div><p className="ux4g-body-s-default subdued-copy">Live AA consent and customer authentication are not active in this local phase.</p></section>;
}
function ConnectPage() {
  const workspace = useWorkspace();
  const navigate = useNavigate();
  return <section className="page-stack ux4g-grid ux4g-gap-xl narrow-page"><PageHeading eyebrow="LOCAL WORKSPACE · NO BANK CONNECTION" title="Start the synthetic household replay" intro="This local journey has no login. The app uses a generated sample corpus, not your bank data, and it does not claim AA consent." /><article className="ux4g-card ux4g-card-solid ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-l-strong">What will happen</h2><ul className="plain-list ux4g-grid ux4g-gap-s"><li>The backend loads synthetic account activity into the existing Mirror engine.</li><li>Answers and the government-protection purpose switch are validated by the engine and saved outside this repository.</li><li>Stop &amp; Forget removes the local saved answers, corrections, and access history.</li></ul><p className="ux4g-body-s-default">This local mode has no authentication and is intended for a single-machine demo with synthetic data only.</p><button className="ux4g-btn ux4g-btn-primary ux4g-btn-md" disabled={workspace.busy} onClick={() => void workspace.load().then(() => navigate("/now"))}>{workspace.busy ? "Preparing…" : "Open the Mirror view"}</button><Link className="ux4g-text-link-md" to="/demo">Back to introduction</Link></div></article></section>;
}
function CardView({ card }: { card: JsonObject }) {
  const { answer, busy } = useWorkspace();
  const question = obj(card.question);
  const options = rows(question.options);
  const body = list(card.body).filter((line): line is string => typeof line === "string");
  const why = rows(card.why);
  const deadline = obj(card.deadline);
  return <article className="ux4g-card ux4g-card-solid ux4g-card-vertical"><div className="ux4g-card-body page-stack ux4g-grid ux4g-gap-m"><div className="answer-row"><span className="ux4g-tag-tonal-neutral ux4g-tag-s">{str(card.type)} · {str(card.status)}</span>{card.simulated === true && <span className="ux4g-tag-tonal-neutral ux4g-tag-s">SIMULATED</span>}</div><h2 className="ux4g-title-l-strong">{str(card.title)}</h2>{body.map((line, index) => <p className="ux4g-body-m-default" key={index}>{line}</p>)}{Boolean(deadline.date) && <p className="ux4g-body-m-default"><strong>Conditional date:</strong> {str(deadline.date)}{Boolean(deadline.depends_on_text) ? ` · ${list(deadline.depends_on_text).join("; ")}` : ""}</p>}{Boolean(card.action) && <p className="ux4g-body-m-default"><strong>Possible next step:</strong> {str(obj(card.action).action_text)}</p>}{why.length > 0 && <details><summary className="ux4g-text-link-md">Why am I seeing this?</summary><EvidenceList items={why} /></details>}{options.length > 0 && <fieldset className="fact-group ux4g-grid ux4g-gap-s"><legend className="ux4g-title-s-strong">{str(question.question)}</legend><div className="answer-row">{options.map((option) => <button key={str(option.id)} type="button" disabled={busy} className="ux4g-btn ux4g-btn-outline-primary ux4g-btn-md" onClick={() => void answer(str(card.id), str(option.id))}>{str(option.label)}</button>)}</div></fieldset>}</div></article>;
}
function NowPage() {
  const { contract } = useWorkspace();
  if (!contract) return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="NOW · CHECK WHAT NEEDS YOU" title="A moment to look at" intro="Items from the validated Mirror engine contract." /><ContractState /></section>;
  const now = obj(contract.now);
  const briefing = obj(now.since_last_time);
  const cards = rows(now.cards);
  const lines = rows(briefing.lines);
  const resolved = rows(now.resolved);
  return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="NOW · CHECK WHAT NEEDS YOU" title="A moment to look at" intro={`Engine contract for ${str(contract.generated.as_of)}. Cards and explanations are produced by Mirror, not the browser.`} />{lines.length ? <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">Since the previous view</h2>{lines.map((line, index) => <p className="ux4g-body-m-default" key={str(line.id, String(index))}>{str(line.text)}</p>)}</div></article> : <EmptyState title="No new events." text="The engine has no new changes to report since the previous view." />}{cards.length ? cards.map((card) => <CardView key={str(card.id)} card={card} />) : <EmptyState title="Nothing needs a response right now." text="There are no open cards in the current engine contract." />}{resolved.length > 0 && <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">Resolved</h2>{resolved.map((item) => <div key={str(item.card_id)}><h3 className="ux4g-title-s-strong">{str(item.title)}</h3><p className="ux4g-body-m-default">{str(item.text)}</p><span className="ux4g-tag-tonal-neutral ux4g-tag-s">{str(item.basis_label)}</span></div>)}</div></article>}<JourneyNav next={["/ahead", "Look ahead"]} /></section>;
}
function AheadPage() {
  const { contract } = useWorkspace();
  if (!contract) return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="AHEAD · LOOKING FORWARD" title="What may be coming up" intro="Conditional projections from the Mirror engine contract." /><ContractState /></section>;
  const ahead = obj(contract.ahead);
  const items = rows(ahead.items);
  const pressure = rows(ahead.pressure_points);
  return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="AHEAD · LOOKING FORWARD" title="What may be coming up" intro="Conditional projections from the validated Mirror engine contract. Confirm any dates with the relevant institution." />{items.map((item, index) => <article className="ux4g-card ux4g-card-solid ux4g-card-vertical" key={str(item.id, String(index))}><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><span className="ux4g-tag-tonal-neutral ux4g-tag-s">{str(item.evidence_class)} · {str(item.kind)}</span><h2 className="ux4g-title-l-strong">{str(item.text, str(item.label))}</h2>{Boolean(item.conditional_on) && <p className="ux4g-body-s-default">Depends on: {list(item.conditional_on).join(", ")}</p>}</div></article>)}{pressure.map((item, index) => <article className="ux4g-card ux4g-card-outline ux4g-card-vertical" key={str(item.id, `pressure-${index}`)}><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><span className="ux4g-tag-tonal-neutral ux4g-tag-s">Conditional pressure point</span><p className="ux4g-body-m-default">{str(item.text)}</p></div></article>)}{!items.length && !pressure.length && <EmptyState title="No upcoming items." text="The engine has no conditional items for the current household view." />}<JourneyNav previous={["/now", "NOW"]} next={["/household", "Our household"]} /></section>;
}
function DataRows({ items, title }: { items: JsonObject[]; title: string }) {
  return <article className="ux4g-card ux4g-card-solid ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">{title}</h2>{items.length ? <ul className="data-list ux4g-grid ux4g-gap-m">{items.map((item, index) => <li key={str(item.id, str(item.member_key, `${str(item.member, str(item.display_name))}-${index}`))}><strong>{[str(item.member, str(item.display_name)), str(item.label, str(item.what))].filter(Boolean).join(" · ")}</strong><span className="ux4g-body-s-default">{[str(item.cadence), str(item.status), str(item.status_text), str(item.not_used_reason), str(item.evidence_class ? `Evidence ${item.evidence_class}` : ""), item.last_amount !== undefined ? amount(item.last_amount) : "", item.last_seen ? `Last seen ${str(item.last_seen)}` : ""].filter(Boolean).join(" · ")}</span>{list(item.notes).map((note, i) => <span className="ux4g-body-xs-default" key={i}>{str(note)}</span>)}{rows(item.schemes).map((scheme) => <span className="ux4g-body-s-default" key={str(scheme.scheme)}>{str(scheme.label)} · {str(scheme.status_text)} · Evidence {str(scheme.evidence_class)}</span>)}</li>)}</ul> : <p className="ux4g-body-s-default">No items are present in this section of the current contract.</p>}</div></article>;
}
function HouseholdPage() {
  const { contract, setPurpose, busy } = useWorkspace();
  if (!contract) return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="OUR HOUSEHOLD · RECURRING FLOWS" title="The patterns in this household" intro="Engine-derived household details." /><ContractState /></section>;
  const house = obj(contract.our_household);
  const protections = obj(house.protections);
  const members = rows(house.members);
  const payCycle = rows(obj(house.visual_data).pay_cycle);
  const purposeOn = protections.switched_on === true;
  return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="OUR HOUSEHOLD · RECURRING FLOWS" title="The patterns in this household" intro="Recurring flows, credits, and observations produced by the Mirror engine." />{members.length > 0 && <DataRows title="Connected account members" items={members} />}{rows(house.commitments).length > 0 && <DataRows title="Recurring commitments" items={rows(house.commitments)} />}<DataRows title="Regular credits" items={rows(house.regular_credits)} /><DataRows title="Observed protections" items={rows(house.protections_observed)} /><DataRows title="Charges observed" items={rows(house.charges)} />{protections.switched_on === true && rows(protections.members).length > 0 && <DataRows title="Government protection checks" items={rows(protections.members)} />}{!purposeOn && <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">Government protection checks are off</h2><p className="ux4g-body-m-default">The engine hides scheme checks while this purpose is off.</p><button className="ux4g-btn ux4g-btn-primary ux4g-btn-md" disabled={busy} onClick={() => void setPurpose(govPurpose, true)}>Turn on this purpose</button></div></article>}{payCycle.length > 0 && <PayCycle rows={payCycle} notes={list(obj(house.visual_data).pay_cycle_notes)} />}<JourneyNav previous={["/ahead", "AHEAD"]} next={["/what-we-know", "What we know"]} /></section>;
}
function PayCycle({ rows: items, notes }: { rows: JsonObject[]; notes: unknown[] }) {
  return <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">Pay-cycle context</h2><div className="table-scroll"><table className="ux4g-table ux4g-table-m ux4g-table-column-dividers"><thead><tr><th scope="col">Member</th><th scope="col">Month</th><th scope="col">Money in</th><th scope="col">Collections expected</th><th scope="col">Collections made</th></tr></thead><tbody>{items.map((row, index) => <tr key={`${str(row.account)}-${str(row.month)}-${index}`}><th scope="row">{str(row.member)}</th><td>{str(row.month)}</td><td>{amount(row.money_in)}</td><td>{amount(row.collections_expected)}</td><td>{amount(row.collections_made)}</td></tr>)}</tbody></table></div>{notes.map((note, index) => <p className="ux4g-body-xs-default" key={index}>{str(note)}</p>)}</div></article>;
}
function FactCorrection({ fact }: { fact: JsonObject }) {
  const { correct, busy } = useWorkspace();
  const options = rows(fact.options);
  const [value, setValue] = useState(str(fact.value));
  useEffect(() => setValue(str(fact.value)), [fact.value]);
  return <fieldset className="fact-group ux4g-grid ux4g-gap-s"><legend className="ux4g-title-s-strong">{str(fact.member)} · {str(fact.fact)} <span className="ux4g-tag-tonal-neutral ux4g-tag-s">U · You told us</span></legend><p className="ux4g-body-s-default">Current answer: {str(fact.answer)}</p><label className="ux4g-label-m-strong" htmlFor={`fact-${str(fact.id)}`}>Correct this answer</label><select id={`fact-${str(fact.id)}`} className="ux4g-select ux4g-form-select" value={value} onChange={(event) => setValue(event.target.value)}>{options.map((option) => <option value={str(option.id)} key={str(option.id)}>{str(option.label)}</option>)}</select><button className="ux4g-btn ux4g-btn-outline-primary ux4g-btn-md" disabled={busy || value === str(fact.value)} onClick={() => void correct(str(fact.id), value)}>Save correction</button><p className="ux4g-body-xs-default">{str(fact.why)}</p></fieldset>;
}
function TrustPage() {
  const { contract, session, setPurpose, setTheme, theme, forget, busy } = useWorkspace();
  const [cleared, setCleared] = useState(false);
  if (!contract) return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="WHAT WE KNOW · YOUR CHOICES" title="Facts, purposes, and access" intro="Review answers held by the local Mirror engine." /><ContractState /></section>;
  const known = obj(contract.what_we_know);
  const purposes = rows(known.purposes);
  const facts = rows(known.household_facts);
  const answers = rows(known.facts);
  const corrections = rows(known.corrections);
  const access = rows(known.access_log);
  const integrations = rows(known.dpi_integrations);
  const gov = purposes.find((item) => item.purpose === govPurpose);
  return <section className="page-stack ux4g-grid ux4g-gap-xl">
    <PageHeading eyebrow="WHAT WE KNOW · YOUR CHOICES" title="Facts, purposes, and access" intro="Choices in this page are saved by the local Mirror store. They apply only to the synthetic replay." />
    <article className="ux4g-card ux4g-card-solid ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m">
      <h2 className="ux4g-title-l-strong">Your household answers</h2><p className="ux4g-body-s-default">Answers remain class U: a statement you gave, never an observed bank fact.</p>
      {facts.length ? facts.map((fact) => <FactCorrection key={str(fact.id)} fact={fact} />) : <EmptyState title="No household answers saved." text="The Mirror engine will ask a bounded question only when an open item needs it." />}
    </div></article>
    {answers.length > 0 && <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m">
      <h2 className="ux4g-title-m-strong">Answers to Mirror questions</h2>
      {answers.map((item) => <p className="ux4g-body-m-default" key={str(item.id)}>{str(item.question)} · {str(item.answer)} · {str(item.stated_on)}</p>)}
    </div></article>}
    <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m">
      <h2 className="ux4g-title-m-strong">Correction history</h2>
      {corrections.length ? corrections.map((item, index) => <p className="ux4g-body-m-default" key={`${str(item.fact_id)}-${index}`}>{str(item.member)} · {str(item.fact)}: {str(item.before)} → {str(item.after)} · {str(item.stated_on)}</p>) : <p className="ux4g-body-s-default">No corrections have been recorded.</p>}
    </div></article>
    <article className="ux4g-card ux4g-card-solid ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m">
      <h2 className="ux4g-title-l-strong">Purpose choices</h2>
      {gov && <label className="purpose-row ux4g-switch ux4g-switch-md"><input type="checkbox" className="ux4g-switch-input" role="switch" aria-label={str(gov.label)} checked={gov.on === true} disabled={busy} onChange={(event) => void setPurpose(govPurpose, event.target.checked)} /><span className="ux4g-switch-control" aria-hidden="true"><span className="ux4g-switch-track purpose-switch-track"><span className="ux4g-switch-thumb" /></span></span><span className="ux4g-switch-content purpose-switch-content ux4g-body-m-default">{str(gov.label)}</span><span className="ux4g-label-m-strong purpose-switch-status">{gov.on ? "On" : "Off"}</span></label>}
      <p className="ux4g-body-s-default">{gov ? str(gov.granted_through) : "This purpose is not in the current contract."} Turning it off removes the answers and derived items that purpose used.</p>
      <div className="purpose-explanations ux4g-grid ux4g-gap-m">{purposes.filter((item) => item.purpose !== govPurpose).map((item) => <div key={str(item.purpose)}><h3 className="ux4g-title-s-strong">{str(item.label)}</h3><p className="ux4g-body-s-default">{str(item.granted_through)}. This local demo does not initiate or revoke this consent.</p></div>)}</div>
    </div></article>
    <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">Display theme</h2><p className="ux4g-body-s-default">UX4G Light is the default. Change the display theme for this browser.</p><button className="ux4g-btn ux4g-btn-outline-primary ux4g-btn-md" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>Switch to {theme === "light" ? "Dark" : "Light"} theme</button></div></article>
    <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-l-strong">Access history</h2>{access.length ? <ul className="ux4g-grid ux4g-gap-s">{access.map((item, index) => <li className="ux4g-body-m-default" key={str(item.id, String(index))}>{str(item.what)} · {str(item.outcome, str(item.purpose))} · {str(item.on)}</li>)}</ul> : <p className="ux4g-body-m-default">No external lookup has happened in this local synthetic replay.</p>}<p className="ux4g-body-s-default">Session mode: {str(session?.mode, "local-demo")} · AA connected: {session?.aa_connected ? "Yes" : "No"}</p></div></article>
    <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">External data sources</h2>{integrations.map((integration) => <div key={str(integration.name)}><h3 className="ux4g-title-s-strong">{str(integration.name)}</h3><p className="ux4g-body-s-default">{str(obj(integration.live_lookup_for_this_household).status, "not performed")}: {str(obj(integration.live_lookup_for_this_household).reason, "No live lookup is part of this local demo.")}</p></div>)}</div></article>
    <article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-l-strong">Stop &amp; Forget local demo state</h2><p className="ux4g-body-m-default">Remove saved answers, corrections, purpose history, and access history from this machine. The generated synthetic source remains available for a later replay.</p><button className="ux4g-btn ux4g-btn-outline-neutral ux4g-btn-md" disabled={busy} onClick={() => { if (window.confirm("Remove all saved local demo answers and history?")) void forget().then(() => setCleared(true)); }}>{busy ? "Removing…" : "Stop & Forget"}</button>{cleared && <p className="ux4g-body-s-default" role="status">Saved local demo state was removed. Open the local demo to start again.</p>}</div></article>
    <JourneyNav previous={["/household", "Our household"]} />
  </section>;
}
function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [contract, setContract] = useState<MirrorAppContract | null>(null);
  const [session, setSession] = useState<LocalSession | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => window.localStorage.getItem("mirror-theme") === "dark" ? "dark" : "light");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => { document.documentElement.dataset.theme = theme; window.localStorage.setItem("mirror-theme", theme); }, [theme]);
  const load = async () => {
    setBusy(true); setError("");
    try { const [nextSession, nextContract] = await Promise.all([mirrorApi.getSession(), mirrorApi.getContract()]); setSession(nextSession); setContract(nextContract); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load the Mirror contract."); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  const update = async (operation: () => Promise<MirrorAppContract>) => {
    setBusy(true); setError(""); setMessage("");
    try { setContract(await operation()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "The action could not be completed."); }
    finally { setBusy(false); }
  };
  const forget = async () => {
    setBusy(true); setError(""); setMessage("");
    try { const receipt = await mirrorApi.forgetSession(); setContract(null); setMessage(receipt.message); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not remove local state."); }
    finally { setBusy(false); }
  };
  const value: Workspace = { contract, session, busy, theme, error, message, load, setTheme,
    answer: (cardId, optionId) => update(() => mirrorApi.submitAnswer({ cardId, optionId })),
    correct: (factId, nextValue) => update(() => mirrorApi.correctFact({ factId, value: nextValue })),
    setPurpose: (purposeId, enabled) => update(() => mirrorApi.setPurpose({ purposeId, enabled })),
    forget, clearMessage: () => setMessage("") };
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
function RoutesView() {
  return <BrowserRouter><Routes><Route element={<AppLayout />}><Route path="/" element={<Navigate to="/demo" replace />} /><Route path="/demo" element={<DemoPage />} /><Route path="/connect" element={<ConnectPage />} /><Route path="/now" element={<NowPage />} /><Route path="/ahead" element={<AheadPage />} /><Route path="/household" element={<HouseholdPage />} /><Route path="/what-we-know" element={<TrustPage />} /><Route path="*" element={<Navigate to="/demo" replace />} /></Route></Routes></BrowserRouter>;
}
function App() {
  return <WorkspaceProvider><RoutesView /></WorkspaceProvider>;
}
export default App;
