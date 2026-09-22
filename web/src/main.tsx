import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ReferenceClockProvider } from "./system/ReferenceClock";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/ai.css";
import "./styles/andon.css";
import "./styles/welding.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <ReferenceClockProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </ReferenceClockProvider>
      </ErrorBoundary>
    </BrowserRouter>
  </StrictMode>,
);

