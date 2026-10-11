import * as React from "react";

/** Per-device display preferences (not business data), kept in localStorage. */
export type Theme = "light" | "dark";
export type Perf = "glass" | "lite";

function read<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T | null) ?? fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: preference lasts for this session only */
  }
}

export function applyPreferences() {
  const root = document.documentElement;
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = read<Theme>("nc.theme", prefersDark ? "dark" : "light");
  root.dataset.perf = read<Perf>("nc.perf", "glass");
}

export function usePreference<T extends string>(key: "theme" | "perf", fallback: T) {
  const storageKey = `nc.${key}`;
  const [value, setValue] = React.useState<T>(
    () => (document.documentElement.dataset[key] as T | undefined) ?? read(storageKey, fallback),
  );
  const update = React.useCallback(
    (next: T) => {
      setValue(next);
      document.documentElement.dataset[key] = next;
      write(storageKey, next);
    },
    [key, storageKey],
  );
  return [value, update] as const;
}
