import { useEffect, useState } from "react";

const standalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent);

// "Install app" in the account menu (PWA, 2026-11-25). Chrome/Edge/Android get the real install prompt;
// iPhone Safari gets the Add to Home Screen steps. Hidden once installed.
export default function InstallItem({ onDone, notify }) {
  const [canPrompt, setCanPrompt] = useState(() => !!window.__tfInstallPrompt);

  useEffect(() => {
    const on = () => setCanPrompt(true);
    window.addEventListener("tf-installable", on);
    return () => window.removeEventListener("tf-installable", on);
  }, []);

  if (standalone() || (!canPrompt && !isIOS())) return null;

  async function install() {
    onDone?.();
    const prompt = window.__tfInstallPrompt;
    if (prompt) {
      prompt.prompt();
      const { outcome } = await prompt.userChoice.catch(() => ({}));
      window.__tfInstallPrompt = null;
      setCanPrompt(false);
      if (outcome === "accepted") notify?.("TimeFrame is installed. Open it from your home screen or apps.");
      return;
    }
    notify?.("On iPhone: tap the Share button, then \"Add to Home Screen\".");
  }

  return <button role="menuitem" onClick={install}>📲 Install app</button>;
}
