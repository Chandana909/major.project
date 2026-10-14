import { vi } from "vitest";

export type Handler = (url: string, init?: RequestInit) => unknown | Response | Promise<unknown | Response>;

/** Replace fetch with a router of canned responses: the first pattern the URL contains wins. */
export function mockApi(routes: [string, Handler][]) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    calls.push({ url, init });
    const found = routes.find(([pattern]) => url.includes(pattern));
    if (!found) return new Response(JSON.stringify({ detail: `no mock for ${url}` }), { status: 404 });
    const body = await found[1](url, init);
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

export function error(status: number, detail: unknown): Response {
  return new Response(JSON.stringify({ detail }), { status, headers: { "Content-Type": "application/json" } });
}
