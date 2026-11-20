# TimeFrame Chrome extension

A toolbar popup that shows the best times you (or one of your groups) are free this week.

- **Best times this week:** the top 5 free slots, best one crowned, each with a **Copy** button for pasting into a message.
- **Group picker:** "Just me" or any of your groups, plus **Copy group link**.
- **Open ↗** opens the full app at https://www.timeframecalender.com.

## Sign-in

There is no separate login. Sign in on timeframecalender.com once and the extension picks it up
(`content.js` runs only on that site and reads only the sign-in token, your name and your settings).
It renews its own sign-in the same way the site does ("Keep me signed in": 90 days, renewed while used).
Signing out on the site signs the extension out too; **Sign out** in the popup signs out only the extension.

## Install (on your own PC)

1. Open `chrome://extensions` in Chrome.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `extension` folder.
4. Pin TimeFrame from the puzzle-piece menu, then open www.timeframecalender.com once while signed in.

## Publishing to the Chrome Web Store (later)

Needs a Chrome Web Store developer account (one-time US$5). Zip the contents of this folder (not the folder itself),
upload it in the developer dashboard, and fill in the listing and privacy answers: it stores only a TimeFrame
sign-in token and the selected group on the device, and talks only to the TimeFrame API.

## Files

| File | What it does |
|---|---|
| `manifest.json` | Manifest V3; permissions: `storage` + the TimeFrame API host only |
| `content.js` | Shares the website's sign-in with the extension |
| `popup.html` / `popup.css` / `popup.js` | The popup |
| `icons/` | Toolbar and store icons |
