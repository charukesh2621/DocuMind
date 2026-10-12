export const API_BASE = "http://localhost:8000";

export async function fetchJson(endpoint, options = {}) {
    const res = await fetch(API_BASE + endpoint, options);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "API error");
    return data;
}
