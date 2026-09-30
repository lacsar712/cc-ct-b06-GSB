const TOKEN_KEY = "cnc_offset_token";
const USER_KEY = "cnc_offset_user";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser() {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function setSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

async function request(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, { ...options, headers });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const msg = data?.detail || data?.message || `请求失败 (${res.status})`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export function login(username, password) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function fetchSubmissions(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined)
  ).toString();
  return request(`/submissions${qs ? `?${qs}` : ""}`);
}

export function fetchSubmission(id) {
  return request(`/submissions/${id}`);
}

export function createSubmission(tool_code, offset_um) {
  return request("/submissions", {
    method: "POST",
    body: JSON.stringify({ tool_code, offset_um: Number(offset_um) }),
  });
}

export function fetchClaimants() {
  return request("/claimants");
}

export function fetchReassignments(claimantId) {
  const qs = claimantId ? `?claimant_id=${encodeURIComponent(claimantId)}` : "";
  return request(`/reassignments${qs}`);
}

export function reassignSubmission(id, to_claimant_id, note) {
  return request(`/submissions/${id}/reassign`, {
    method: "POST",
    body: JSON.stringify({ to_claimant_id, note }),
  });
}
