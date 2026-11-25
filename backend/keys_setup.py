"""Makes the server keys for TimeFrame's optional features. Run it yourself in a terminal:

    python keys_setup.py

It prints (only on your screen, never saved anywhere) values to paste into Render > Calender-App > Environment:
  GOOGLE_TOKEN_KEY  - turns on Google auto-sync. TimeFrame then keeps each person's Google refresh token,
                      encrypted with this key. Losing or changing it just means people reconnect Google once.
  VAPID_PRIVATE_KEY - turns on push notifications (phones/browsers). Changing it means people turn
                      notifications on again.
Don't paste these into any chat (including Jarvis). Close this window when done.
"""
import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec

print()
print("GOOGLE_TOKEN_KEY  =", Fernet.generate_key().decode())
raw = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value.to_bytes(32, "big")
print("VAPID_PRIVATE_KEY =", base64.urlsafe_b64encode(raw).decode().rstrip("="))
print()
print("Paste the ones you want into Render > Environment, save, and let it redeploy. Don't paste them into any chat.")
