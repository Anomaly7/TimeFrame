// Runs Google sign-in for the popup. The popup closes as soon as Google's window opens, so the
// sign-in has to finish here; the token is saved to chrome.storage and the popup is signed in next time.

const API = "https://calender-app-mm4q.onrender.com";

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type !== "google-signin") return false;
  const redirect = chrome.identity.getRedirectURL("auth"); // https://<extension-id>.chromiumapp.org/auth
  const url = `${API}/auth/login?app_redirect=${encodeURIComponent(redirect)}`;
  chrome.identity.launchWebAuthFlow({ url, interactive: true }, async (finalUrl) => {
    if (chrome.runtime.lastError || !finalUrl) {
      reply({ ok: false, error: chrome.runtime.lastError?.message || "Sign-in was cancelled." });
      return;
    }
    const params = new URLSearchParams(new URL(finalUrl).hash.slice(1));
    const token = params.get("token");
    if (!token) {
      reply({ ok: false, error: params.get("auth_error") || "Google sign-in didn't finish." });
      return;
    }
    await chrome.storage.local.set({ token, userId: params.get("user") || "", renewedAt: 0, remember: msg.remember !== false });
    reply({ ok: true });
  });
  return true; // reply comes later
});
