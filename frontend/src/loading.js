// The full-screen TimeFrame loading screen lives in index.html (#boot-loader) so it shows before any code loads.
// The app fades it out once it knows who you are, and brings it back while leaving for Google or Stripe.
let hideTimer;

export function hideLoader() {
  const el = document.getElementById("boot-loader");
  if (!el) return;
  el.classList.add("done");
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => { el.style.display = "none"; }, 400);
}

export function showLoader() {
  const el = document.getElementById("boot-loader");
  if (!el) return;
  clearTimeout(hideTimer);
  el.style.display = "";
  el.classList.remove("done");
}

// Coming back with the browser's Back button (from Google or Stripe) restores this page as it was: hide the loader again.
window.addEventListener("pageshow", (e) => { if (e.persisted) hideLoader(); });
