#!/usr/bin/env node
/*
 * unfriend.js - remove one-way Snapchat friends through Snapchat for Web.
 *
 * Runs ON YOUR OWN COMPUTER. It opens a real Chromium window on web.snapchat.com,
 * you log in once (the session is kept in web/profile/), then it works through a
 * list of usernames: find the person, open their profile/menu, Manage Friendship,
 * Remove Friend, confirm. It paces itself like a person and stops when things look
 * wrong, because hammering Snapchat gets accounts temporarily locked.
 *
 *   node web/unfriend.js --list usernames.txt                 # remove, 100 per run
 *   node web/unfriend.js --list not-following-back.csv --limit 25
 *   node web/unfriend.js --list usernames.txt --dry-run       # everything except the final confirm
 *   node web/unfriend.js --discover some_username             # capture screenshots + page tree for debugging
 *
 * Progress is written to web/progress.csv so re-running resumes where it left off.
 * See web/README.md for setup.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const readline = require('readline');

function parseArgs(argv) {
  const o = { list: null, limit: 100, dryRun: false, discover: null, url: 'https://web.snapchat.com',
    minDelay: 5000, maxDelay: 11000, breakEvery: 25, breakMs: 90000, headless: false, noWait: false,
    profile: path.join(__dirname, 'profile'), progress: path.join(__dirname, 'progress.csv'),
    outDir: path.join(__dirname, 'discover'), maxFailures: 3, loginTimeout: 15 * 60 * 1000 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], next = () => argv[++i];
    if (a === '--list') o.list = next();
    else if (a === '--limit') o.limit = parseInt(next(), 10);
    else if (a === '--dry-run') o.dryRun = true;
    else if (a === '--discover') o.discover = next();
    else if (a === '--url') o.url = next();
    else if (a === '--min-delay') o.minDelay = parseInt(next(), 10);
    else if (a === '--max-delay') o.maxDelay = parseInt(next(), 10);
    else if (a === '--break-every') o.breakEvery = parseInt(next(), 10);
    else if (a === '--break-ms') o.breakMs = parseInt(next(), 10);
    else if (a === '--max-failures') o.maxFailures = parseInt(next(), 10);
    else if (a === '--login-timeout') o.loginTimeout = parseInt(next(), 10) * 1000;
    else if (a === '--profile') o.profile = next();
    else if (a === '--progress') o.progress = next();
    else if (a === '--headless') o.headless = true;      // for automated tests only
    else if (a === '--no-wait') o.noWait = true;         // skip the "press Enter after login" prompt
    else if (a === '--help' || a === '-h') { console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0]); process.exit(0); }
    else throw new Error('Unknown argument: ' + a);
  }
  if (!o.list && !o.discover) throw new Error('Give --list <file> or --discover <username>. See --help.');
  return o;
}

// ---- input list -------------------------------------------------------------
function readList(file) {
  const text = fs.readFileSync(file, 'utf8').replace(/^﻿/, '');
  const lines = text.split(/\r?\n/).filter(l => l.trim() && !l.startsWith('#'));
  if (!lines.length) return [];
  if (/^username,/i.test(lines[0])) {                      // CSV from snap_unfollowers.py
    return lines.slice(1).map(parseCsvLine).filter(c => c[0]).map(c => ({ username: c[0], displayName: c[1] || '' }));
  }
  return lines.map(l => ({ username: l.trim(), displayName: '' }));
}
function parseCsvLine(line) {
  const out = []; let cur = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) { if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
    else if (ch === '"') q = true; else if (ch === ',') { out.push(cur); cur = ''; } else cur += ch;
  }
  out.push(cur); return out;
}

// ---- progress ---------------------------------------------------------------
function readProgress(file) {
  const done = new Map();
  if (!fs.existsSync(file)) return done;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/).slice(1)) {
    const c = parseCsvLine(line); if (c[0]) done.set(c[0].toLowerCase(), c[1]);
  }
  return done;
}
function appendProgress(file, username, status, note) {
  if (!fs.existsSync(file)) fs.writeFileSync(file, 'username,status,when,note\n');
  const q = s => '"' + String(s || '').replace(/"/g, '""') + '"';
  fs.appendFileSync(file, [q(username), q(status), q(new Date().toISOString()), q(note)].join(',') + '\n');
}

// ---- helpers ----------------------------------------------------------------
const sleep = ms => new Promise(r => setTimeout(r, ms));
const rand = (a, b) => a + Math.floor(Math.random() * (b - a + 1));
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
function waitForEnter(msg) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(r => rl.question(msg, () => { rl.close(); r(); }));
}
async function waitForLogin(page, timeoutMs) {
  // Logged in = the chat UI is there (Add Friends / New Chat button or a search box) and we are not on a login page.
  const deadline = Date.now() + timeoutMs;
  let lastNote = 0;
  while (Date.now() < deadline) {
    const url = page.url();
    const onLogin = /accounts\.snapchat\.com|login|signin/i.test(url);
    const ui = await firstVisible(page, [
      page.getByRole('button', { name: /add friends?|new chat|compose/i }),
      page.getByRole('searchbox'),
      page.getByPlaceholder(/search/i),
    ], 500);
    if (ui && !onLogin) { console.log('Logged in; starting.'); await sleep(1500); return; }
    if (Date.now() - lastNote > 30000) { lastNote = Date.now(); console.log('Waiting for login in the browser window... (' + Math.round((deadline - Date.now()) / 60000) + ' min left)'); }
    await sleep(2000);
  }
  throw new Error('No login detected within the timeout. Log in to web.snapchat.com in the window and run again.');
}

async function firstVisible(page, locators, timeout) {
  // Return the first locator in the list that becomes visible within `timeout` ms.
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const loc of locators) {
      try { if (await loc.first().isVisible()) return loc.first(); } catch (e) { /* detached, try again */ }
    }
    await sleep(250);
  }
  return null;
}

