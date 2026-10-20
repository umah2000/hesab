import { describe, expect, it } from "vitest";
import { invoiceLabel } from "@/features/sales/api";
import { gatewayState, noteGatewayHeaders } from "./gateway";

describe("register gateway headers", () => {
  it("ignores responses that did not pass through the gateway", () => {
    noteGatewayHeaders(new Headers({ "Content-Type": "application/json" }));
    expect(gatewayState()).toEqual({ viaGateway: false, offline: false, queue: 0 });
  });

  it("follows the mode and the queue the gateway reports", () => {
    noteGatewayHeaders(new Headers({ "X-Nextcam-Mode": "offline", "X-Nextcam-Queue": "3" }));
    expect(gatewayState()).toEqual({ viaGateway: true, offline: true, queue: 3 });
    noteGatewayHeaders(new Headers({ "X-Nextcam-Mode": "online", "X-Nextcam-Queue": "0" }));
    expect(gatewayState()).toEqual({ viaGateway: true, offline: false, queue: 0 });
  });
});

describe("invoice label", () => {
  it("uses the register number until the server numbers an offline sale", () => {
    expect(invoiceLabel({ number: 12, device_number: null })).toBe("فاکتور ۱۲");
    expect(invoiceLabel({ number: null, device_number: "AB12CD34-3" })).toBe("فیش صندوق AB12CD34-3");
    expect(invoiceLabel({ number: 7, device_number: "AB12CD34-3" })).toBe("فاکتور ۷");
  });
});
