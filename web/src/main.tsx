import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { ReferenceClockProvider } from "./system/ReferenceClock";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/ai.css";
import "./styles/andon.css";
import "./styles/welding.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ReferenceClockProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ReferenceClockProvider>
    </BrowserRouter>
  </StrictMode>,
);

