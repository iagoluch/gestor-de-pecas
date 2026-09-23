import { useState } from "react";
import { useAuth } from "../auth/AuthContext";

export function LogoutButton({ compact = false }: { compact?: boolean }) {
  const { logout } = useAuth();
  const [pending, setPending] = useState(false);

  async function leaveAccount() {
    if (pending) return;
    setPending(true);
    try {
      await logout();
    } finally {
      setPending(false);
    }
  }

  return (
    <button
      className={compact ? "logout-button logout-button--icon" : "logout-button"}
      type="button"
      disabled={pending}
      onClick={() => void leaveAccount()}
      aria-label="Sair"
      title={pending ? "Saindo…" : "Sair"}
    >
      {compact ? <DoorIcon /> : pending ? "Saindo…" : "Sair"}
    </button>
  );
}

function DoorIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
      <path d="M13 4H7a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M9 12h11m0 0-3.5-3.5M20 12l-3.5 3.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
