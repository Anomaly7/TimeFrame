"""Makes the two secrets the TimeFrame admin page needs. Run it yourself in a terminal:

    python admin_setup.py

It prints (only on your screen, never saved anywhere):
  1. ADMIN_PASSWORD     - a long random password. Save it in your password manager.
  2. ADMIN_TOTP_SECRET  - the key for your authenticator app (iPhone Passwords, Google Authenticator, 1Password...).
     Add it there as a new code with "enter setup key" / "enter code manually", type: time-based.
Then put both in Render > Calender-App > Environment (plus OWNER_NTFY_TOPIC for phone alerts) and save.
"""
import base64
import secrets
import urllib.parse

password = secrets.token_urlsafe(24)  # ~190 bits
totp = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")  # 160 bits, the standard size
uri = "otpauth://totp/" + urllib.parse.quote("TimeFrame admin") + "?" + urllib.parse.urlencode(
    {"secret": totp, "issuer": "TimeFrame", "digits": 6, "period": 30})

print()
print("ADMIN_PASSWORD    =", password)
print("ADMIN_TOTP_SECRET =", totp)
print()
print("Authenticator setup key (same as ADMIN_TOTP_SECRET, spaced for typing):")
print("   ", " ".join(totp[i:i + 4] for i in range(0, len(totp), 4)))
print()
print("Or paste this link into an authenticator that accepts otpauth links:")
print("   ", uri)
print()
print("Don't paste these into any chat (including Jarvis). Close this window when done.")
