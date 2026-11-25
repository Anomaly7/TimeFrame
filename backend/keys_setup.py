"""Makes the server keys for TimeFrame's optional features. Run it yourself in a terminal:

    python keys_setup.py

It prints (only on your screen, never saved anywhere) values to paste into Render > Calender-App > Environment:
  GOOGLE_TOKEN_KEY  - turns on Google auto-sync. TimeFrame then keeps each person's Google refresh token,
                      encrypted with this key. Losing or changing it just means people reconnect Google once.
Don't paste these into any chat (including Jarvis). Close this window when done.
"""
from cryptography.fernet import Fernet

print()
print("GOOGLE_TOKEN_KEY =", Fernet.generate_key().decode())
print()
print("Paste into Render > Environment, save, and let it redeploy. Don't paste it into any chat.")
