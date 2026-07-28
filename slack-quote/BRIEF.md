# Warp Work Trial — Freight Desk for Slack

A half-day build (~4 hours). This is a real item off our roadmap. We care far more
about the decisions you make than about how many boxes you tick — a smaller thing done
well beats a broad thing half-working.

## What you're building

A Slack app that lets a team run freight operations without leaving Slack: get a rate,
compare carriers, track a shipment, and pull its paperwork.

You'll build and test it in your **own free Slack workspace** (create one at
https://slack.com/get-started — two minutes). We don't need access to your Slack, and
you don't need ours. You'll submit a repo and a short recording — see
[`../SUBMISSION.md`](../SUBMISSION.md).

The freight endpoints your app will use:

| Endpoint | What it gives you |
|---|---|
| `POST /freights/freight-quote` | A rate shop — several carriers for one lane, each with price, transit time, service level |
| `POST /freights/quote` | A single all-in Warp rate for a lane |
| `POST /freights/tracking` | Live status and location for a tracking number |
| `GET /freights/shipments` | Recent shipments on the account |
| `GET /freights/events/:shipmentId` | A shipment's event timeline |
| `GET /freights/documents/:orderId` | Document links (BOL, POD) |
| `GET /freights/invoices/:orderId` | Cost breakdown for an order |

You build against the **local mock** in [`../mock/`](../mock/README.md) — no Warp key
needed this round:

```bash
node mock/server.js          # from the repo root; http://localhost:3001
```

- **Base URL:** `WARP_API_BASE_URL=http://localhost:3001`
- **Auth:** your app still sends an `apikey` header (keep all secrets server-side, out of
  the repo and out of Slack messages) — the mock ignores it, so any value works.
- **Read [`../mock/README.md`](../mock/README.md) first.** The mock is deliberately slow,
  flaky, and messy, which is where the difficulty lives.

## The build

Three slash commands. Get the first one genuinely good before moving on to the others.

1. **`/quote 90001 to 60601, 2 pallets, 1000 lbs`** — parse the lane, rate-shop it, and
   post the carriers back **cheapest-first** (price, carrier, transit, service level).
   This is the centerpiece.
2. **`/track <tracking-number>`** — post the shipment's current status, location, and
   most recent events.
3. **`/shipments`** — list recent shipments, each with a button that expands to its
   timeline, its documents (a clickable BOL link), and its invoice total.

If a user gives no dimensions, assume a standard pallet (48 × 40 × 48 in). If they give
no pickup date, use the next business day.

## The parts that are actually hard

Read these before you start — they're why this isn't a one-endpoint toy.

- **Slack's 3-second rule vs. a slow quote.** Slack drops your command if you don't
  respond within 3 seconds — and the mock's quote endpoints take **4–16 seconds, always
  more than 3**. So a call-then-reply handler will fail every time. You have to
  acknowledge immediately and deliver the result when it's ready — Slack hands you a
  `response_url` for exactly this. This is the single most important thing we're looking
  at, and the mock guarantees you can't skip it.
- **Interactivity, not just commands.** The `/shipments` expand button means handling
  Slack's interactive payloads on a second endpoint — a different surface than slash
  commands.
- **Real data has sharp edges.** Transit time comes back in different units across
  endpoints — don't render raw seconds as days. Prices need rounding. A shipment can
  come back canceled or with no rates. Handle the messiness instead of assuming the
  happy path.

## Requirements

**Must have**

- `/quote` works end to end and returns real, correct, cheapest-first rates in Slack.
- The 3-second-ack / slow-quote gap is handled correctly — the user gets an instant
  acknowledgement, then the rates when they're ready.
- You verify Slack's signing secret and reject requests that aren't really from Slack.
- Your keys stay server-side — never in the repo, a log, or a message.
- Every failure mode — bad input, invalid zip, no rates, and the mock's transient
  `503`/`429` responses — produces a clear message to the user, never a silent hang.
  (The flaky quote endpoint all but requires a retry/backoff; how you handle it matters.)
- **Every quote is logged.** We ship nothing without usage data. Record at least: time,
  Slack user and channel, the parsed lane, the rates returned (or the failure), and the
  latency. Any store is fine as long as it could answer "how many quotes this week, on
  which lanes."
- A short README: how to run it, the decisions you made, and what you'd do next for
  production.

**Stretch — pick what interests you; don't grind through all of it**

- `/track` and `/shipments` as described, with the interactive expand.
- Cache a lane while its quote is still valid.
- Tests.
- Deploy it (Vercel, Render, wherever) and send a live URL.
- Block Kit output you'd actually want to read at 2pm on a busy day.

## Out of scope

This is read-only — there's no booking flow to build. The mock returns `403` for
`/book` and `/freights/booking` (that's the one action the real API gates, since it
actually dispatches freight). Everything else — quote, track, list, pull docs — is fair
game. One workspace is plenty; no multi-workspace install or OAuth distribution needed.

## What to hand in

See [`../SUBMISSION.md`](../SUBMISSION.md) — your repo link, a README with a
"Decisions & tradeoffs" section, and a short recording of the commands working
(including one where the mock misbehaves and your app handles it).

## Stack

Whatever you're fastest in — Node/TypeScript (e.g. Slack Bolt), Python (`slack_sdk`),
anything. We're judging judgment and craft, not a framework.

Good luck, and have fun with it.
