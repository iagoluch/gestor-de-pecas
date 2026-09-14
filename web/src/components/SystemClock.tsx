import { useEffect, useState } from "react";
import { useReferenceClock } from "../system/ReferenceClock";

export function SystemClock() {
  const { reference } = useReferenceClock();
  const [clock, setClock] = useState(() => reference ?? new Date());

  useEffect(() => {
    if (reference) {
      setClock(reference);
      return undefined;
    }
    setClock(new Date());
    const timer = window.setInterval(() => setClock(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, [reference]);

  return (
    <>
      <strong>{clock.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</strong>
      <small>{clock.toLocaleDateString("pt-BR")}</small>
    </>
  );
}
