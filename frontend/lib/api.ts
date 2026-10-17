export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8888/api/v1";

export async function fetchApi(endpoint: string, options: RequestInit = {}) {
  const url = `${API_BASE}${endpoint}`;
  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });
    if (!res.ok) {
      // The API explains refusals ({"error": ...} or FastAPI's {"detail": ...}); pass that on.
      const body = await res.json().catch(() => null);
      const reason = body?.error ?? (typeof body?.detail === "string" ? body.detail : null);
      throw new Error(reason || `API error: ${res.statusText}`);
    }
    if (res.status === 204) return null;
    return await res.json();
  } catch (error) {
    console.error(`Error fetching ${url}:`, error);
    throw error;
  }
}
