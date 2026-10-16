import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api } from "@/lib/api";

export type Transport = "none" | "tcp" | "windows" | "serial";

export type Device = {
  id: string;
  name: string;
  branch_id: string;
  cash_register_id: string | null;
  cash_register_name: string | null;
  status: "pending" | "active" | "revoked";
  online: boolean;
  last_seen_at: string | null;
  paired_at: string | null;
  agent_version: string | null;
  platform: string | null;
  printer_state: string | null;
  /** Offline sales still on the register (ADR-0017). */
  offline_queue: number;
  last_sync_at: string | null;
  printer_transport: Transport;
  printer_address: string | null;
  paper_width: 58 | 80;
  cut_paper: boolean;
  drawer_enabled: boolean;
  drawer_pin: 2 | 5;
  /** Only in the response that creates it. */
  pairing_code: string | null;
  pairing_expires_at: string | null;
  row_version: string;
};

export type Job = {
  id: string;
  kind: "receipt" | "drawer" | "test";
  status: "queued" | "sent" | "done" | "failed" | "expired";
  error: string | null;
  attempts: number;
  created_at: string;
  sent_at: string | null;
  finished_at: string | null;
};

export type RegisterDevice = { device_id: string | null; online: boolean; printer: boolean; drawer: boolean };

export const TRANSPORT_LABEL: Record<Transport, string> = {
  none: "بدون چاپگر",
  tcp: "شبکه (TCP/IP)",
  windows: "USB از طریق ویندوز",
  serial: "درگاه سریال (COM)",
};

export const JOB_LABEL: Record<Job["status"], string> = {
  queued: "در صف",
  sent: "ارسال‌شده به دستگاه",
  done: "انجام شد",
  failed: "ناموفق",
  expired: "منقضی",
};

export const KIND_LABEL: Record<Job["kind"], string> = { receipt: "فیش", drawer: "کشوی پول", test: "صفحه آزمایشی" };

export function useRegisterDevice(registerId: string) {
  return useQuery({
    queryKey: ["devices", "register", registerId],
    queryFn: () => api.get<RegisterDevice>(`/devices/registers/${registerId}`),
    refetchInterval: 10_000,
    retry: false,
  });
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Wait for the agent's answer; "sent" for too long means the result is unknown. */
export async function waitForJob(id: string, timeoutMs = 12_000): Promise<Job> {
  const until = Date.now() + timeoutMs;
  let job = await api.get<Job>(`/devices/jobs/${id}`);
  while (job.status === "queued" || job.status === "sent") {
    if (Date.now() > until) return job;
    await sleep(600);
    job = await api.get<Job>(`/devices/jobs/${id}`);
  }
  return job;
}

/**
 * Print a sales receipt through the register's Device Agent; anything that is not a
 * confirmed print falls back to (or offers) browser printing.
 */
export async function printViaAgent(
  invoiceId: string,
  opts: { reprint?: boolean; browserPrint: () => void },
): Promise<void> {
  let job: Job;
  try {
    job = await api.post<Job>("/devices/print-receipt", { invoice_id: invoiceId, reprint: !!opts.reprint });
  } catch (e) {
    toast.warning(e instanceof ApiError ? e.message : "چاپگر صندوق در دسترس نیست", {
      action: { label: "چاپ با مرورگر", onClick: opts.browserPrint },
    });
    return;
  }
  const done = await waitForJob(job.id).catch(() => null);
  if (done?.status === "done") {
    toast.success("فیش چاپ شد");
    return;
  }
  const why =
    done?.status === "failed"
      ? `چاپ ناموفق: ${done.error ?? "خطای چاپگر"}`
      : "پاسخی از چاپگر نرسید؛ کاغذ را بررسی کنید";
  toast.error(why, { action: { label: "چاپ با مرورگر", onClick: opts.browserPrint }, duration: 10_000 });
}
