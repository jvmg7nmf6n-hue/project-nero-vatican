// CC-1 Part D6b — push notification on a genuine new Forward Trial ENTRY.
// Ported near-verbatim from the private btc-monitor-main repo's push +
// state-file pattern, per explicit instruction ("Adapt the trigger condition
// only; the cooldown/state-file dedup logic is pure infra -- keep as-is").
//
// ONE DELIBERATE DEVIATION, reasoned below (not a silent drift from "keep as-
// is"): btc-monitor-main's COOLDOWN_MS exists to debounce a CONTINUOUSLY-
// POLLED live condition (e.g. a price threshold that stays true across many
// 15-minute ticks) -- a 2-hour cooldown stops it from re-alerting on every
// tick while the condition remains true. A Forward Trial ENTRY
// (nero_core.execution.export_trial_entries.py, D6a's own definition) is the
// OPPOSITE shape: a discrete, already-logged, IMMUTABLE historical fact (one
// execution_log row, forever) that this script reads from an
// append-only, ever-growing docs/site_data/trial_entries.json every run. A
// time-based cooldown on that kind of event is actively wrong here: once an
// entry's cooldown expires, the exact same historical entry would still be
// present in the feed and would fire a SECOND, spurious alert. So this
// script dedupes by execution_log_id PERMANENTLY (no expiry) rather than on
// a rolling cooldown window -- the state-file MECHANISM (a small local JSON
// map, checked before pushing, updated after) is unchanged from the
// original pattern; only the retention policy is adapted to fit a
// once-ever event instead of a debounced continuous one.
//
// SECRETS: NTFY_TOPIC is read from process.env only (GitHub Actions
// `secrets.NTFY_TOPIC`) -- never printed, logged, or included in any commit.
// If you need to confirm it's set, log presence/length only, never the value.

const fs = require('fs');
const path = require('path');

const NTFY_TOPIC = process.env.NTFY_TOPIC || '';
const TRIAL_ENTRIES_PATH = path.join(__dirname, 'docs', 'site_data', 'trial_entries.json');
const STATE_FILE = path.join(__dirname, 'signal_alerts_state.json');

async function push(title, body, priority, tag) {
  if (!NTFY_TOPIC) {
    console.log('NTFY_TOPIC not set (length: 0) -- skipping push, dry run only');
    return;
  }
  try {
    await fetch(`https://ntfy.sh/${NTFY_TOPIC}`, {
      method: 'POST',
      headers: { Title: title, Priority: priority || 'default', Tags: tag || '' },
      body,
    });
    console.log('pushed:', title);
  } catch (e) {
    console.log('push failed:', e.message);
  }
}

function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch (e) {
    return {};
  }
}

function loadTrialEntries() {
  try {
    const payload = JSON.parse(fs.readFileSync(TRIAL_ENTRIES_PATH, 'utf8'));
    return Array.isArray(payload.entries) ? payload.entries : [];
  } catch (e) {
    console.log('could not read trial_entries.json (non-fatal):', e.message);
    return [];
  }
}

function formatEntryMessage(entry) {
  const direction = entry.direction || 'position';
  const priceText = entry.entry_price != null ? entry.entry_price.toFixed ? entry.entry_price.toFixed(4) : entry.entry_price : 'n/a';
  const name = entry.hypothesis_name || entry.trial_id;
  return {
    title: `Vatican | Forward Trial ENTRY | ${name}`,
    body: `${entry.asset || '?'} ${direction} @ ${priceText} (origin: ${entry.origin_agent || 'unknown'})`,
  };
}

async function main() {
  const entries = loadTrialEntries();
  const state = loadState();
  let newAlerts = 0;

  for (const entry of entries) {
    const key = `execution_log_id:${entry.execution_log_id}`;
    if (state[key]) continue; // already alerted, permanently -- see module header for why no cooldown expiry

    const { title, body } = formatEntryMessage(entry);
    await push(title, body, 'high', 'chart_with_upwards_trend');
    state[key] = { alertedAt: entry.timestamp, trialId: entry.trial_id };
    newAlerts += 1;
  }

  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  console.log(`Done. ${newAlerts} new Forward Trial ENTRY alert(s) sent, ${entries.length} total entries in feed.`);
}

main().catch((e) => {
  console.log('signal_alerts.js failed (non-fatal, workflow continues):', e.message);
});
