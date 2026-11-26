import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/space-grotesk/300.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/jetbrains-mono/400.css";
import App, { BASE_KEY, TOKEN_KEY } from "./App.tsx";
import { takeLaunchToken } from "./hash-route.ts";
import "./styles.css";
import { registerShellWorker } from "./sw.ts";

// The launcher opens a URL whose fragment carries the bearer token. Consume it before React
// mounts so the first paint is the workspace, not the connect gate. The helper also removes the
// fragment from history; the token then lives only in localStorage, where the app already keeps it.
const launchToken = takeLaunchToken();
if (launchToken) {
  localStorage.setItem(TOKEN_KEY, launchToken);
  localStorage.setItem(BASE_KEY, window.location.origin);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// After the first paint: a worker that failed to register must never delay the app.
void registerShellWorker();