// Each step is a list of candidate locators, most specific first. Snapchat for Web
// changes its markup, so these are by role/text, not by CSS class. If a step fails,
// run --discover and compare the captured tree with these candidates.
function candidates(page, person) {
  const name = person.username, display = person.displayName;
  const nameRe = new RegExp('^\\s*' + esc(name) + '\\s*$', 'i');
  const looseRe = new RegExp(esc(name) + (display ? '|' + esc(display) : ''), 'i');
  return {
    // A search box that can look up a person (Add Friends search, new chat picker, or the chat search).
    search: [
      page.getByRole('searchbox'),
      page.getByPlaceholder(/search|find|username|add friends|to:/i),
      page.getByRole('textbox', { name: /search|find|username|to/i }),
      page.getByRole('combobox'),
    ],
    openSearch: [
      page.getByRole('button', { name: /add friends?/i }),
      page.getByRole('button', { name: /new chat|compose|new message/i }),
      page.getByRole('link', { name: /add friends?/i }),
    ],
    result: [
      page.getByRole('option', { name: looseRe }),
      page.getByRole('listitem').filter({ hasText: looseRe }),
      page.getByRole('button', { name: looseRe }),
      page.getByRole('link', { name: looseRe }),
      page.getByText(nameRe),
      page.getByText(looseRe),
    ],
    profile: [
      page.getByRole('button', { name: /view profile|profile|more options|more|options|settings|⋯|…/i }),
      page.getByRole('button', { name: looseRe }),
      page.getByRole('heading', { name: looseRe }),
    ],
    manage: [
      page.getByRole('menuitem', { name: /manage friendship/i }),
      page.getByRole('button', { name: /manage friendship/i }),
      page.getByText(/manage friendship/i),
    ],
    remove: [
      page.getByRole('menuitem', { name: /remove friend|unfriend|cancel request|remove/i }),
      page.getByRole('button', { name: /remove friend|unfriend|cancel request/i }),
      page.getByText(/remove friend|unfriend|cancel request/i),
    ],
    confirm: [
      page.getByRole('dialog').getByRole('button', { name: /^remove|^yes|^confirm|^ok/i }),
      page.getByRole('alertdialog').getByRole('button', { name: /^remove|^yes|^confirm|^ok/i }),
      page.getByRole('button', { name: /^remove$|^remove friend$|^yes$|^confirm$/i }),
    ],
    cancel: [
      page.getByRole('button', { name: /^cancel$|^close$|^not now$/i }),
    ],
  };
}

async function capture(page, opts, tag) {
  if (!opts.discover) return;
  fs.mkdirSync(opts.outDir, { recursive: true });
  const base = path.join(opts.outDir, `${Date.now()}-${tag}`);
  try { await page.screenshot({ path: base + '.png', fullPage: false }); } catch (e) { /* ignore */ }
  try {
    const tree = await page.locator('body').ariaSnapshot();
    fs.writeFileSync(base + '.aria.txt', tree);
  } catch (e) {
    try { fs.writeFileSync(base + '.aria.txt', JSON.stringify(await page.accessibility.snapshot(), null, 2)); } catch (e2) { /* ignore */ }
  }
  console.log(`   captured ${path.basename(base)}.{png,aria.txt}`);
}

