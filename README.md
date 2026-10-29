# Snap Unfollowers

Find the people you added on Snapchat who never added you back, then remove them.

Snapchat has no public API for your friend list, and bots that drive the app get
accounts locked. So this tool works from the official **Download My Data** export:
it reads `friends.json` (JSON export) or `friends.html` (HTML export), lists everyone you
added who hasn't added you back, and gives you a checklist to work through in the app. Nothing is sent anywhere and nothing is
removed automatically.

Two ways to use it, pick one:

| | Browser page (`index.html`) | Command line (`snap_unfollowers.py`) |
|---|---|---|
| Needs | Any browser | Python 3.8+ |
| Input | `friends.json` / `friends.html` or the export `.zip` | `friends.json` / `friends.html`, the `.zip`, or the unzipped folder |
| Output | On-screen checklist with tick boxes, CSV, copy usernames | Table, CSV, JSON, Markdown checklist, plain usernames |

## 1. Download your Snapchat data

1. Sign in at [accounts.snapchat.com](https://accounts.snapchat.com) and open **My Data**.
2. Tick **Friends** (everything else can stay unticked) and submit. Either format works;
   JSON is slightly smaller.
3. Snapchat emails you a link to a file called `mydata~<numbers>.zip`. Download it.
   Inside is `json/friends.json` or `html/friends.html`, which is all this tool needs.

## 2a. Browser page

Open `index.html` in any browser (double-click it, or open it on your phone), then choose
or drop your `friends.json`, `friends.html` or the whole `.zip`. You get:

- The list of people who didn't add you back, oldest first.
- A second tab with the reverse list (people who added you but you never added back).
- A tick box per person that remembers your progress, a filter box, **Copy usernames** and
  **Download CSV**.

The file never leaves your device. Reading a `.zip` directly uses the JSZip library from
cdnjs, so for that you need to be online; a plain `friends.json` or `friends.html` works fully offline.

## 2b. Command line

```bash
# point it at the zip, the unzipped folder, or friends.json / friends.html itself
python3 snap_unfollowers.py ~/Downloads/mydata~1700000000.zip
python3 snap_unfollowers.py ~/Downloads/mydata~1700000000/html/friends.html

# a Markdown checklist you can tick off
python3 snap_unfollowers.py json/friends.json --format checklist --out remove.md

# spreadsheet
python3 snap_unfollowers.py json/friends.json --format csv > not_following_back.csv

# just usernames, one per line
python3 snap_unfollowers.py json/friends.json --format usernames

# also show people who added you but you haven't added back
python3 snap_unfollowers.py json/friends.json --pending
```

Example output:

```
Added by you, but they have NOT added you back
==============================================
   #  Username           Display name  Added
--------------------------------------------
   1  old_classmate      Jess          2018-11-30
   2  party_guy_2021     Mike          2021-07-04
   3  travel.influencer                2023-01-15

Mutual friends:                       2
Added by you, not added back (remove): 3
Added you, not added back by you:      1
```

No dependencies beyond the Python standard library. Try it on the bundled sample:
`python3 snap_unfollowers.py sample/friends.sample.json --pending`.

## 3. Remove them in Snapchat

There are two ways: by hand in the app, or with the Snapchat for Web helper in
[`web/`](web/README.md), which drives web.snapchat.com in a browser window on your own
computer, with your own login, and works through the list with human-like pacing. The
web helper is unverified against the live site (Snapchat only documents removal in the
mobile app), carries some account-lock risk if pushed too fast, and starts with a
discovery run; read `web/README.md` before using it.

By hand, for each username on the list:

1. Open Snapchat, tap your **profile** (top left), then **My Friends**.
2. Search the username and open their profile.
3. Tap **⋯** (top right) → **Manage Friendship** → **Remove Friend**.

Before removing, glance at their profile: if their **Snap Score is hidden**, they still
haven't added you back. If you can see a score, they added you after your export, so skip them.

## How the export maps to the lists

`friends.json` has several sections (`friends.html` has the same sections as headed tables,
and is converted to the same structure). This is how they are used:

| Section | Meaning | Used as |
|---|---|---|
| `Friends` | Both of you added each other | Mutual friends (excluded from both lists) |
| `Friend Requests Sent` | You added them, they haven't added you back | **The list to remove** |
| `Pending Requests` | They added you, you haven't added them back | Shown with `--pending` / the second tab (not present in every export) |
| `Blocked Users`, `Ignored Snapchatters` | People you blocked or ignored | Excluded |
| `Deleted Friends`, `Hidden Friend Suggestions`, `Shortcuts` | History and UI data | Ignored |

When someone who used to be your friend removes you, your side of the friendship becomes
a one-way add, so they show up under `Friend Requests Sent` in a fresh export too.

The export is a snapshot from the moment Snapchat generated it. Request a new one after a
round of removals to confirm the list is clean.

## Privacy

Your export contains personal data. `.gitignore` already excludes `friends.json`,
`friends.html`, `mydata*`, `*.zip` and the `json/` and `html/` export folders so they are never
committed to this repository by accident. Keep the export somewhere private and delete
it when you're done.

## Development

```bash
python3 -m unittest discover -s tests -v     # analyser
bash tests/test_web_unfriend.sh              # web helper, against tests/mock/snapweb.html (needs node + playwright)
```
