import { ApiError, api } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(body === undefined ? "" : JSON.stringify(body), { status }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "nextcam_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("api client", () => {
  it("echoes the CSRF cookie and sends Idempotency-Key on writes", async () => {
    document.cookie = "nextcam_csrf=abc123";
    const fetchFn = mockFetch(201, { id: "1" });
    await api.post("/users", { a: 1 }, { idempotencyKey: "key-1" });
    const [, init] = fetchFn.mock.calls[0];
    expect(init.headers["X-CSRF-Token"]).toBe("abc123");
    expect(init.headers["Idempotency-Key"]).toBe("key-1");
    expect(init.credentials).toBe("same-origin");
  });

  it("never sends the CSRF header on reads", async () => {
    document.cookie = "nextcam_csrf=abc123";
    const fetchFn = mockFetch(200, {});
    await api.get("/auth/me");
    expect(fetchFn.mock.calls[0][1].headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("sends If-Match for versioned updates", async () => {
    const fetchFn = mockFetch(200, {});
    await api.patch("/users/1", { full_name: "x" }, "00ab");
    expect(fetchFn.mock.calls[0][1].headers["If-Match"]).toBe("00ab");
  });

  it("maps server errors and broadcasts 401", async () => {
    mockFetch(409, { error: { code: "version_conflict", message: "تغییر کرده است", incident: "i1" } });
    await expect(api.get("/x")).rejects.toMatchObject({ status: 409, code: "version_conflict", incident: "i1" });

    const onUnauthorized = vi.fn();
    window.addEventListener("nextcam:unauthorized", onUnauthorized);
    mockFetch(401, { error: { code: "not_authenticated", message: "ابتدا وارد شوید" } });
    await expect(api.get("/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("reports network failures in Persian", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.get("/x")).rejects.toMatchObject({ code: "network_error", message: "ارتباط با سرور برقرار نشد" });
  });
});
