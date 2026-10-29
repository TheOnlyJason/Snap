import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import snap_unfollowers as su  # noqa: E402

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample")
SAMPLE = os.path.join(SAMPLE_DIR, "friends.sample.json")
SAMPLE_HTML = os.path.join(SAMPLE_DIR, "friends.sample.html")


def person(username, display="", added="2020-01-01 00:00:00 UTC", source="ADDED_BY_USERNAME"):
    return {"Username": username, "Display Name": display, "Creation Timestamp": added,
            "Last Modified Timestamp": added, "Source": source}


class ParsingTests(unittest.TestCase):
    def setUp(self):
        with open(SAMPLE, encoding="utf-8") as fh:
            self.data = json.load(fh)

    def test_sample_not_following_back_sorted_oldest_first(self):
        names = [p.username for p in su.find_not_following_back(self.data)]
        self.assertEqual(names, ["old_classmate", "party_guy_2021", "travel.influencer"])

    def test_sample_pending(self):
        names = [p.username for p in su.find_not_added_back_by_me(self.data)]
        self.assertEqual(names, ["random_adder_99"])

    def test_summary_counts(self):
        s = su.summary(self.data)
        self.assertEqual(s["mutual_friends"], 2)
        self.assertEqual(s["not_following_back"], 3)
        self.assertEqual(s["not_added_back_by_me"], 1)

    def test_mutual_and_blocked_are_excluded_and_duplicates_collapsed(self):
        data = {
            "Friends": [person("mutual_pal")],
            "Blocked Users": [person("creep")],
            "Friend Requests Sent": [
                person("mutual_pal"), person("creep"), person("Ghost"), person("ghost"), person("someone"),
            ],
        }
        names = [p.username for p in su.find_not_following_back(data)]
        self.assertEqual(sorted(n.lower() for n in names), ["ghost", "someone"])

    def test_missing_sections_and_odd_casing_are_tolerated(self):
        data = {"friend requests sent": [{"username": "lowercase_keys", "display name": "LC",
                                          "creation timestamp": "2022-02-02 02:02:02 UTC"}]}
        people = su.find_not_following_back(data)
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0].display_name, "LC")
        self.assertEqual(people[0].added_date, "2022-02-02")
        self.assertEqual(su.find_not_added_back_by_me(data), [])

    def test_rows_without_username_are_skipped(self):
        data = {"Friend Requests Sent": [{"Display Name": "nobody"}, "garbage", person("real_one")]}
        self.assertEqual([p.username for p in su.find_not_following_back(data)], ["real_one"])

    def test_unknown_dates_sort_last(self):
        data = {"Friend Requests Sent": [person("nodate", added=""), person("b", added="2021-01-01 00:00:00 UTC"),
                                         person("a", added="2021-01-01 00:00:00 UTC")]}
        self.assertEqual([p.username for p in su.find_not_following_back(data)], ["a", "b", "nodate"])

    def test_parse_timestamp_variants(self):
        self.assertEqual(su.parse_timestamp("2021-05-14 18:22:33 UTC").year, 2021)
        self.assertEqual(su.parse_timestamp("2021-05-14").day, 14)
        self.assertIsNone(su.parse_timestamp("not a date"))
        self.assertIsNone(su.parse_timestamp(""))


