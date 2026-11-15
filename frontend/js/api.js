/* Thin fetch wrapper around the BLAQUE ANALYSIS API. */

const TOKEN_KEY = "blaque.token";
const BASE = "/api";

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    this.details = payload?.details || null;
    this.code = payload?.code || "request_failed";
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage may be unavailable in private mode */
  }
}

async function request(path, options = {}) {
  const {
    method = "GET",
    body,
    auth = true,
    timeout = 45000,
    signal: externalSignal,
  } = options;

  const headers = { Accept: "application/json" };
  const token = auth ? getToken() : null;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const controller = new AbortController();
  let timer = null;
  if (timeout > 0) {
    timer = setTimeout(() => controller.abort(), timeout);
  }
  const onAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", onAbort, { once: true });
  }

  try {
    const response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      credentials: "same-origin",
    });

    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { error: { message: text.slice(0, 300) } };
      }
    }

    if (!response.ok) {
      const payload = data?.error || { message: `Request failed (${response.status}).` };
      if (response.status === 401 && token) {
        window.dispatchEvent(new CustomEvent("blaque:unauthorized"));
        // Public pages should still work after a session expires or the account
        // is removed. Retry a read once without credentials.
        if (method === "GET") {
          return request(path, { ...options, auth: false });
        }
      }
      throw new ApiError(payload.message || `Request failed (${response.status}).`, response.status, payload);
    }
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error?.name === "AbortError") {
      throw new ApiError("The request took too long. Please try again.", 0, { code: "timeout" });
    }
    throw new ApiError(
      "Could not reach the server. Check your connection and try again.",
      0,
      { code: "network_error" },
    );
  } finally {
    if (timer) clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener("abort", onAbort);
  }
}

export const api = {
  get: (path, options = {}) => request(path, { ...options, method: "GET" }),
  post: (path, body, options = {}) => request(path, { ...options, method: "POST", body }),
  patch: (path, body, options = {}) => request(path, { ...options, method: "PATCH", body }),
  put: (path, body, options = {}) => request(path, { ...options, method: "PUT", body }),
  del: (path, options = {}) => request(path, { ...options, method: "DELETE" }),
};

export function qs(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}
