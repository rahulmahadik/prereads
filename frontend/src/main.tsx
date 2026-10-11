import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import OfflineBadge from "./components/OfflineBadge";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

const badgeRoot = document.createElement("div");
badgeRoot.id = "offline-root";
document.body.appendChild(badgeRoot);
ReactDOM.createRoot(badgeRoot).render(<OfflineBadge />);

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
