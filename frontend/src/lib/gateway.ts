/**
 * Register gateway state (ADR-0017). When the POS is opened through the Device Agent on
 * http://127.0.0.1:47616, every API response says whether the server answered
 * (`X-Nextcam-Mode`) and how many offline sales are still waiting (`X-Nextcam-Queue`).
 * Opened straight from the server, these headers never appear and nothing changes.
 */
import * as React from "react";

export type GatewayState = { viaGateway: boolean; offline: boolean; queue: number };

let state: GatewayState = { viaGateway: false, offline: false, queue: 0 };
const listeners = new Set<() => void>();

export function noteGatewayHeaders(headers: Headers) {
  const mode = headers.get("X-Nextcam-Mode");
  if (!mode) return;
  const queue = Number(headers.get("X-Nextcam-Queue") ?? "0") || 0;
  const next = { viaGateway: true, offline: mode === "offline", queue };
  if (next.offline === state.offline && next.queue === state.queue && state.viaGateway) return;
  state = next;
  for (const l of listeners) l();
}

export function gatewayState(): GatewayState {
  return state;
}

export function useGateway(): GatewayState {
  return React.useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
  );
}
