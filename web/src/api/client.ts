export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let onUnauthorized: () => void = () => {};

export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

export function readToken(): string {
  return localStorage.getItem("jifen_token") || "";
}

export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers = new Headers(opts.headers);
  headers.set("X-Token", readToken());
  let res: Response;
  try {
    res = await fetch(path, { ...opts, headers });
  } catch {
    throw new ApiError(0, "network");
  }
  if (res.status === 401) {
    onUnauthorized();
    throw new ApiError(401, "unauthorized");
  }
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return (await res.json()) as T;
}
