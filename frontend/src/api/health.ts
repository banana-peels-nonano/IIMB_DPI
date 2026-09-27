export type BackendHealth = "checking" | "available" | "unavailable";

/** Reads only the existing Flask health flag; operational capture metadata is discarded. */
export async function checkBackendHealth(signal?: AbortSignal): Promise<boolean> {
  const response = await fetch("/_mirror_backend/health", {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) return false;
  const payload: unknown = await response.json();
  return typeof payload === "object" && payload !== null && "ok" in payload && payload.ok === true;
}
