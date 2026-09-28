export interface MirrorAppContract {
  contract: "mirror.app/1.0";
  generated: { as_of: string; data_mode: string; [key: string]: unknown };
  now: { cards: readonly unknown[]; [key: string]: unknown };
  ahead: Readonly<Record<string, unknown>>;
  our_household: Readonly<Record<string, unknown>>;
  what_we_know: Readonly<Record<string, unknown>>;
}

/** UI operations expected from a future customer API; no matching backend routes exist yet. */
export interface MirrorContractSource {
  getContract(signal?: AbortSignal): Promise<MirrorAppContract>;
  submitAnswer(input: { cardId: string; optionId: string }): Promise<void>;
  correctFact(input: { factId: string; value: string }): Promise<void>;
  setPurpose(input: { purposeId: string; enabled: boolean }): Promise<void>;
  forgetSession(): Promise<void>;
}

/** Explicitly unavailable until an approved customer-facing API is implemented. */
export class DisabledLiveContractSource implements MirrorContractSource {
  private unavailable(): never {
    throw new Error("Live Mirror data is unavailable: the backend has no customer contract API yet.");
  }
  async getContract(): Promise<MirrorAppContract> { return this.unavailable(); }
  async submitAnswer(): Promise<void> { return this.unavailable(); }
  async correctFact(): Promise<void> { return this.unavailable(); }
  async setPurpose(): Promise<void> { return this.unavailable(); }
  async forgetSession(): Promise<void> { return this.unavailable(); }
}
