import { useEffect, useState } from "react";
import { subscribeRealtimeStatus } from "../api/realtime";
import type { RealtimeStatus } from "../api/realtime";

export function useRealtimeStatus() {
  const [status, setStatus] = useState<RealtimeStatus>("connecting");
  useEffect(() => subscribeRealtimeStatus(setStatus), []);
  return status;
}
