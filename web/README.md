# Removing one-way friends through Snapchat for Web

`unfriend.js` drives Snapchat for Web (web.snapchat.com) in a real browser window on
**your own computer**, using your own login, and removes the people on your list one
by one with human-like pacing. It never sees your password: you log in yourself in the
window it opens, and that login is kept in `web/profile/` (git-ignored) for next time.

Read this first:

- **Unverified against the live site.** Snapchat's help pages only document friend
  removal in the mobile app; whether Snapchat for Web offers *Manage Friendship → Remove
  Friend* is reported inconsistently. The script looks for buttons by their visible
  names, so it can adapt, but the first run is a test. Start with `--discover`.
- **Account risk.** Snapchat's terms prohibit automation and it rate-limits unusual
  activity. The script waits 5–11 s between people, pauses 90 s every 25, stops after 3
  consecutive failures, and does at most 100 per run by default. Keep it that way, and
  spread 2,651 removals over days, not hours.
- **Removal is permanent.** `--dry-run` goes through every step except the final
  confirmation.

## Setup (once)

You need Node.js 18+ (nodejs.org). Then, in this repository folder:

```bash
cd web
npm install playwright
npx playwright install chromium
```

## 1. Discovery run

```bash
node web/unfriend.js --discover some_username_from_your_list
```

A browser window opens on web.snapchat.com. Log in and wait for your chats to appear.
From a terminal, press Enter to continue; when Claude runs the script for you, it notices
the login by itself (up to 15 minutes). The script tries the removal steps in dry-run
mode and writes a screenshot plus a text tree of the page at each step to
`web/discover/`. If it reports `Result: { status: 'dry-run', ... }` the selectors fit.
If it reports `Stopped at: could not find ...`, send the files in `web/discover/` back
to Claude so the selectors can be adjusted; that folder is git-ignored because the
screenshots show your account.

## 2. Dry run on a few

```bash
node web/unfriend.js --list ../usernames.txt --limit 5 --dry-run
```

Watch the window. It should find each person and reach the Remove Friend confirmation,
then cancel.

## 3. Real runs

```bash
node web/unfriend.js --list ../usernames.txt --limit 100
```

`--list` accepts the plain `usernames` output or the CSV from `snap_unfollowers.py`
(the CSV is better: the display name is used as a fallback search). Progress is kept in
`web/progress.csv`, so re-running continues where it left off; delete that file to start
over. After each session, request a fresh export and re-run `snap_unfollowers.py` to
confirm the list shrank.

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--list FILE` | | usernames.txt or CSV from the analyser |
| `--limit N` | 100 | people per run |
| `--dry-run` | off | stop before the final confirmation |
| `--discover USERNAME` | | capture screenshots and page tree for one person |
| `--min-delay MS` / `--max-delay MS` | 5000 / 11000 | pause between people |
| `--break-every N` / `--break-ms MS` | 25 / 90000 | longer pause every N people |
| `--max-failures N` | 3 | stop after N consecutive failures |
| `--login-timeout SECONDS` | 900 | when not run from a terminal, how long to wait for you to log in |
| `--profile DIR` | web/profile | where the browser login is kept |
| `--progress FILE` | web/progress.csv | progress log |
| `--url URL` | https://web.snapchat.com | page to open (used by the tests with a mock page) |