// Try to remove one person. Returns {status, note}: 'removed' | 'dry-run' | 'not-found' | 'failed'.
async function removeOne(page, opts, person) {
  const c = candidates(page, person);
  const step = async (label, locs, timeout, { required = true, type = null } = {}) => {
    const loc = await firstVisible(page, locs, timeout);
    if (!loc) { if (required) throw new Error('could not find: ' + label); return null; }
    if (type !== null) { await loc.click(); await loc.fill(''); await loc.type(type, { delay: rand(40, 110) }); }
    else await loc.click();
    await sleep(rand(600, 1400));
    await capture(page, opts, label);
    return loc;
  };

  // 1. Get to a search box; some layouts need the Add Friends / New Chat panel opened first.
  let search = await firstVisible(page, c.search, 1500);
  if (!search) { await step('open-search', c.openSearch, 8000); search = await firstVisible(page, c.search, 8000); }
  if (!search) throw new Error('could not find a search box');
  await search.click(); await search.fill(''); await search.type(person.username, { delay: rand(40, 110) });
  await sleep(rand(1200, 2200));
  await capture(page, opts, 'typed-username');

  // 2. Click the matching result.
  let result = await firstVisible(page, c.result, 6000);
  if (!result && person.displayName) {
    await search.fill(''); await search.type(person.displayName, { delay: rand(40, 110) });
    await sleep(rand(1200, 2200));
    result = await firstVisible(page, c.result, 6000);
  }
  if (!result) { await page.keyboard.press('Escape').catch(() => {}); return { status: 'not-found', note: 'no search result matched username or display name' }; }
  await result.click(); await sleep(rand(900, 1800)); await capture(page, opts, 'opened-result');

  // 3. Manage Friendship -> Remove Friend. The menu may sit behind a profile/more button.
  let manage = await firstVisible(page, c.manage, 2500);
  if (!manage) { await step('profile-or-more', c.profile, 6000); manage = await firstVisible(page, c.manage, 6000); }
  let remove;
  if (manage) { await manage.click(); await sleep(rand(600, 1300)); await capture(page, opts, 'manage-friendship'); }
  remove = await firstVisible(page, c.remove, 6000);
  if (!remove) throw new Error('could not find Remove Friend (after ' + (manage ? 'Manage Friendship' : 'opening profile') + ')');
  await remove.click(); await sleep(rand(600, 1300)); await capture(page, opts, 'remove-friend');

  // 4. Confirm.
  const confirm = await firstVisible(page, c.confirm, 6000);
  if (opts.dryRun) {
    const cancel = await firstVisible(page, c.cancel, 1500); if (cancel) await cancel.click();
    await page.keyboard.press('Escape').catch(() => {});
    return { status: 'dry-run', note: confirm ? 'reached confirmation dialog' : 'Remove clicked, no confirmation dialog seen' };
  }
  if (confirm) { await confirm.click(); await sleep(rand(800, 1600)); await capture(page, opts, 'confirmed'); }
  return { status: 'removed', note: confirm ? 'confirmed' : 'no confirmation dialog appeared' };
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const { chromium } = require('playwright');
  const context = await chromium.launchPersistentContext(opts.profile, {
    headless: opts.headless, viewport: { width: 1280, height: 860 },
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const page = context.pages()[0] || await context.newPage();
  await page.goto(opts.url, { waitUntil: 'domcontentloaded' });

  if (!opts.noWait) {
    console.log('\nA browser window is open on ' + opts.url + '. Log in there if needed.');
    if (process.stdin.isTTY) {
      await waitForEnter('Wait until your chats are visible, then press Enter here to start... ');
    } else {
      // Not an interactive terminal (e.g. run by Claude): watch the page for the logged-in UI instead.
      await waitForLogin(page, opts.loginTimeout);
    }
  }

  if (opts.discover) {
    opts.dryRun = true;
    console.log(`Discovery for ${opts.discover}: screenshots and page trees go to ${opts.outDir}`);
    await capture(page, opts, 'start');
    try { const r = await removeOne(page, opts, { username: opts.discover, displayName: '' }); console.log('Result:', r); }
    catch (e) { console.log('Stopped at:', e.message); await capture(page, opts, 'stopped'); }
    console.log('Send the files in ' + opts.outDir + ' back so the selectors can be adjusted.');
    await context.close(); return;
  }

  const people = readList(opts.list);
  const done = readProgress(opts.progress);
  const todo = people.filter(p => !['removed', 'dry-run'].includes(done.get(p.username.toLowerCase())));
  console.log(`${people.length} in list, ${people.length - todo.length} already done, ${todo.length} to go, doing up to ${opts.limit} now${opts.dryRun ? ' (dry run)' : ''}.`);

  let failures = 0, attempted = 0, removed = 0;
  for (const person of todo.slice(0, opts.limit)) {
    attempted++;
    process.stdout.write(`[${attempted}/${Math.min(opts.limit, todo.length)}] ${person.username} ... `);
    let r;
    try { r = await removeOne(page, opts, person); failures = r.status === 'failed' ? failures + 1 : 0; }
    catch (e) { r = { status: 'failed', note: e.message.split('\n')[0] }; failures++; }
    console.log(r.status + (r.note ? ' (' + r.note + ')' : ''));
    appendProgress(opts.progress, person.username, r.status, r.note);
    if (r.status === 'removed') removed++;
    await page.keyboard.press('Escape').catch(() => {});
    if (failures >= opts.maxFailures) {
      console.log(`\nStopped: ${failures} failures in a row. Snapchat may have changed its layout or rate-limited you. ` +
                  `Run with --discover <username> and check web/discover/.`);
      break;
    }
    if (attempted % opts.breakEvery === 0) { console.log(`   taking a ${Math.round(opts.breakMs / 1000)}s break`); await sleep(opts.breakMs); }
    else await sleep(rand(opts.minDelay, opts.maxDelay));
  }
  console.log(`\nDone for this run: ${removed} removed, ${attempted - removed} not removed. Progress is in ${opts.progress}.`);
  await context.close();
}

main().catch(e => { console.error('error:', e.message); process.exit(1); });
