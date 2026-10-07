import { useState } from "react";
import { API_URL } from "../config";

export default function EmailAuth({ onAuthenticated }) {
  const [mode, setMode] = useState("signin"); // "signin" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const path = mode === "signup" ? "/auth/signup" : "/auth/login";

    try {
      const res = await fetch(`${API_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || "Something went wrong.");

      onAuthenticated(data.token, data.email);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  return (
    <form className="email-auth" onSubmit={submit}>
      <div className="email-auth-fields">
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={8}
          required
        />
        <button className="btn btn-primary" type="submit" disabled={loading}>
          {loading && <span className="spinner" />}
          {mode === "signup" ? "Create account" : "Sign in"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      <p className="email-auth-toggle">
        {mode === "signup" ? "Already have an account? " : "Don't have an account? "}
        <button
          type="button"
          className="link-btn"
          onClick={() => {
            setMode(mode === "signup" ? "signin" : "signup");
            setError("");
          }}
        >
          {mode === "signup" ? "Sign in" : "Sign up"}
        </button>
      </p>
    </form>
  );
}
