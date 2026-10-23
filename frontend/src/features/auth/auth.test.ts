import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { meKey, signOut } from "./auth";

afterEach(() => vi.unstubAllGlobals());

describe("signOut", () => {
  it("tells whoever watches the user that nobody is signed in, and drops other data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
    const qc = new QueryClient();
    qc.setQueryData(meKey, { id: "u1" });
    qc.setQueryData(["items"], [1, 2]);
    const gate = new QueryObserver(qc, { queryKey: meKey, queryFn: () => null, staleTime: Infinity });
    const seen: unknown[] = [];
    const stop = gate.subscribe((r) => seen.push(r.data));
    window.history.replaceState(null, "", "/accounting/vouchers");

    await signOut(qc);

    expect(seen.at(-1)).toBeNull();
    expect(qc.getQueryData(["items"])).toBeUndefined();
    expect(window.location.pathname).toBe("/");
    stop();
  });

  it("still signs out on this device when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const qc = new QueryClient();
    qc.setQueryData(meKey, { id: "u1" });
    await signOut(qc);
    expect(qc.getQueryData(meKey)).toBeNull();
  });
});
