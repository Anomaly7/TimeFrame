import { useState } from "react";
import { API_URL } from "../config";
import AppleConnect from "./AppleConnect";
import EmailAuth from "./EmailAuth";
import { rememberMe, setRememberMe } from "../session";

// The sign-in page: one full-width button per way in (Google, Apple Calendar, Notion when it's set up, email).
// Google and Notion go straight to their own sign-in; Apple and email open their small form in place.

const GoogleIcon = () => (
  <svg viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
    <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
    <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
    <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
  </svg>
);
const AppleIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path fill="currentColor" d="M16.37 12.62c-.03-2.6 2.13-3.86 2.22-3.92-1.21-1.77-3.09-2.01-3.76-2.04-1.6-.16-3.12.94-3.93.94-.81 0-2.06-.92-3.39-.89-1.74.03-3.35 1.01-4.25 2.57-1.81 3.14-.46 7.79 1.3 10.34.86 1.25 1.89 2.65 3.24 2.6 1.3-.05 1.79-.84 3.36-.84s2.01.84 3.38.81c1.4-.02 2.29-1.27 3.14-2.53.99-1.45 1.4-2.86 1.42-2.93-.03-.01-2.72-1.04-2.75-4.12zM13.79 5.01c.72-.87 1.2-2.07 1.07-3.27-1.03.04-2.28.69-3.02 1.55-.66.77-1.24 2-1.09 3.18 1.15.09 2.32-.58 3.04-1.46z" />
  </svg>
);
const NotionIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <rect x="3" y="3" width="18" height="18" rx="3" fill="none" stroke="currentColor" strokeWidth="2" />
    <path fill="currentColor" d="M8.2 7.5h1.7l4.4 6.3V7.5h1.5v9h-1.6L9.7 10.2v6.3H8.2z" />
  </svg>
);
const MailIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
    <path d="M4 7l8 6 8-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
  </svg>
);

export default function SignInOptions({ notionAvailable, onAuthenticated }) {
  const [open, setOpen] = useState(null); // null | "apple" | "email"
  const [remember, setRemember] = useState(rememberMe);
  const toggleRemember = (e) => { setRemember(e.target.checked); setRememberMe(e.target.checked); };
  const rememberBox = (
    <label className="remember-me">
      <input type="checkbox" checked={remember} onChange={toggleRemember} />
      <span>Keep me signed in</span>
    </label>
  );

  if (open) {
    return (
      <div className="provider-form">
        <button type="button" className="link-back" onClick={() => setOpen(null)}>← All sign-in options</button>
        {open === "apple"
          ? <AppleConnect signedIn={false} bare onAuthenticated={onAuthenticated} onCancel={() => setOpen(null)} />
          : <EmailAuth onAuthenticated={onAuthenticated} />}
        {rememberBox}
      </div>
    );
  }

  return (
    <div className="provider-list">
      <button type="button" className="provider-btn" onClick={() => { window.location.href = `${API_URL}/auth/login`; }}>
        <GoogleIcon /><span>Continue with Google</span>
      </button>
      <button type="button" className="provider-btn" onClick={() => setOpen("apple")}>
        <AppleIcon /><span>Continue with Apple Calendar</span>
      </button>
      {notionAvailable && (
        <button type="button" className="provider-btn" onClick={() => { window.location.href = `${API_URL}/notion/login`; }}>
          <NotionIcon /><span>Continue with Notion</span>
        </button>
      )}
      <button type="button" className="provider-btn" onClick={() => setOpen("email")}>
        <MailIcon /><span>Continue with email</span>
      </button>
      {rememberBox}
    </div>
  );
}
