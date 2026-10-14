import { afterEach, describe, expect, it } from "vitest";
import { api, ApiError, request, setToken, waitForJob } from "./client";
import { error, mockApi } from "../test/mockApi";

afterEach(() => setToken(null));

describe("the API client", () => {
  it("sends JSON and the token, and returns the parsed body", async () => {
    const { calls } = mockApi([["/api/results/7/decision", () => ({ result_id: 7, invoice_id: "INV1", workflow_status: "REVIEW_REJECTED" })]]);
    setToken("s3cret");
    const out = await api.decide(7, "reject", "A. Auditor", "");
    expect(out.workflow_status).toBe("REVIEW_REJECTED");
    const headers = new Headers(calls[0].init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer s3cret");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ decision: "reject", reviewer: "A. Auditor", justification: "" });
  });

  it("turns every kind of error detail into an ApiError", async () => {
    mockApi([
      ["/text", () => error(400, "an override needs a written justification")],
      ["/problems", () => error(422, { message: "not adopted", problems: ["Rule 4.3.1 is missing"] })],
      ["/validation", () => error(422, [{ msg: "field required" }, { msg: "too short" }])],
      ["/plain", () => new Response("gateway down", { status: 502 })],
    ]);
    await expect(request("/text")).rejects.toMatchObject({ status: 400, message: "an override needs a written justification" });
    await expect(request("/problems")).rejects.toMatchObject({ status: 422, message: "not adopted", problems: ["Rule 4.3.1 is missing"] });
    await expect(request("/validation")).rejects.toMatchObject({ message: "field required; too short" });
    await expect(request("/plain")).rejects.toBeInstanceOf(ApiError);
  });

  it("does not send a JSON content type with an upload", async () => {
    const { calls } = mockApi([["/api/policy/preview", () => ({ upload_id: "x" })]]);
    await api.preview(new File(["%PDF-1.4"], "p.pdf", { type: "application/pdf" }));
    expect(new Headers(calls[0].init?.headers).has("Content-Type")).toBe(false);
    expect(calls[0].init?.body).toBeInstanceOf(FormData);
  });

  it("polls a job until it is done, and fails with the job's error", async () => {
    let polls = 0;
    mockApi([["/api/jobs/j1", () => (++polls < 2 ? { id: "j1", status: "running", done: 1, total: 2 } : { id: "j1", status: "done", result: { ok: true } })]]);
    const seen: string[] = [];
    const result = await waitForJob({ id: "j1", kind: "x", status: "queued", done: 0, total: 2, result: null, error: null, seconds: 0 }, (j) => seen.push(j.status), 1);
    expect(result).toEqual({ ok: true });
    expect(seen).toEqual(["queued", "running", "done"]);
    await expect(waitForJob({ id: "j2", kind: "x", status: "failed", done: 0, total: 0, result: null, error: "KeyError: INV1", seconds: 0 })).rejects.toThrow("KeyError: INV1");
  });
});
