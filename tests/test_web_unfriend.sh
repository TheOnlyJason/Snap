#!/usr/bin/env bash
# End-to-end test of web/unfriend.js against the mock Snapchat for Web page.
# Needs node + playwright (the pre-installed one in CI/dev containers works).
set -euo pipefail
cd "$(dirname "$0")/.."
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
MOCK="file://$PWD/tests/mock/snapweb.html"
printf 'party_guy_2021\nold_classmate\ndoes_not_exist\ntravel.influencer\n' > "$TMP/list.txt"
COMMON=(--url "$MOCK" --headless --no-wait --profile "$TMP/profile" --progress "$TMP/progress.csv" --min-delay 50 --max-delay 100 --break-every 1000)

echo "== dry run on 2 =="
node web/unfriend.js --list "$TMP/list.txt" --limit 2 --dry-run "${COMMON[@]}" | tee "$TMP/out1.txt"
grep -q "party_guy_2021 ... dry-run" "$TMP/out1.txt"
grep -q "old_classmate ... dry-run" "$TMP/out1.txt"
[ "$(grep -c dry-run "$TMP/progress.csv")" = 2 ]

echo "== real run resumes past dry-run entries, handles a missing user =="
rm "$TMP/progress.csv"
node web/unfriend.js --list "$TMP/list.txt" --limit 10 "${COMMON[@]}" | tee "$TMP/out2.txt"
grep -q "party_guy_2021 ... removed" "$TMP/out2.txt"
grep -q "does_not_exist ... not-found" "$TMP/out2.txt"
grep -q "travel.influencer ... removed" "$TMP/out2.txt"
grep -q "3 removed, 1 not removed" "$TMP/out2.txt"

echo "== re-run skips everything already removed =="
node web/unfriend.js --list "$TMP/list.txt" --limit 10 "${COMMON[@]}" | tee "$TMP/out3.txt"
grep -q "3 already done, 1 to go" "$TMP/out3.txt"

echo "== csv input with display-name fallback =="
printf 'username,display_name,added,source\nnope_user,"party",2026-01-01,x\n' > "$TMP/list.csv"
node web/unfriend.js --list "$TMP/list.csv" --dry-run "${COMMON[@]}" --progress "$TMP/p2.csv" | tee "$TMP/out4.txt"
grep -q "nope_user ... dry-run" "$TMP/out4.txt"

echo "== discover mode writes captures =="
node web/unfriend.js --discover ghost_user "${COMMON[@]}" --profile "$TMP/profile2" > "$TMP/out5.txt" 2>&1
grep -q "status: 'not-found'" "$TMP/out5.txt"              # ghost_user never appears in search results
test "$(ls web/discover/*.png | wc -l)" -ge 2
test "$(ls web/discover/*.aria.txt | wc -l)" -ge 2
rm -rf web/discover
echo "ALL WEB TESTS PASSED"
