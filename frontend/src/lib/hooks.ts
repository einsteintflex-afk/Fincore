import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api, type RequestOptions } from "./api";
import type { Business, Notification, Platform, Wallet } from "./types";
import { useToast } from "@/components/toast";

export function useGet<T = any>(key: QueryKey, path: string | null, query?: RequestOptions["query"], opts: { refetchInterval?: number } = {}) {
  return useQuery<T>({
    queryKey: [...key, query ?? {}],
    queryFn: () => api<T>(path as string, { query }),
    enabled: path !== null,
    ...opts,
  });
}

/** Mutation that shows a toast and invalidates the given query keys on success. */
export function useAction<TVars = any, TRes = any>(
  fn: (vars: TVars) => Promise<TRes>,
  { success, invalidate = [], onSuccess }: { success?: string | ((r: TRes) => string); invalidate?: QueryKey[]; onSuccess?: (r: TRes) => void } = {},
) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation<TRes, Error, TVars>({
    mutationFn: fn,
    onSuccess: (res) => {
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
      if (success) toast.success(typeof success === "function" ? success(res) : success);
      onSuccess?.(res);
    },
    onError: (e) => toast.error(e),
  });
}

export const usePlatform = () => useGet<Platform>(["platform"], "/platform");
export const useWallets = () => useGet<Wallet[]>(["wallets"], "/wallets");
export const useBusinesses = (enabled = true) => useGet<Business[]>(["businesses"], enabled ? "/businesses" : null);
export const useNotifications = () =>
  useGet<{ unread: number; items: Notification[] }>(["notifications"], "/me/notifications", undefined, { refetchInterval: 30000 });
