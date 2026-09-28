export type JsonObject = Record<string, unknown>;

export interface MirrorAppContract extends JsonObject {
  contract: "mirror.app/1.0";
  generated: JsonObject & { as_of: string; data_mode: string };
  now: JsonObject & { cards: JsonObject[]; since_last_time: JsonObject; resolved: JsonObject[] };
  ahead: JsonObject;
  our_household: JsonObject;
  what_we_know: JsonObject;
}

export interface LocalSession {
  mode: "local-demo";
  authenticated: false;
  data_source: string;
  aa_connected: false;
  consent_status: "not_started";
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/_mirror_backend/api/customer/${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = typeof payload === "object" && payload !== null && "error" in payload
      ? String(payload.error)
      : `The local service returned ${response.status}.`;
    throw new Error(message);
  }
  return payload as T;
}

export const mirrorApi = {
  getSession(signal?: AbortSignal) {
    return requestJson<LocalSession>("session", { signal });
  },
  getContract(signal?: AbortSignal) {
    return requestJson<MirrorAppContract>("contract", { signal });
  },
  submitAnswer(input: { cardId: string; optionId: string }) {
    return requestJson<MirrorAppContract>("answers", { method: "POST", body: JSON.stringify(input) });
  },
  correctFact(input: { factId: string; value: string }) {
    return requestJson<MirrorAppContract>("facts/correct", { method: "POST", body: JSON.stringify(input) });
  },
  setPurpose(input: { purposeId: string; enabled: boolean }) {
    return requestJson<MirrorAppContract>("purpose", { method: "POST", body: JSON.stringify(input) });
  },
  forgetSession() {
    return requestJson<{ forgotten: boolean; state_removed: boolean; message: string }>("forget", { method: "POST" });
  },
};
