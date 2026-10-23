import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Logo } from "./Logo";

export type Branding = { organization_name: string; logo_version: string | null };

export const brandingKey = ["system", "branding"] as const;

/** The shop's name and logo version; public, so the login page can show them too. */
export function useBranding() {
  return useQuery({
    queryKey: brandingKey,
    queryFn: () => api.get<Branding>("/system/branding"),
    staleTime: 600_000,
    retry: false,
  });
}

/** The logo URL changes with every new logo, so browsers never show an old one. */
export const logoUrl = (version: string) => `/api/v1/system/logo?v=${encodeURIComponent(version)}`;

/** The shop's logo when it has one, else the NEXTCAM mark. */
export function BrandMark({ size = 40 }: { size?: number }) {
  const b = useBranding();
  const v = b.data?.logo_version;
  if (!v) return <Logo size={size} />;
  return <img src={logoUrl(v)} alt="" width={size} height={size} className="object-contain" style={{ width: size, height: size }} />;
}
