#!/usr/bin/env python3
"""
snap_unfollowers.py - find the Snapchat friends who haven't added you back.

Snapchat has no public API for friend lists, so this works from the official
"Download My Data" export (accounts.snapchat.com -> My Data), specifically the
``friends.json`` (JSON export) or ``friends.html`` (HTML export) file inside
it.  Point the script at that file, at the unzipped export folder, or at the
downloaded ``.zip`` itself.

Typical use::

    python snap_unfollowers.py mydata~1700000000.zip
    python snap_unfollowers.py json/friends.json --format checklist --out remove.md
    python snap_unfollowers.py json/friends.json --format csv > not_following_back.csv

The script never contacts Snapchat and never removes anyone for you: removing
friends is done in the app (Profile -> My Friends -> name -> Manage Friendship
-> Remove Friend).  Automating that would break Snapchat's terms and risk your
account being locked.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import zipfile
from html.parser import HTMLParser
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

__version__ = "1.0.0"

# Section names as they appear in Snapchat's friends.json (compared lower-cased).
SECTION_FRIENDS = "friends"                    # mutual: you added them, they added you
SECTION_SENT = "friend requests sent"          # you added them, they have NOT added you back
SECTION_PENDING = "pending requests"           # they added you, you have NOT added them back
SECTION_DELETED = "deleted friends"
SECTION_BLOCKED = "blocked users"
SECTION_IGNORED = "ignored snapchatters"

FORMATS = ("table", "csv", "json", "checklist", "usernames")
FRIENDS_FILES = ("friends.json", "friends.html")


@dataclass(frozen=True)
class Person:
    username: str
    display_name: str
    added: str          # raw timestamp string from the export, e.g. "2021-05-14 18:22:33 UTC"
    source: str         # how the friendship was made, e.g. "ADDED_BY_USERNAME"

    @property
    def added_date(self) -> str:
        """Just the YYYY-MM-DD part of the timestamp (or the raw value if unparseable)."""
        dt = parse_timestamp(self.added)
        return dt.strftime("%Y-%m-%d") if dt else self.added


# --------------------------------------------------------------------------- loading

def load_friends_data(path: str) -> Dict[str, Any]:
    """Load the friends list from a file path, an extracted export folder, or the export .zip.

    Accepts ``friends.json`` (JSON export) or ``friends.html`` (HTML export); the
    result always has the JSON export's shape (section name -> list of rows).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"No such file or folder: {path}")

    if os.path.isdir(path):
        found = _find_in_dir(path, FRIENDS_FILES)
        if not found:
            raise FileNotFoundError(
                f"Could not find friends.json or friends.html anywhere under {path}. "
                "Make sure you ticked 'Friends' when requesting the export."
            )
        with open(found, "rb") as fh:
            return _parse_bytes(fh.read(), found)

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            candidates = [n for n in zf.namelist() if os.path.basename(n).lower() in FRIENDS_FILES]
            if not candidates:
                raise FileNotFoundError(
                    f"{path} does not contain a friends.json or friends.html. "
                    "Make sure you ticked 'Friends' when requesting the export."
                )
            # Prefer JSON over HTML, then the conventional json/friends.json location.
            candidates.sort(key=lambda n: (not n.lower().endswith(".json"), not n.lower().endswith("json/friends.json"), len(n)))
            with zf.open(candidates[0]) as fh:
                return _parse_bytes(fh.read(), f"{path}:{candidates[0]}")

    with open(path, "rb") as fh:
        return _parse_bytes(fh.read(), path)


def _find_in_dir(root: str, filenames: Iterable[str]) -> Optional[str]:
    wanted = tuple(f.lower() for f in filenames)
    best: Optional[str] = None
    for dirpath, _dirnames, names in os.walk(root):
        for name in names:
            if name.lower() in wanted:
                candidate = os.path.join(dirpath, name)
                # JSON wins over HTML when both are present.
                if best is None or (best.lower().endswith(".html") and candidate.lower().endswith(".json")):
                    best = candidate
    return best


