import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";
import { clearLastSnapshots } from "../hooks/useApiQuery";

// 1000 ms (padrão) estoura quando a suíte roda junto de outra carga pesada;
// o teste continua falhando de verdade se a UI nunca chegar ao estado esperado.
configure({ asyncUtilTimeout: 4000 });

afterEach(() => {
  cleanup();
  clearLastSnapshots();
});
