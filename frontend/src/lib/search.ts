/**
 * Search in the browser (ADR-0030): the same folding as the server (``app/core/text.py``)
 * and the same order of results, over the register's copy of the catalogue.
 */

const FOLD: [string, string][] = [
  ["ي", "ی"],
  ["ى", "ی"],
  ["ئ", "ی"],
  ["ك", "ک"],
  ["ة", "ه"],
  ["أ", "ا"],
  ["إ", "ا"],
  ["ٱ", "ا"],
  ["ؤ", "و"],
  ["‌", ""],
  ["ـ", ""],
  ...Array.from({ length: 10 }, (_, i): [string, string] => [String.fromCharCode(0x06f0 + i), String(i)]),
  ...Array.from({ length: 10 }, (_, i): [string, string] => [String.fromCharCode(0x0660 + i), String(i)]),
];
const MAP = new Map(FOLD);

/** Search form of a text: Arabic/Persian letters and digits unified, spaces collapsed. */
export function fold(text: string): string {
  let out = "";
  for (const ch of text) out += MAP.get(ch) ?? ch;
  return out.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

/** One row of ``GET /inventory/items/search-index``. */
export type IndexRow = [
  id: string,
  code: string,
  name: string,
  folded: string,
  unit: string,
  price: string | null,
  weighted: boolean,
  barcodes: string[],
  image: string | null,
];

export type SearchIndex = { version: string; items: IndexRow[] };

export type Hit = { id: string; code: string; name: string; unit: string; price: string | null; weighted: boolean; image: string | null };

/**
 * Best matches first, like the server: 0 exact code or barcode · 1 code starting with it ·
 * 2 name starting with it · 3 a word of the name starting with it · 4 every word contained.
 */
export function searchIndex(index: SearchIndex, text: string, limit = 12): Hit[] {
  const q = fold(text);
  if (!q) return [];
  const words = q.split(" ");
  const code = q.replace(/\s+/g, "");
  const ranked: [number, IndexRow][] = [];
  for (const row of index.items) {
    const c = row[1].toLowerCase();
    const name = row[3].toLowerCase();
    let rank = -1;
    if (c === code || row[7].includes(code)) rank = 0;
    else if (c.startsWith(code)) rank = 1;
    else if (words.every((w) => name.includes(w))) {
      rank = name.startsWith(q) ? 2 : name.includes(` ${q}`) ? 3 : 4;
    }
    if (rank >= 0) ranked.push([rank, row]);
  }
  ranked.sort((a, b) => a[0] - b[0] || a[1][2].length - b[1][2].length || a[1][2].localeCompare(b[1][2], "fa"));
  return ranked.slice(0, limit).map(([, r]) => ({ id: r[0], code: r[1], name: r[2], unit: r[4], price: r[5], weighted: r[6], image: r[8] }));
}
