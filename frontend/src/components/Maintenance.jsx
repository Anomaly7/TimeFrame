import { useCallback, useEffect, useRef, useState } from "react";
import "../App.css";
import { hideLoader } from "../loading";
import { fetchStatus } from "../maintenance";

const CHECK_EVERY = 30; // seconds

const timeText = (t) => {
  const d = new Date(t * 1000);
  const sameDay = d.toDateString() === new Date().toDateString();
  return d.toLocaleString(undefined, sameDay
    ? { hour: "numeric", minute: "2-digit" }
    : { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};

// Shown instead of the app while the owner has TimeFrame switched off for maintenance (admin page).
// Same look as the sign-in page. It checks every 30 seconds and reloads into the app once it's back.
export default function Maintenance({ status }) {
  const [info, setInfo] = useState(status);
  const [checking, setChecking] = useState(false);
  const [left, setLeft] = useState(CHECK_EVERY);
  const [now, setNow] = useState(() => Date.now());
  const busy = useRef(false);
  const secondsLeft = useRef(CHECK_EVERY);

  useEffect(() => { hideLoader(); }, []);

  const check = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setChecking(true);
    const s = await fetchStatus();
    if (s && !s.maintenance) { window.location.reload(); return; }
    if (s) setInfo(s);
    busy.current = false;
    setChecking(false);
    secondsLeft.current = CHECK_EVERY;
    setLeft(CHECK_EVERY);
  }, []);

  // One ticking clock: counts down to the next automatic check and keeps "expected back" current.
  useEffect(() => {
    const t = setInterval(() => {
      setNow(Date.now());
      if (busy.current) return;
      secondsLeft.current = secondsLeft.current <= 1 ? CHECK_EVERY : secondsLeft.current - 1;
      setLeft(secondsLeft.current);
      if (secondsLeft.current === CHECK_EVERY) check();
    }, 1000);
    return () => clearInterval(t);
  }, [check]);

  const until = info?.until && info.until * 1000 > now ? info.until : null;

  return (
    <div className="auth-shell mt-shell">
      <aside className="auth-hero" aria-hidden="true">
        <div className="auth-logo auth-logo-light">
          <img src="/favicon.svg" alt="" />
          <span>TimeFrame</span>
        </div>
        <div className="hero-copy">
          <h2>Back in a moment.</h2>
        </div>
        {/* The usual week preview, being rebuilt: blocks shimmer while a progress card sits on top. */}
        <div className="hero-preview mt-preview">
          <div className="hp-head">
            <span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span>
          </div>
          <div className="hp-grid">
            <i className="hp-b p0 mt-shim" style={{ gridColumn: 1, gridRow: "1 / 3" }} />
            <i className="hp-b p1 mt-shim" style={{ gridColumn: 1, gridRow: "4 / 6", animationDelay: ".3s" }} />
            <i className="hp-b p2 mt-shim" style={{ gridColumn: 2, gridRow: "2 / 4", animationDelay: ".6s" }} />
            <i className="hp-b p0 mt-shim" style={{ gridColumn: 2, gridRow: "5 / 7", animationDelay: ".9s" }} />
            <i className="hp-b p1 mt-shim" style={{ gridColumn: 3, gridRow: "1 / 2", animationDelay: "1.2s" }} />
            <i className="hp-b p2 mt-shim" style={{ gridColumn: 3, gridRow: "3 / 5", animationDelay: ".15s" }} />
            <i className="hp-b p0 mt-shim" style={{ gridColumn: 4, gridRow: "1 / 2", animationDelay: ".45s" }} />
            <i className="hp-b p2 mt-shim" style={{ gridColumn: 4, gridRow: "6 / 7", animationDelay: ".75s" }} />
            <i className="hp-b p1 mt-shim" style={{ gridColumn: 5, gridRow: "2 / 4", animationDelay: "1.05s" }} />
            <i className="hp-b p0 mt-shim" style={{ gridColumn: 5, gridRow: "5 / 6", animationDelay: "1.35s" }} />
          </div>
          <div className="mt-card">
            <span className="mt-gear">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
              </svg>
            </span>
            <div>
              <b>Upgrading TimeFrame</b>
              <div className="mt-bar"><span /></div>
            </div>
          </div>
        </div>
      </aside>

      <div className="auth-side">
        <main className="auth-panel" role="status" aria-live="polite">
          <div className="auth-logo auth-logo-mobile">
            <img src="/favicon.svg" alt="" />
            <span>TimeFrame</span>
          </div>
          <span className="mt-badge"><i />Scheduled maintenance</span>
          <h1 className="auth-title">We're tuning up TimeFrame</h1>
          <p className="auth-sub">
            {info?.message || "TimeFrame is down for a short upgrade. We'll be back shortly."}
          </p>

          <ul className="mt-facts">
            {until && (
              <li>
                <span className="mt-ico">⏱</span>
                <div><b>Expected back</b><small>around {timeText(until)}</small></div>
              </li>
            )}
            <li>
              <span className="mt-ico">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" />
                </svg>
              </span>
              <div><b>Your data is safe</b><small>Calendars, groups and settings are untouched.</small></div>
            </li>
            <li>
              <span className="mt-ico">↻</span>
              <div><b>No need to refresh</b><small>This page opens TimeFrame by itself when it's back.</small></div>
            </li>
          </ul>

          <button type="button" className="mt-btn" onClick={check} disabled={checking}>
            {checking ? "Checking…" : "Check again"}
          </button>
          <p className="auth-legal mt-next">
            {checking ? "Checking now…" : `Checking again automatically in ${left}s.`}
          </p>
        </main>

        <footer className="auth-footer">
          <span>© {new Date().getFullYear()} TimeFrame</span>
          <nav>
            <a href="/privacy.html">Privacy</a>
            <a href="/terms.html">Terms</a>
            <a href="mailto:sam.esebor@gmail.com">Contact</a>
          </nav>
        </footer>
      </div>
    </div>
  );
}
