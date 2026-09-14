import { useState } from "react";
import { useAuth } from "../auth/AuthContext";

export function LogoutButton() {
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
      className="logout-button"
      type="button"
      disabled={pending}
      onClick={() => void leaveAccount()}
    >
      {pending ? "Saindo…" : "Sair"}
    </button>
  );
}
