/** Synthetic, pre-authored fixture for the local UX walk-through. */
export type EvidenceKind = "Observed in sample" | "Published rule" | "Our reading" | "You tell us";

export interface EvidenceItem {
  kind: EvidenceKind;
  text: string;
}

export interface DemoCard {
  id: string;
  title: string;
  summary: string;
  evidence: EvidenceItem[];
  action: string;
}

export const sampleCards: DemoCard[] = [
  {
    id: "returned-collection",
    title: "A loan collection was returned (SIMULATED sample)",
    summary: "In this illustrative sample, a lender collection did not go through. Check with the lender for today's amount and how it applies payments.",
    evidence: [
      { kind: "Observed in sample", text: "A returned collection appears in the illustrative account activity." },
      { kind: "Published rule", text: "Payment allocation depends on the lender's terms." },
      { kind: "Our reading", text: "A returned item may need follow-up; this does not establish an outstanding amount." },
      { kind: "You tell us", text: "Only you and the lender can confirm whether it was paid or arranged another way." },
    ],
    action: "Ask the lender for today's overdue amount and how payments are applied",
  },
  {
    id: "regular-credit",
    title: "A regular credit pattern (SIMULATED sample)",
    summary: "A repeating credit appears in the sample. Mirror does not label it as income or assume it will arrive next time.",
    evidence: [
      { kind: "Observed in sample", text: "The sample account shows credits on a repeating pattern." },
      { kind: "Our reading", text: "This pattern can help frame timing, but it does not confirm the source or next payment." },
    ],
    action: "Review the household timeline",
  },
];

export const sampleAhead = [
  { id: "premium-window", title: "A premium may be due soon (SIMULATED sample)", text: "If the premium was due on the date in the sample, a grace period may end around the illustrative date shown. Check your policy and insurer for the actual due date." },
  { id: "regular-collection", title: "A collection usually happens around this time (SIMULATED sample)", text: "The sample shows a repeating collection pattern. Timing can change; confirm with the institution." },
];

export const sampleHousehold = {
  commitments: ["A recurring loan collection pattern (SIMULATED sample)", "A recurring insurance premium pattern (SIMULATED sample)"],
  credits: ["A regular credit pattern in the sample (SIMULATED; source not confirmed)"],
  protections: "No real scheme or insurance eligibility is assessed in this local sample.",
  payCycle: "A repeating credit pattern is shown for discussion only; it is not a salary or income claim.",
};

export const sampleFacts = [
  { id: "policy-due", label: "When was the premium due?", choices: ["I know the due date", "I am not sure"] },
  { id: "payment-route", label: "Was it paid another way?", choices: ["Yes", "No", "I am not sure"] },
];
