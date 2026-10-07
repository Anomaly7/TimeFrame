// Where the API lives. Set VITE_API_URL in Vercel (or a local .env) to point
// the frontend at a different backend without editing code.
export const API_URL = (import.meta.env.VITE_API_URL || "https://calender-app-mm4q.onrender.com").replace(/\/$/, "");
