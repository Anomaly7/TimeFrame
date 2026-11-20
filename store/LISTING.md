# Chrome Web Store listing: TimeFrame (copy-paste sheet)

Upload: `store/timeframe-extension-0.1.4.zip` (Developer Dashboard → New item).

## Store listing tab

**Name** (from the manifest): TimeFrame — Find Free Time

**Summary** (132 chars max, from the manifest):
See the best times your group is free this week, right from your toolbar.

**Description:**
TimeFrame finds a time that works for everyone. This extension puts your group's best free times one click away.

• A mini week calendar: everyone's busy times in their own colour, with the best free slots highlighted in green and the top one crowned
• Copy any time straight into a message, chat or email
• Switch between "Just me" and any of your TimeFrame groups
• Copy your group's invite link to add someone new
• Open the full calendar at timeframecalender.com in one click

How it works: sign in at timeframecalender.com (Google, Apple Calendar, Notion or email) and the extension signs in with you. TimeFrame only ever looks at when you're busy, never what your events are.

Free to install. The toolbar calendar is part of TimeFrame Pro (7-day free trial, or free with a coupon). No ads. No tracking.

**Category:** Productivity (Workflow & Planning)
**Language:** English

**Graphics:**
- Store icon 128×128: `extension/icons/icon-128.png`
- Screenshot (1280×800): `store/screenshot-1280x800.png`
- Small promo tile (440×280): `store/promo-tile-440x280.png`

**Website / homepage URL:** https://www.timeframecalender.com
**Support URL:** mailto:sam.esebor@gmail.com (or leave blank)

## Privacy practices tab

**Single purpose:**
Shows the user's best free meeting times from their TimeFrame account (and their TimeFrame groups) in a toolbar popup.

**Permission justifications:**
- `storage`: Keeps the user's TimeFrame sign-in token, display settings and selected group on the device so the popup stays signed in between uses.
- Host permission `https://calender-app-mm4q.onrender.com/*`: The TimeFrame API, which the popup calls to load the user's free times, groups and name.
- Content script on `timeframecalender.com`: Reads only the TimeFrame sign-in token and display settings from TimeFrame's own website, so the extension signs in when the user signs in on the site. It runs on no other site.

**Remote code:** No, I am not using remote code.

**Data usage (tick these):**
- [x] Personally identifiable information (the user's name and email are shown in the popup from their TimeFrame account)
- [x] Authentication information (TimeFrame sign-in token)
- Everything else: unticked (no health, financial, location, web history, user activity, or website content).

**Certify all three:**
- [x] I do not sell or transfer user data to third parties, outside of the approved use cases
- [x] I do not use or transfer user data for purposes that are unrelated to my item's single purpose
- [x] I do not use or transfer user data to determine creditworthiness or for lending purposes

**Privacy policy URL:** https://www.timeframecalender.com/privacy.html (has a "TimeFrame Chrome extension" section)

## Distribution tab
- Visibility: **Public** (or **Unlisted** to test with a link first)
- Regions: All regions
- Pricing: Free

Then **Submit for review**. Review usually takes a few days; Google emails the result.