def _parse_bytes(raw: bytes, origin: str) -> Dict[str, Any]:
    text = raw.decode("utf-8-sig", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json(text, origin)
    if stripped[:200].lower().lstrip().startswith(("<!doctype", "<html")) or "<table" in text.lower():
        return parse_friends_html(text, origin)
    # Not obviously either; let the JSON parser produce the error message.
    return _parse_json(text, origin)


def _parse_json(text: str, origin: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{origin} is not valid JSON ({exc}). Expected Snapchat's friends.json or friends.html."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{origin} does not look like a Snapchat friends.json (expected an object at the top level).")
    return data


class _FriendsHTMLParser(HTMLParser):
    """Turns Snapchat's friends.html (a heading followed by a table per section) into
    the same ``{section: [row, ...]}`` structure as friends.json."""

    HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: Dict[str, List[Dict[str, str]]] = {}
        self._heading_tag: Optional[str] = None
        self._heading_text: List[str] = []
        self._last_heading = ""
        self._in_table = False
        self._section = ""
        self._headers: List[str] = []
        self._row: List[str] = []
        self._cell: Optional[List[str]] = None
        self._cell_is_header = False
        self._row_has_header_cells = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.HEADINGS:
            self._heading_tag, self._heading_text = tag, []
        elif tag == "table":
            self._in_table, self._section, self._headers = True, self._last_heading, []
            self.sections.setdefault(self._section, [])
        elif self._in_table and tag == "tr":
            self._row, self._row_has_header_cells = [], False
        elif self._in_table and tag in ("td", "th"):
            self._cell, self._cell_is_header = [], tag == "th"
            self._row_has_header_cells = self._row_has_header_cells or tag == "th"
        elif self._in_table and tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag:
            self._last_heading = " ".join("".join(self._heading_text).split())
            self._heading_tag = None
        elif self._in_table and tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self._in_table and tag == "tr":
            if self._row_has_header_cells and not self._headers:
                self._headers = self._row
            elif self._row and self._headers and any(self._row):
                row = {h: v for h, v in zip(self._headers, self._row) if h}
                self.sections[self._section].append(row)
            self._row = []
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._heading_tag is not None:
            self._heading_text.append(data)
        elif self._cell is not None:
            self._cell.append(data)


def parse_friends_html(text: str, origin: str = "friends.html") -> Dict[str, Any]:
    """Parse the HTML export's friends page into the friends.json structure."""
    parser = _FriendsHTMLParser()
    parser.feed(text)
    parser.close()
    sections = {name: rows for name, rows in parser.sections.items() if name}
    if not sections:
        raise ValueError(f"{origin} contains no friend tables. Expected Snapchat's friends.html.")
    return sections


# --------------------------------------------------------------------------- parsing

def _lower_keys(d: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).strip().lower(): v for k, v in d.items()}


def _get(entry: Dict[str, Any], *names: str) -> str:
    """Return the first matching field (case/space-insensitive) as a stripped string."""
    low = _lower_keys(entry)
    for name in names:
        value = low.get(name.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def people_in(data: Dict[str, Any], section: str) -> List[Person]:
    """Return the people listed under one section of friends.json (empty list if absent)."""
    rows = _lower_keys(data).get(section.lower())
    if not isinstance(rows, list):
        return []
    people: List[Person] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        username = _get(row, "Username", "User Name", "user_name")
        if not username:
            continue
        people.append(
            Person(
                username=username,
                display_name=_get(row, "Display Name", "DisplayName", "display_name", "Name"),
                added=_get(row, "Creation Timestamp", "Created", "Timestamp", "Date"),
                source=_get(row, "Source"),
            )
        )
    return people


def _usernames(people: Iterable[Person]) -> set:
    return {p.username.lower() for p in people}


def find_not_following_back(data: Dict[str, Any]) -> List[Person]:
    """People you added who have not added you back ("Friend Requests Sent").

    Anyone who also appears as a mutual friend, or whom you have blocked, is left out.
    Duplicates are collapsed on username (case-insensitive).
    """
    mutual = _usernames(people_in(data, SECTION_FRIENDS))
    blocked = _usernames(people_in(data, SECTION_BLOCKED))
    seen: set = set()
    result: List[Person] = []
    for person in people_in(data, SECTION_SENT):
        key = person.username.lower()
        if key in seen or key in mutual or key in blocked:
            continue
        seen.add(key)
        result.append(person)
    return sort_people(result)


def find_not_added_back_by_me(data: Dict[str, Any]) -> List[Person]:
    """People who added you but whom you have not added back ("Pending Requests")."""
    mutual = _usernames(people_in(data, SECTION_FRIENDS))
    blocked = _usernames(people_in(data, SECTION_BLOCKED))
    ignored = _usernames(people_in(data, SECTION_IGNORED))
    seen: set = set()
    result: List[Person] = []
    for person in people_in(data, SECTION_PENDING):
        key = person.username.lower()
        if key in seen or key in mutual or key in blocked or key in ignored:
            continue
        seen.add(key)
        result.append(person)
    return sort_people(result)


def summary(data: Dict[str, Any]) -> Dict[str, int]:
    return {
        "mutual_friends": len(people_in(data, SECTION_FRIENDS)),
        "not_following_back": len(find_not_following_back(data)),
        "not_added_back_by_me": len(find_not_added_back_by_me(data)),
        "deleted_friends": len(people_in(data, SECTION_DELETED)),
        "blocked_users": len(people_in(data, SECTION_BLOCKED)),
    }


def parse_timestamp(value: str) -> Optional[datetime]:
    """Parse Snapchat's timestamp formats; returns None when it cannot."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def sort_people(people: Iterable[Person]) -> List[Person]:
    """Oldest add first (those are the stalest), unknown dates last, then by username."""
    def key(p: Person):
        dt = parse_timestamp(p.added)
        return (dt is None, dt or datetime.max, p.username.lower())
    return sorted(people, key=key)


# --------------------------------------------------------------------------- output

def render(people: List[Person], fmt: str, title: str = "") -> str:
    if fmt == "table":
        return _render_table(people, title)
    if fmt == "csv":
        return _render_csv(people)
    if fmt == "json":
        return json.dumps([asdict(p) for p in people], indent=2, ensure_ascii=False) + "\n"
    if fmt == "checklist":
        return _render_checklist(people, title)
    if fmt == "usernames":
        return "".join(p.username + "\n" for p in people)
    raise ValueError(f"Unknown format: {fmt}")


def _render_table(people: List[Person], title: str) -> str:
    out = io.StringIO()
    if title:
        out.write(title + "\n" + "=" * len(title) + "\n")
    if not people:
        out.write("(none)\n")
        return out.getvalue()
    width_user = max(len("Username"), *(len(p.username) for p in people))
    width_name = max(len("Display name"), *(len(p.display_name) for p in people))
    header = f"{'#':>4}  {'Username':<{width_user}}  {'Display name':<{width_name}}  Added"
    out.write(header + "\n" + "-" * len(header) + "\n")
    for i, p in enumerate(people, 1):
        out.write(f"{i:>4}  {p.username:<{width_user}}  {p.display_name:<{width_name}}  {p.added_date}\n")
    return out.getvalue()


def _render_csv(people: List[Person]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["username", "display_name", "added", "source"])
    for p in people:
        writer.writerow([p.username, p.display_name, p.added, p.source])
    return out.getvalue()


def _render_checklist(people: List[Person], title: str) -> str:
    out = io.StringIO()
    out.write(f"# {title or 'Snapchat friends to remove'}\n\n")
    out.write(f"{len(people)} people. In Snapchat: Profile -> My Friends -> tap the name -> "
              "(...) -> Manage Friendship -> Remove Friend. Tick each one off as you go.\n\n")
    for p in people:
        label = p.username if not p.display_name else f"{p.username} ({p.display_name})"
        out.write(f"- [ ] {label} - added {p.added_date}\n")
    return out.getvalue()


# --------------------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snap_unfollowers",
        description="List the Snapchat friends who haven't added you back, from your Snapchat data export.",
        epilog="Removal happens in the app: Profile -> My Friends -> tap the name -> (...) -> "
               "Manage Friendship -> Remove Friend.",
    )
    parser.add_argument("path", help="friends.json, the unzipped export folder, or the export .zip")
    parser.add_argument("--format", "-f", choices=FORMATS, default="table",
                        help="output format (default: table). 'checklist' is Markdown with tick boxes.")
    parser.add_argument("--out", "-o", help="write the list to this file instead of standard output")
    parser.add_argument("--pending", action="store_true",
                        help="also list the reverse: people who added you but you haven't added back")
    parser.add_argument("--quiet", "-q", action="store_true", help="don't print the summary")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load_friends_data(args.path)
    except (FileNotFoundError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    not_back = find_not_following_back(data)
    sections = [("Added by you, but they have NOT added you back", not_back)]
    if args.pending:
        sections.append(("Added you, but you have NOT added them back", find_not_added_back_by_me(data)))

    if args.format in ("csv", "json", "usernames") and args.pending:
        # Machine formats cannot carry two lists; label rows instead.
        chunks = []
        for title, people in sections:
            if args.format == "json":
                chunks.append(json.dumps({"title": title, "people": [asdict(p) for p in people]}, indent=2, ensure_ascii=False) + "\n")
            else:
                chunks.append(f"# {title}\n" + render(people, args.format))
        text = "".join(chunks)
    else:
        text = "\n".join(render(people, args.format, title) for title, people in sections)

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)

    if not args.quiet:
        s = summary(data)
        lines = [
            "",
            f"Mutual friends:                       {s['mutual_friends']}",
            f"Added by you, not added back (remove): {s['not_following_back']}",
            f"Added you, not added back by you:      {s['not_added_back_by_me']}",
        ]
        if args.out:
            lines.append(f"List written to {args.out}")
        lines.append("Export data is a snapshot: double-check in the app before removing (their Snap score "
                     "is hidden if they haven't added you back).")
        print("\n".join(lines), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
