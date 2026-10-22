import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Star, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, Spinner } from "@/components/ui/feedback";
import { ApiError, api, upload } from "@/lib/api";
import { toFaDigits } from "@/lib/format";
import { cn } from "@/lib/utils";
import { type ItemImage, imageUrl } from "./api";

const MAX_IMAGES = 6;
const MAX_BYTES = 15 * 1024 * 1024;
const ACCEPT = "image/jpeg,image/png,image/webp";

/** Photos of one item: add (several at once), make one the main photo, remove, enlarge. */
export function ItemImages({ itemId, canManage }: { itemId: string; canManage: boolean }) {
  const qc = useQueryClient();
  const key = ["inventory", "item-images", itemId];
  const images = useQuery({ queryKey: key, queryFn: () => api.get<ItemImage[]>(`/inventory/items/${itemId}/images`) });
  const input = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(0);
  const [shown, setShown] = React.useState<ItemImage | null>(null);
  const list = images.data ?? [];

  const refresh = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["inventory", "items"] });
  };
  const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "خطا");

  const add = async (files: FileList | null) => {
    if (!files?.length) return;
    const room = MAX_IMAGES - list.length;
    const chosen = Array.from(files).slice(0, Math.max(room, 0));
    if (files.length > room) toast.warning(`هر کالا حداکثر ${toFaDigits(MAX_IMAGES)} عکس دارد`);
    for (const f of chosen) {
      if (f.size > MAX_BYTES) {
        toast.error(`«${f.name}» بیش از ۱۵ مگابایت است`);
        continue;
      }
      setBusy((n) => n + 1);
      try {
        await upload<ItemImage>(`/inventory/items/${itemId}/images`, f);
      } catch (e) {
        onError(e);
      } finally {
        setBusy((n) => n - 1);
      }
    }
    refresh();
  };

  const remove = useMutation({
    mutationFn: (im: ItemImage) => api.del(`/inventory/items/${itemId}/images/${im.id}`, ""),
    onSuccess: refresh,
    onError,
  });
  const makeMain = useMutation({
    mutationFn: (im: ItemImage) =>
      api.put<ItemImage[]>(`/inventory/items/${itemId}/images/order`, { ids: [im.id, ...list.filter((x) => x.id !== im.id).map((x) => x.id)] }, ""),
    onSuccess: refresh,
    onError,
  });

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-semibold text-ink">عکس‌های کالا</legend>
      {images.isLoading ? (
        <Spinner />
      ) : (
        <div className="flex flex-wrap gap-3">
          {list.map((im) => (
            <div key={im.id} className="group relative size-28 overflow-hidden rounded-xl ring-1 ring-[var(--line)]">
              <button type="button" className="size-full" onClick={() => setShown(im)} aria-label="نمایش بزرگ">
                <img src={imageUrl(im.id)} alt="" loading="lazy" className="size-full object-cover" />
              </button>
              {im.position === 0 ? (
                <Badge tone="success" className="absolute top-1 right-1">اصلی</Badge>
              ) : null}
              {canManage ? (
                <div className="absolute inset-x-1 bottom-1 flex justify-between gap-1">
                  {im.position !== 0 ? (
                    <Button size="icon" variant="outline" className="size-7 bg-white/90" aria-label="عکس اصلی شود" title="عکس اصلی شود" onClick={() => makeMain.mutate(im)}>
                      <Star />
                    </Button>
                  ) : <span />}
                  <Button
                    size="icon"
                    variant="outline"
                    className="size-7 bg-white/90 text-danger"
                    aria-label="حذف عکس"
                    title="حذف عکس"
                    onClick={() => window.confirm("این عکس حذف شود؟") && remove.mutate(im)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ) : null}
            </div>
          ))}
          {canManage && list.length < MAX_IMAGES ? (
            <button
              type="button"
              onClick={() => input.current?.click()}
              disabled={busy > 0}
              className={cn(
                "flex size-28 flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-[var(--line)] text-xs text-ink-soft hover:border-brand-400 hover:text-brand-600",
                busy > 0 && "opacity-60",
              )}
            >
              {busy > 0 ? <Spinner /> : <ImagePlus className="size-6" />}
              {busy > 0 ? "در حال ارسال…" : "افزودن عکس"}
            </button>
          ) : null}
          {!canManage && !list.length ? <p className="text-sm text-ink-faint">عکسی ندارد</p> : null}
        </div>
      )}
      {canManage ? (
        <p className="text-xs text-ink-faint">
          JPEG، PNG یا WebP تا ۱۵ مگابایت؛ حداکثر {toFaDigits(MAX_IMAGES)} عکس. سرور عکس را کوچک می‌کند و اطلاعات مکان و دوربین را حذف می‌کند. عکس اصلی در فهرست و اپ ویزیتور اول نشان داده می‌شود.
        </p>
      ) : null}
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          void add(e.target.files);
          e.target.value = "";
        }}
      />
      {shown ? (
        <Dialog open onOpenChange={(o) => !o && setShown(null)}>
          <DialogContent title="عکس کالا" className="max-w-4xl">
            <img src={imageUrl(shown.id, "large")} alt="" className="mx-auto max-h-[75vh] rounded-xl object-contain" />
          </DialogContent>
        </Dialog>
      ) : null}
    </fieldset>
  );
}
