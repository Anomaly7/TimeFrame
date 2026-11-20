// Runs only on timeframecalender.com. Shares the website's sign-in with the extension:
// sign in on the site once and the toolbar popup is signed in too; sign out there and
// the popup signs out. Nothing else on the page is read.

function syncSignIn() {
  const token = sessionStorage.getItem("authToken") || localStorage.getItem("authToken");
  if (token) {
    chrome.storage.local.get(["siteToken", "token"], (saved) => {
      // Only take the site's token when it changed (a new sign-in or the site renewed it);
      // otherwise keep the extension's own renewed copy.
      if (saved.siteToken !== token || !saved.token) {
        chrome.storage.local.set({
          token,
          userId: localStorage.getItem("userId") || "",
          remember: localStorage.getItem("rememberMe") !== "0",
          // Your day start/end, meeting length and preferred times, so the popup suggests the same slots.
          settings: localStorage.getItem("settings") || "",
          siteToken: token,
          renewedAt: 0,
        });
      }
    });
  } else {
    chrome.storage.local.get("siteToken", (saved) => {
      // Only sign the extension out if the site was signed in before (a real sign-out),
      // not on a first visit to the sign-in page.
      if (saved.siteToken) chrome.storage.local.remove(["token", "userId", "siteToken", "renewedAt"]);
    });
  }
}

syncSignIn();
document.addEventListener("visibilitychange", () => { if (!document.hidden) syncSignIn(); });
window.addEventListener("storage", syncSignIn);
// The site signs in/out without a page load sometimes (e.g. Sign out reloads, email sign-in reloads),
// so a light re-check catches anything missed.
setInterval(syncSignIn, 5000);
