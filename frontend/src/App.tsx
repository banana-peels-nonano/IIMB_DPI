import { createContext, useContext, useMemo, useState } from "react";
import { BrowserRouter, Link, NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { sampleAhead, sampleCards, sampleFacts, sampleHousehold } from "./demo/sample-contract";

type DemoState = {
  answers: Record<string, string>;
  purposes: Record<string, boolean>;
  setAnswer: (id: string, answer: string) => void;
  setPurpose: (id: string, on: boolean) => void;
  clear: () => void;
};
const DemoContext = createContext<DemoState | null>(null);
function useDemo() {
  const value = useContext(DemoContext);
  if (!value) throw new Error("Demo state unavailable");
  return value;
}

const sections = [
  { to: "/now", label: "NOW" }, { to: "/ahead", label: "AHEAD" },
  { to: "/household", label: "Our household" }, { to: "/what-we-know", label: "What we know" },
];

function Header() {
  return <header className="site-header"><nav className="ux4g-navbar" aria-label="Mirror">
    <div className="ux4g-navbar-wrap ux4g-container site-header__inner ux4g-gap-m">
      <Link className="brand-lockup ux4g-gap-s" to="/demo" aria-label="Mirror home"><span className="brand-copy"><span className="brand-name">Mirror</span><span className="brand-caption">Household financial clarity</span></span></Link>
      <ul className="ux4g-navbar-links desktop-navigation ux4g-gap-s" aria-label="Main sections">{sections.map((s) => <li key={s.to}><NavLink to={s.to} className={({ isActive }) => `navigation-link${isActive ? " is-active" : ""}`}>{s.label}</NavLink></li>)}</ul>
      <div className="ux4g-navbar-right"><span className="ux4g-tag-tonal-neutral ux4g-tag-s demo-pill">LOCAL DEMO</span></div>
    </div>
  </nav></header>;
}
function MobileNavigation() {
  return <nav className="ux4g-navbar ux4g-navbar-mobile mobile-navigation" aria-label="Main sections"><ul className="ux4g-navbar-links mobile-navigation__links">{sections.map((s) => <li key={s.to}><NavLink to={s.to} className={({ isActive }) => `mobile-navigation__link${isActive ? " is-active" : ""}`}>{s.label === "Our household" ? "Household" : s.label === "What we know" ? "Trust" : s.label}</NavLink></li>)}</ul></nav>;
}
function Disclosure() {
  return <div className="ux4g-alert ux4g-alert-info demo-disclosure" role="note"><span><strong>Local demo.</strong> Every household record is synthetic and illustrative. No bank is connected. Never enter personal, bank, Aadhaar, or OTP information.</span></div>;
}
function AppLayout() {
  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to main content</a><Header /><main id="main-content" className="ux4g-container app-main ux4g-grid ux4g-gap-xl"><Disclosure /><Outlet /></main><footer className="site-footer ux4g-container"><p className="ux4g-body-xs-default">Mirror helps you inspect patterns. Only you or the institution can confirm what happened. Mirror never moves money.</p></footer><MobileNavigation /></div>;
}
function PageHeading({ eyebrow, title, intro }: { eyebrow: string; title: string; intro: string }) {
  return <div className="page-heading ux4g-grid ux4g-gap-m"><p className="ux4g-label-m-strong ux4g-text-brand-primary-default">{eyebrow}</p><h1 className="ux4g-heading-xl-strong">{title}</h1><p className="ux4g-body-l-default">{intro}</p></div>;
}
function DemoPage() {
  return <section className="page-stack ux4g-grid ux4g-gap-xl" aria-labelledby="demo-title"><div className="intro-copy ux4g-grid ux4g-gap-m"><p className="ux4g-label-m-strong ux4g-text-brand-primary-default">A LOCAL WALK-THROUGH</p><h1 id="demo-title" className="ux4g-heading-xl-strong">See the patterns across your household accounts.</h1><p className="ux4g-body-l-default">Follow the customer journey from a clear consent choice to understanding, action, and control. This first phase uses only synthetic examples.</p><Link className="ux4g-btn ux4g-btn-primary ux4g-btn-md" to="/connect">Explore the local demo</Link></div><div className="ux4g-grid ux4g-gap-m journey-preview">{[["01 · Understand", "See recurring patterns", "Review commitments and credits in one household view."], ["02 · Identify", "Understand the evidence", "See what was observed, what a rule says, and what remains unknown."], ["03 · Act", "Choose your next step", "Contact the institution through its own channel. Mirror never moves money."]].map(([tag, title, text]) => <article className="ux4g-card ux4g-card-solid ux4g-card-vertical" key={tag}><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><span className="ux4g-tag-tonal-neutral ux4g-tag-s">{tag}</span><h2 className="ux4g-title-m-strong">{title}</h2><p className="ux4g-body-m-default">{text}</p></div></article>)}</div><p className="ux4g-body-s-default subdued-copy">Live Account Aggregator consent and connected data are later phases. No real login or consent occurs here.</p></section>;
}
function ConnectPage() {
  return <section className="page-stack ux4g-grid ux4g-gap-xl narrow-page"><PageHeading eyebrow="CONNECT · DEMO MODE" title="Start with a sample household" intro="A live experience begins with an Account Aggregator consent. This walk-through deliberately skips consent and uses synthetic records." /><article className="ux4g-card ux4g-card-solid ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-l-strong">What this demo includes</h2><ul className="plain-list ux4g-grid ux4g-gap-s"><li>A sample household and recurring account activity.</li><li>Evidence labels for observed, rule-based, inferred, and unknown details.</li><li>Answers and privacy choices held only in memory in this tab.</li></ul><div className="ux4g-alert ux4g-alert-warning" role="note"><span>Do not enter personal, bank, Aadhaar, or OTP information.</span></div><Link className="ux4g-btn ux4g-btn-primary ux4g-btn-md" to="/now">Continue to the sample</Link><Link className="ux4g-text-link-md" to="/demo">Back to introduction</Link></div></article></section>;
}
const evidenceLetters: Record<string, string> = { "Observed in sample": "O", "Published rule": "R", "Our reading": "I", "You tell us": "U" };
function EvidenceList({ items }: { items: { kind: string; text: string }[] }) {
  return <ul className="evidence-list ux4g-grid ux4g-gap-s">{items.map((item) => <li key={item.kind + item.text}><span className="ux4g-tag-tonal-neutral ux4g-tag-s">{evidenceLetters[item.kind] ?? "U"} · {item.kind}</span><p className="ux4g-body-s-default">{item.text}</p></li>)}</ul>;
}
function JourneyNav({ previous, next }: { previous?: [string, string]; next?: [string, string] }) {
  return <nav className="journey-nav" aria-label="Journey navigation">{previous ? <Link className="ux4g-btn ux4g-btn-outline-primary ux4g-btn-md" to={previous[0]}>← {previous[1]}</Link> : <span />}{next && <Link className="ux4g-btn ux4g-btn-primary ux4g-btn-md" to={next[0]}>{next[1]} →</Link>}</nav>;
}
function NowPage() {
  const { answers, setAnswer } = useDemo();
  return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="NOW · CHECK WHAT NEEDS YOU" title="A moment to look at" intro="A short list to help you decide what deserves attention. The content below is synthetic, not a live account finding." /><div className="ux4g-alert ux4g-alert-info" role="note"><span><strong>Since your last time (sample):</strong> No new events are connected to this demo. This is sample copy, not an account update.</span></div>{sampleCards.map((card) => <article className="ux4g-card ux4g-card-solid ux4g-card-vertical" key={card.id}><div className="ux4g-card-body page-stack ux4g-grid ux4g-gap-m"><span className="ux4g-tag-tonal-neutral ux4g-tag-s">SIMULATED · Illustrative sample</span><h2 className="ux4g-title-l-strong">{card.title}</h2><p className="ux4g-body-m-default">{card.summary}</p><details><summary className="ux4g-text-link-md">Why am I seeing this?</summary><EvidenceList items={card.evidence} /></details><p className="ux4g-label-m-strong">A possible next step</p><p className="ux4g-body-m-default">{card.action}. Mirror will not contact the institution or make a payment.</p><div className="answer-row"><span className="ux4g-body-s-default">Did you already resolve this? (demo answer)</span>{["Yes", "Not yet", "Not sure"].map((a) => <button key={a} className={`ux4g-btn ${answers[card.id] === a ? "ux4g-btn-primary" : "ux4g-btn-outline-primary"} ux4g-btn-md`} aria-pressed={answers[card.id] === a} onClick={() => setAnswer(card.id, a)}>{a}</button>)}</div></div></article>)}<JourneyNav next={["/ahead", "Look ahead"]} /></section>;
}
function AheadPage() {
  return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="AHEAD · LOOKING FORWARD" title="What may be coming up" intro="These conditional examples are included to show how a forward-looking view explains its assumptions. Confirm dates with the institution." /><div className="ux4g-alert ux4g-alert-warning" role="note"><span>Dates and events below are illustrative. They are not a reminder or deadline for your household.</span></div>{sampleAhead.map((item) => <article className="ux4g-card ux4g-card-solid ux4g-card-vertical" key={item.id}><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><span className="ux4g-tag-tonal-neutral ux4g-tag-s">SIMULATED · Conditional sample</span><h2 className="ux4g-title-l-strong">{item.title}</h2><p className="ux4g-body-m-default">{item.text}</p><EvidenceList items={[{ kind: "Observed in sample", text: "Illustrative pattern supplied in the local sample." }, { kind: "You tell us", text: "The actual date and any action must be confirmed with you and the institution." }]} /></div></article>)}<JourneyNav previous={["/now", "NOW"]} next={["/household", "Our household"]} /></section>;
}
function HouseholdPage() {
  const groups = [["Recurring commitments", sampleHousehold.commitments], ["Regular credits", sampleHousehold.credits], ["Protection checks", [sampleHousehold.protections]], ["Pay-cycle context", [sampleHousehold.payCycle]]] as const;
  return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="OUR HOUSEHOLD · RECURRING FLOWS" title="The patterns in this household" intro="A household view can bring recurring flows together, while keeping observations separate from assumptions." /><div className="ux4g-grid ux4g-gap-m household-grid">{groups.map(([title, rows]) => <article className="ux4g-card ux4g-card-solid ux4g-card-vertical" key={title}><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-m-strong">{title}</h2><ul className="ux4g-grid ux4g-gap-s">{rows.map((row) => <li key={row} className="ux4g-body-m-default">{row}</li>)}</ul></div></article>)}</div><div className="ux4g-alert ux4g-alert-info" role="note"><span>No balances, eligibility, or confirmed income are presented in this demo.</span></div><JourneyNav previous={["/ahead", "AHEAD"]} next={["/what-we-know", "What we know"]} /></section>;
}
function TrustPage() {
  const { answers, purposes, setAnswer, setPurpose, clear } = useDemo();
  const [cleared, setCleared] = useState(false);
  const answerEntries = useMemo(() => Object.entries(answers), [answers]);
  return <section className="page-stack ux4g-grid ux4g-gap-xl"><PageHeading eyebrow="WHAT WE KNOW · YOUR CHOICES" title="Facts, purposes, and access" intro="See what you told us, which demo purposes are on, and what access has happened. These controls do not change the backend." /><article className="ux4g-card ux4g-card-solid ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-l-strong">Questions for you</h2><p className="ux4g-body-s-default">Your selection appears as “You told us”; it does not become observed bank data.</p>{sampleFacts.map((fact) => <fieldset className="fact-group ux4g-grid ux4g-gap-s" key={fact.id}><legend className="ux4g-title-s-strong">{fact.label}</legend><div className="answer-row">{fact.choices.map((answer) => <button className={`ux4g-btn ${answers[fact.id] === answer ? "ux4g-btn-primary" : "ux4g-btn-outline-primary"} ux4g-btn-md`} key={answer} aria-pressed={answers[fact.id] === answer} onClick={() => setAnswer(fact.id, answer)}>{answer}</button>)}</div>{answers[fact.id] && <span className="ux4g-tag-tonal-neutral ux4g-tag-s">You told us: {answers[fact.id]}</span>}</fieldset>)}</div></article><article className="ux4g-card ux4g-card-solid ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-l-strong">Demo purposes</h2><p className="ux4g-body-s-default">Switching a purpose changes only this tab's sample view. No data is shared.</p>{[["patterns", "Understand recurring patterns"], ["protections", "Explore government protection questions"]].map(([id, label]) => <label className="purpose-row" key={id}><span className="ux4g-body-m-default">{label}</span><input type="checkbox" checked={purposes[id] ?? true} onChange={(event) => setPurpose(id, event.target.checked)} /><span className="ux4g-label-m-strong">{(purposes[id] ?? true) ? "On" : "Off"}</span></label>)}</div></article><article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-l-strong">Access history</h2><p className="ux4g-body-m-default">No external lookup has been made in this local demo.</p><p className="ux4g-body-s-default">Demo activity held in memory: {answerEntries.length} answer(s). No access is recorded by the backend.</p></div></article><article className="ux4g-card ux4g-card-outline ux4g-card-vertical"><div className="ux4g-card-body ux4g-grid ux4g-gap-m"><h2 className="ux4g-title-l-strong">Stop &amp; Forget this demo session</h2><p className="ux4g-body-m-default">Clear the answers and purpose switches in this tab. The synthetic fixture remains in the app and will return if you refresh.</p><button className="ux4g-btn ux4g-btn-danger ux4g-btn-md" onClick={() => { clear(); setCleared(true); }}>Clear demo choices</button>{cleared && <p className="ux4g-body-s-default" role="status">Demo choices cleared from this tab. Sample records remain illustrative.</p>}</div></article><JourneyNav previous={["/household", "Our household"]} /></section>;
}
function App() {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [purposes, setPurposes] = useState<Record<string, boolean>>({ patterns: true, protections: true });
  const state: DemoState = { answers, purposes, setAnswer: (id, answer) => setAnswers((a) => ({ ...a, [id]: answer })), setPurpose: (id, on) => setPurposes((p) => ({ ...p, [id]: on })), clear: () => { setAnswers({}); setPurposes({ patterns: true, protections: true }); } };
  return <DemoContext.Provider value={state}><BrowserRouter><Routes><Route element={<AppLayout />}><Route path="/" element={<Navigate to="/demo" replace />} /><Route path="/demo" element={<DemoPage />} /><Route path="/connect" element={<ConnectPage />} /><Route path="/now" element={<NowPage />} /><Route path="/ahead" element={<AheadPage />} /><Route path="/household" element={<HouseholdPage />} /><Route path="/what-we-know" element={<TrustPage />} /><Route path="*" element={<Navigate to="/demo" replace />} /></Route></Routes></BrowserRouter></DemoContext.Provider>;
}
export default App;
