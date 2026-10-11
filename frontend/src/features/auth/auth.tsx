import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { ApiError, api } from "@/lib/api";

export type RoleRef = { id: string; code: string; name: string };
export type Me = {
  id: string;
  username: string;
  full_name: string;
  must_change_password: boolean;
  roles: RoleRef[];
  permissions: string[];
  all_branches: boolean;
  branch_ids: string[];
  session_expires_at: string | null;
};

export const meKey = ["auth", "me"] as const;

export function useMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: async () => {
      try {
        return await api.get<Me>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

/** UI hint only — the backend enforces every permission independently. */
export function useCan() {
  const { data } = useMe();
  return React.useCallback(
    (permission?: string) => !permission || Boolean(data?.permissions.includes(permission)),
    [data],
  );
}

export function Can({ permission, children }: { permission: string; children: React.ReactNode }) {
  const can = useCan();
  return can(permission) ? <>{children}</> : null;
}

/** Any 401 from any request drops the cached user so the router shows the login page. */
export function useUnauthorizedListener() {
  const qc = useQueryClient();
  React.useEffect(() => {
    const onUnauthorized = () => qc.setQueryData(meKey, null);
    window.addEventListener("nextcam:unauthorized", onUnauthorized);
    return () => window.removeEventListener("nextcam:unauthorized", onUnauthorized);
  }, [qc]);
}