class LoadingTests(unittest.TestCase):
    def test_load_plain_file(self):
        data = su.load_friends_data(SAMPLE)
        self.assertIn("Friends", data)

    def test_load_from_folder_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            export_dir = os.path.join(tmp, "mydata~123", "json")
            os.makedirs(export_dir)
            with open(SAMPLE, "rb") as src, open(os.path.join(export_dir, "friends.json"), "wb") as dst:
                dst.write(src.read())
            self.assertEqual(su.summary(su.load_friends_data(os.path.join(tmp, "mydata~123")))["not_following_back"], 3)

            zip_path = os.path.join(tmp, "mydata~123.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(os.path.join(export_dir, "friends.json"), "json/friends.json")
                zf.writestr("json/account.json", "{}")
            self.assertEqual(su.summary(su.load_friends_data(zip_path))["not_following_back"], 3)

    def test_zip_without_friends_json_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "x.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("json/account.json", "{}")
            with self.assertRaises(FileNotFoundError):
                su.load_friends_data(zip_path)

    def test_html_without_tables_gives_helpful_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "friends.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("<html><body><h2>Friends</h2><p>nothing here</p></body></html>")
            with self.assertRaises(ValueError) as ctx:
                su.load_friends_data(path)
            self.assertIn("friends.html", str(ctx.exception))

    def test_garbage_file_gives_helpful_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "friends.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("hello there")
            with self.assertRaises(ValueError):
                su.load_friends_data(path)


class HtmlExportTests(unittest.TestCase):
    def test_html_matches_json_sample(self):
        html_data = su.load_friends_data(SAMPLE_HTML)
        self.assertEqual(set(html_data), {"Friends", "Friend Requests Sent", "Blocked Users", "Deleted Friends"})
        people = su.find_not_following_back(html_data)
        self.assertEqual([p.username for p in people], ["old_classmate", "party_guy_2021", "travel.influencer"])
        self.assertEqual(people[0].display_name, "Jess & co")      # entity decoded
        self.assertEqual(people[0].source, "added by phone")
        self.assertEqual(su.summary(html_data)["mutual_friends"], 2)
        self.assertEqual(html_data["Deleted Friends"], [])

    def test_blocked_excluded_from_html(self):
        data = su.parse_friends_html("""<h2>Friend Requests Sent</h2><table><tr><th>Username</th><th>Display Name</th></tr>
            <tr><td>creep</td><td></td></tr><tr><td>fine</td><td>F</td></tr></table>
            <h2>Blocked Users</h2><table><tr><th>Username</th></tr><tr><td>creep</td></tr></table>""")
        self.assertEqual([p.username for p in su.find_not_following_back(data)], ["fine"])

    def test_html_zip_and_folder_and_json_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_dir = os.path.join(tmp, "mydata~1", "html")
            os.makedirs(html_dir)
            with open(SAMPLE_HTML, "rb") as src, open(os.path.join(html_dir, "friends.html"), "wb") as dst:
                dst.write(src.read())
            self.assertEqual(su.summary(su.load_friends_data(os.path.join(tmp, "mydata~1")))["not_following_back"], 3)

            zip_path = os.path.join(tmp, "mydata~1.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(os.path.join(html_dir, "friends.html"), "html/friends.html")
                zf.writestr("index.html", "<html><body>index</body></html>")
            self.assertEqual(su.summary(su.load_friends_data(zip_path))["not_following_back"], 3)

            # When both formats are present, JSON is used.
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(os.path.join(html_dir, "friends.html"), "html/friends.html")
                zf.writestr("json/friends.json", json.dumps({"Friend Requests Sent": [person("only_in_json")]}))
            self.assertEqual([p.username for p in su.find_not_following_back(su.load_friends_data(zip_path))], ["only_in_json"])

    def test_missing_path(self):
        with self.assertRaises(FileNotFoundError):
            su.load_friends_data("/definitely/not/here.json")


class RenderAndCliTests(unittest.TestCase):
    def setUp(self):
        with open(SAMPLE, encoding="utf-8") as fh:
            self.people = su.find_not_following_back(json.load(fh))

    def test_csv(self):
        lines = su.render(self.people, "csv").splitlines()
        self.assertEqual(lines[0], "username,display_name,added,source")
        self.assertEqual(len(lines), 4)

    def test_json_roundtrip(self):
        rows = json.loads(su.render(self.people, "json"))
        self.assertEqual(rows[0]["username"], "old_classmate")

    def test_checklist_has_tickboxes(self):
        text = su.render(self.people, "checklist", "Remove")
        self.assertIn("- [ ] old_classmate (Jess) - added 2018-11-30", text)
        self.assertIn("- [ ] travel.influencer - added 2023-01-15", text)

    def test_usernames(self):
        self.assertEqual(su.render(self.people, "usernames"), "old_classmate\nparty_guy_2021\ntravel.influencer\n")

    def test_empty_table(self):
        self.assertIn("(none)", su.render([], "table", "Nobody"))

    def test_cli_writes_file_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "remove.md")
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = su.main([SAMPLE, "--format", "checklist", "--out", out_path])
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("not added back (remove): 3", stderr.getvalue())
            with open(out_path, encoding="utf-8") as fh:
                self.assertIn("- [ ] party_guy_2021", fh.read())

    def test_cli_pending_csv_labels_both_lists(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = su.main([SAMPLE, "-f", "csv", "--pending", "-q"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("# Added by you, but they have NOT added you back", text)
        self.assertIn("random_adder_99", text)
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_bad_path_returns_2(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = su.main(["/nope/friends.json"])
        self.assertEqual(code, 2)
        self.assertIn("error:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
