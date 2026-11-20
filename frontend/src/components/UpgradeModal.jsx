import { useState } from "react";
import { API_URL } from "../config";
import { showLoader } from "../loading";

// TimeFrame Pro checkout (2026-11-20): pick monthly or yearly and go to Stripe, or enter a coupon
// (the coupon gives Pro for free right here, no card).

const FEATURES = [
  "Create groups and share invite links",
  "The TimeFrame Chrome extension",
  "Everything in Free: Google, Apple, Notion and .ics calendars",
];

export default function UpgradeModal({ status, authHeaders, onClose, onUpgraded, reason }) {
  const [period, setPeriod] = useState("year");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [coupon, setCoupon] = useState("");
  const [showCoupon, setShowCoupon] = useState(false);
  const [done, setDone] = useState("");

  const prices = status?.prices || { month: "$3.99", year: "$29" };
  const trialDays = status?.trial_days ?? 7;
  const monthly = parseFloat(String(prices.month).replace(/[^0-9.]/g, "")) || 3.99;
  const yearly = parseFloat(String(prices.year).replace(/[^0-9.]/g, "")) || 29;
  const save = Math.round((1 - yearly / (monthly * 12)) * 100);

  async function checkout() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ interval: period }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't start checkout.");
      showLoader();
      window.location.href = data.url;
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  async function redeem(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/billing/redeem`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ code: coupon }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(res.status === 429 ? "Too many tries. Wait a bit and try again." : data.detail || "That coupon code isn't valid.");
      setDone(data.still_paying
        ? "Coupon applied: Pro is now free for you. You still have a paid subscription, so cancel it under Manage billing."
        : "Coupon applied: TimeFrame Pro is yours, free.");
      onUpgraded?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal upgrade" role="dialog" aria-modal="true" aria-labelledby="upgrade-title" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        <div className="upgrade-head">
          <img src="/favicon.svg" alt="" />
          <div>
            <h2 id="upgrade-title">TimeFrame Pro</h2>
            <p>{reason || "Plan with your whole group."}</p>
          </div>
        </div>

        {done ? (
          <div className="upgrade-done">
            <p>🎉 {done}</p>
            <button className="btn btn-primary" onClick={onClose}>Start using Pro</button>
          </div>
        ) : (
          <>
            <ul className="upgrade-features">
              {FEATURES.map((f) => <li key={f}>{f}</li>)}
            </ul>

            <div className="plan-pick" role="radiogroup" aria-label="Billing period">
              <button role="radio" aria-checked={period === "month"} className={period === "month" ? "on" : ""} onClick={() => setPeriod("month")}>
                <span className="plan-name">Monthly</span>
                <span className="plan-price">{prices.month}<small>/month</small></span>
              </button>
              <button role="radio" aria-checked={period === "year"} className={period === "year" ? "on" : ""} onClick={() => setPeriod("year")}>
                <span className="plan-name">Yearly {save > 0 && <em>Save {save}%</em>}</span>
                <span className="plan-price">{prices.year}<small>/year</small></span>
              </button>
            </div>

            <button className="btn btn-primary upgrade-cta" onClick={checkout} disabled={busy || status?.checkout_available === false}>
              {trialDays > 0 ? `Start ${trialDays}-day free trial` : "Continue to checkout"}
            </button>
            <p className="upgrade-fine">
              {status?.checkout_available === false
                ? "Card payments are being set up. A coupon still works."
                : `${trialDays > 0 ? `Free for ${trialDays} days, then ` : ""}${period === "year" ? prices.year + " a year" : prices.month + " a month"} (${status?.currency || "CAD"})${status?.tax_added ? " + tax" : ""}. Cancel anytime. Secure checkout by Stripe.`}
            </p>

            <div className="coupon">
              {showCoupon ? (
                <form onSubmit={redeem}>
                  <input value={coupon} onChange={(e) => setCoupon(e.target.value)} placeholder="Coupon code" aria-label="Coupon code" autoFocus />
                  <button className="btn" type="submit" disabled={busy || !coupon.trim()}>Apply</button>
                </form>
              ) : (
                <button className="link-btn" onClick={() => setShowCoupon(true)}>Have a coupon?</button>
              )}
            </div>
          </>
        )}
        {error && <p className="error-text">{error}</p>}
      </div>
    </div>
  );
}
