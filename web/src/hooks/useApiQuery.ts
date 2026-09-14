import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { subscribeRealtime } from "../api/realtime";

export function useApiQuery<T>(
  path: string | null,
  options: { ignoreLiveTick?: boolean } = {},
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [generation, setGeneration] = useState(0);
  const inFlight = useRef(false);
  const refreshQueued = useRef(false);
  const requestId = useRef(0);
  const hasData = useRef(false);
  const activePath = useRef<string | null>(path);

  const reload = useCallback(() => {
    if (inFlight.current) {
      refreshQueued.current = true;
      return;
    }
    setGeneration((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!path) return undefined;
    return subscribeRealtime(reload, { ignoreLiveTick: options.ignoreLiveTick });
  }, [path, reload, options.ignoreLiveTick]);

  useEffect(() => {
    if (!path) {
      requestId.current += 1;
      inFlight.current = false;
      hasData.current = false;
      activePath.current = null;
      setLoading(false);
      setError(null);
      return;
    }
    if (activePath.current !== path) {
      activePath.current = path;
      hasData.current = false;
      setData(null);
    }
    const controller = new AbortController();
    const currentRequest = ++requestId.current;
    inFlight.current = true;
    setLoading(!hasData.current);
    setError(null);
    api
      .get<T>(path, controller.signal)
      .then((value) => {
        hasData.current = true;
        setData(value);
      })
      .catch((reason) => {
        if (reason?.name !== "AbortError") {
          setError(reason instanceof ApiError ? reason : new ApiError(0, {
            code: "network_error",
            message: "Não foi possível acessar o servidor.",
          }));
        }
      })
      .finally(() => {
        if (currentRequest !== requestId.current) return;
        inFlight.current = false;
        if (!controller.signal.aborted) {
          setLoading(false);
          if (refreshQueued.current) {
            refreshQueued.current = false;
            setGeneration((value) => value + 1);
          }
        }
      });
    return () => controller.abort();
  }, [path, generation]);

  return { data, error, loading, reload };
}
