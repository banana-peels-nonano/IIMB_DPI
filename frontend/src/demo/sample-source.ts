import type { DemoCard } from "./sample-contract";
import { sampleAhead, sampleCards, sampleFacts, sampleHousehold } from "./sample-contract";

/** Read-only demo adapter. All money-related copy remains pre-authored in the fixture. */
export interface LocalDemoSource {
  readonly mode: "sample";
  readonly nowCards: readonly DemoCard[];
  readonly aheadItems: readonly (typeof sampleAhead)[number][];
  readonly household: Readonly<Omit<typeof sampleHousehold, "commitments" | "credits"> & {
    commitments: readonly string[];
    credits: readonly string[];
  }>;
  readonly facts: readonly (Omit<(typeof sampleFacts)[number], "choices"> & {
    choices: readonly string[];
  })[];
}

export const activeDemoSource: LocalDemoSource = Object.freeze({
  mode: "sample",
  nowCards: Object.freeze([...sampleCards]),
  aheadItems: Object.freeze([...sampleAhead]),
  household: Object.freeze({
    ...sampleHousehold,
    commitments: Object.freeze([...sampleHousehold.commitments]),
    credits: Object.freeze([...sampleHousehold.credits]),
  }),
  facts: Object.freeze(sampleFacts.map((fact) => Object.freeze({
    ...fact,
    choices: Object.freeze([...fact.choices]),
  }))),
});
