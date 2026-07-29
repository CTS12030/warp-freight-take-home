# Freight Desk for Slack

**Recording:** [Walkthrough on Loom](https://www.loom.com/share/e7a451f9cdb6406a96f0a8f3bddf0ed2)
· **Brief:** [`BRIEF.md`](BRIEF.md) · **Tests:** 113, no network

Three read-only slash commands that let a coordinator price a lane, chase a shipment and
review an account without leaving Slack.

```
/quote 90001 to 60601, 2 pallets, 1000 lbs
/track S-1001-IN
/shipments
```

The interesting constraint is in the first one. Slack drops any slash command that is not
answered within **three seconds**. The rate-shop endpoint takes **four to sixteen** and
fails outright about **one time in seven**. So the honest version of this feature cannot
be a request/response — it has to acknowledge instantly and deliver later.

---

## What it looks like

```
$ /quote 90001 to 60601, 2 pallets, 1000 lbs
ack: HTTP 200 in 56ms

  Rate-shopping 90001 -> 60601 · 2 pallets · 1,000 lbs · pickup 2026-07-29
  — this usually takes 5-15 seconds.

--- 10.9s later, delivered to response_url ---

  Rates: 90001 -> 60601
  2 pallets · 1,000 lbs · 48x40x48 in · pickup 2026-07-29

  `1`  $432.29  ·  Forward Air     ·  3 days  ·  STANDARD
  `2`  $583.06  ·  XPO Logistics   ·  5 days  ·  STANDARD
  `3`  $583.66  ·  RL Carriers     ·  4 days  ·  STANDARD

  Showing the 3 cheapest of 10.
  Cheapest guaranteed: $646.07 · RL Carriers · 4 days.
  [Show all 10]  [Share to channel]

  Assumed a standard pallet (48x40x48 in). Assumed pickup on 2026-07-29 (next business day).
  ─────────────────────────────────────────────────────────────
  Indicative rate, not a booking · 10 carriers · quoted 2026-07-28 20:06 UTC
  · req 01MOCKREQ0000000000000001
```

---

## What the brief asked for

| Must-have | Where it lives |
|---|---|
| `/quote` end to end, cheapest-first | `commands/quote.py`; sorted on the exact float in `warp/normalize.py` |
| The 3-second ack against a 4–16s quote | `main.py` returns in ~60ms, work continues in a background task and posts to `response_url` |
| Verify Slack's signing secret | `slack/verify.py` — HMAC over the raw body, 5-minute replay window, 401 otherwise |
| Keys stay server-side | `.env` is gitignored; the key is never logged or rendered. There is no bot token at all |
| Every failure mode says something | Bad input, invalid ZIP, empty lane and exhausted retries each get their own card |
| Every quote logged | `store.py` (SQLite) records lane, user, channel, outcome, latency, attempts, cache status |
| README with decisions | below |

Stretch taken: `/track`, `/shipments` with the interactive expand, a lane cache, Block Kit
throughout, and 113 tests. Stretch skipped: deployment — a tunnel is enough to demonstrate
the interesting behaviour, and a hosted URL would not have changed a single decision below.

---

## Running it

```bash
# 1. the mock freight API, from the repo root
node mock/server.js

# 2. this app
cd slack-quote
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # then set SLACK_SIGNING_SECRET
.venv/bin/python -m uvicorn app.main:app --port 8000
```

### Exercising it without Slack

`scripts/fake_slack.py` signs requests exactly as Slack does, stands up a local receiver
to play the part of `response_url`, and reports how long the acknowledgement took.

```bash
.venv/bin/python scripts/fake_slack.py quote "90001 to 60601, 2 pallets, 1000 lbs"
.venv/bin/python scripts/fake_slack.py track S-1001-IN
.venv/bin/python scripts/fake_slack.py shipments
.venv/bin/python scripts/fake_slack.py action expand_shipment '{"shipment_id":"SH-1005","order_id":"O-1005"}'
```

### Tests

```bash
.venv/bin/python -m pytest -q      # 113 tests
```

Twelve of those drive the real FastAPI app end to end — signed request in, background
task, delivered card out — with the freight API and Slack's receiving end both stubbed
through one `MockTransport`.

### Usage report

```bash
.venv/bin/python scripts/report.py --days 7
```

### Connecting a real Slack workspace

See [`SLACK_SETUP.md`](SLACK_SETUP.md).

---

## Decisions & tradeoffs

**Acknowledge first, answer later.** Every command returns within ~60ms with an echo of
what was understood, then does the slow work in a `BackgroundTask` and posts the result
to the `response_url` Slack supplied. The echo is not filler: it is the cheapest possible
way for a coordinator to catch a misparse before they have waited fifteen seconds for the
wrong lane. Nothing that can block runs above the `return`.

**No bot token.** Replies go back through `response_url`, which arrives with each request
and needs no credential of its own. The only Slack secret this app holds is the signing
secret, and it only ever verifies with it. There is no `xoxb-` token to leak.

**Signatures are checked over the raw body.** The HMAC is computed on the exact bytes
received, before any form parsing, with a five-minute replay window and
`hmac.compare_digest`. Unsigned and tampered requests get a 401. Ten unit tests plus two
integration tests cover this.

**Retries honour `Retry-After`, and give up on a clock.** The upstream answers 503 and 429
with a `Retry-After` header; we obey it, and fall back to exponential backoff with jitter
when it is absent. The whole call is also bounded by a 45-second deadline, so we never
sleep into a window where the answer would be useless anyway. In a six-quote run against
the default mock, two calls needed a second attempt and both succeeded — the user never
saw the failure.

**We refuse to guess weight.** Weight drives the price, so a command without one gets a
refusal, not a quote built on a made-up number. Pallet count, dimensions and pickup date
*are* defaulted, because being wrong about them is recoverable — but every default is
stated on the card under "Assumed…". A wrong number a coordinator can see beats a wrong
number they cannot.

**The dirty data is cleaned where it enters, not where it renders.** `transitTime` arrives
in seconds and becomes days. A `transitTime` of `0` means *unknown*, so it renders as
"transit n/a" rather than a same-day promise nobody can keep. A missing `serviceLevel`
stays missing — "service level unspecified" — instead of being quietly defaulted to
STANDARD. Sorting is done on the exact float, which matters: two options in the fixture
differ by sixty cents ($583.056 against $583.656) and a rounded sort would order them
arbitrarily.

**An empty lane is an answer.** `00501 -> 60601` returns HTTP 200 with zero options. That
is the carriers saying no, not the system breaking, and it is worded that way. The parser
accepts any well-formed five-digit ZIP for the same reason: format is our business,
availability is the API's.

**Failures say what happened.** When the retries are exhausted the card carries the
upstream's own message plus the diagnostics — `upstream_unavailable · after 3 attempts ·
over 22.4s`. Enough for a coordinator to decide whether to retry or phone someone, and
enough for us to debug from a screenshot. The API key never appears in any message or log.

**Quotes are ephemeral, with a Share button.** A price shown to a channel is a price
someone will quote to a customer, so the default is visible only to the person who asked.
Sharing is one click and stamps who shared it.

**Repeat lanes are cached, and the card says so.** A rate shop is a billable call to every
carrier on the lane and the upstream rate-limits us; two coordinators pricing the same
lane a minute apart should cost one call. The card labels a cached result rather than
passing a stale number off as fresh.

**Every command is logged, especially the failures.** Successes, refusals, empty lanes and
upstream errors all land in the same SQLite table with latency, attempt count and cache
status. `scripts/report.py` turns that into the things worth knowing:

```
Reliability
  ok: 8   upstream_error: 2   no_rates: 1   invalid_input: 1   missing_weight: 1
  Upstream failure rate: 15.4%
  Average attempts: 1.5
Latency
  p50: 9895 ms      p95: 23977 ms
```

Volume alone would only tell us the feature is used. The failure lines tell us where it is
letting people down — which lanes we could not price is a sales signal, not just an error
count.

**Expanding a shipment degrades one section at a time.** Timeline, documents and invoice
are three independent calls, fetched concurrently, and on this account four of seven
shipments have no invoice. Each section renders its data or says why it cannot; a missing
invoice never blanks the timeline next to it.

---

## How this was built

Written in Cursor. Opus 5 planned the work and acted as orchestrator; Composer agents took
the individual modules; Opus reviewed and tested each one before the next batch went out.
The implementation-and-test loop ran about **30 minutes** of wall clock. Planning before it
and the Slack workspace wiring afterwards took considerably longer — the coding was never
the slow part.

**Contracts came before code, because that is what makes the work parallel.** `models.py`
was written first and depends on nothing: every dataclass the modules exchange — parse
results, normalized rates, the `WarpError` hierarchy, log entries. Once that existed, the
parser, the API client, the normalizer, the Block Kit layer and the store could all be
built at the same time against a fixed shape, each with its own tests, and still fit
together at the end. Without it, parallel agents produce five subtly different ideas of
what a rate is. The five commits in this repo follow that order.

**The review gate is the part that mattered.** Generated code passes its own tests very
happily. These are the things that only turned up when someone read it or ran it for real:

- `normalize_events` sorted `datetime` objects directly. The mock mixes timezone-aware and
  naive timestamps on the same shipment, so that raises `TypeError` in production. The
  fixtures were uniform, so the tests were green. Now sorted on `.timestamp()`.
- Every `httpx.TransportError` was mapped to `timeout`, so a mock that was simply not
  running told the user the upstream was slow. Only visible by stopping the mock and
  looking at the card. `connection_error` is now its own case.
- `/quote help` fell into the invalid-input path instead of showing usage.
- `1 pallets`, and a status printed twice on every timeline row.

The first two are the useful ones: a unit test suite written alongside the code tends to
share the code's assumptions. Running the real thing against the real mock is what broke
them.

**The product calls were not delegated.** Refusing to price without a weight; making
quotes ephemeral with a Share button; reading `transitTime: 0` as unknown rather than
same-day; justifying the cache by upstream cost rather than by latency; logging failures
because they are the half that says where the tool lets people down — each of those is a
decision about what the tool should do, argued out before any of it was assigned. An agent
will happily default a missing `serviceLevel` to `STANDARD` and produce clean, tested,
wrong code.

---

## What I would do next

**The item schema is a guess.** The mock only validates that `pickupDate`, both zipcodes
and a non-empty `listItems` are present, so the shape of a line item — `packaging`,
`weightUnit`, per-unit against total weight — is my reasonable reading, not something I
could confirm. First question for whoever owns the real API.

**The cache TTL is a judgement call, not a contract.** `freight-quote` returns no expiry
field, so 15 minutes is a conservative guess. If quotes carry a real validity window, that
should drive the TTL and be printed on the card.

**Both caches are in-process.** The rate cache and the rendered-card store are plain
dictionaries, so a second replica would not share them and a restart drops them. Redis is
the obvious swap; the interfaces are already narrow enough that it is a small change.

**`Retry-After` only handles the delta-seconds form.** The HTTP-date form would be ignored
and fall through to backoff. Correct but not complete.

**Freight parsing stops at one line item.** Real multi-class LTL with several commodities
and freight classes needs more than a regex, and probably a form rather than a text
command.

**`/track` takes one number at a time,** although the API accepts a batch. Batching would
be a small change and a real convenience.

**No holiday calendar.** "Next business day" skips weekends only, so it will cheerfully
propose Thanksgiving.
