# Mock Warp API

A local stand-in for the real Warp freight API, so you can build this challenge without
a key. Zero dependencies.

```bash
node mock/server.js
# warp-mock listening on http://localhost:3001
```

Then point your app at it:

```
WARP_API_BASE_URL=http://localhost:3001
WARP_API_KEY=anything          # ignored by the mock; there is no auth here
```

Your code is exactly what you'd write against the real API — same routes, same request
and response shapes. Only the base URL differs. If you advance, we hand you a real key
and you change that one line back to `https://gw.wearewarp.com/api/v1`.

## This is not a friendly stub — read this

It imitates a real, imperfect upstream on purpose. Building around these behaviors *is*
the challenge:

- **Quote endpoints are slow.** `/freights/quote` and `/freights/freight-quote` take
  **4–16 seconds** and always more than 3. Build for that.
- **They sometimes fail.** ~15% of quote calls return `503` or `429` with a `Retry-After`
  header. Assume any call can fail.
- **Rate-shop data is raw.** `/freights/freight-quote` returns options **unsorted**, with
  `transitTime` in **seconds** (one is `0`), prices with long decimals, and one option
  **missing `serviceLevel`**. Cheapest-first is your job, not the API's.
- **Responses depend on input.** An invalid ZIP (not 5 digits, or starting `00`) returns
  no rates. Unknown tracking numbers and unknown ids come back `not_found`. Shipments are
  paginated.
- **Booking is blocked** (`403`). This exercise is read-only.
- **Required fields are enforced** — a missing `pickupDate`, zipcode, or items → `400`.

Errors use the real API's envelope: `{ "code": "...", "message": "..." }`.

## Routes

| Method + path | Notes |
|---|---|
| `POST /freights/freight-quote` | Multi-carrier rate shop. Slow, flaky, unsorted, mixed units. `options: []` for a dead lane. |
| `POST /freights/quote` | Single all-in rate. Slow, flaky. `404 no_rates_found` for a dead lane. |
| `POST /freights/tracking` | Body `{ "trackingNumbers": [...] }` → array. Try `S-1001-IN` (in transit), `S-1002-DEL` (delivered), `S-1003-CAN` (canceled), and an unknown number. |
| `GET /freights/shipments?page=&pageSize=` | Paginated. 7 shipments total. |
| `GET /freights/events/:shipmentId` | e.g. `SH-1001`. Unknown → `404`. |
| `GET /freights/documents/:orderId` | e.g. `O-1002`. Returns working download links. |
| `GET /freights/invoices/:orderId` | e.g. `O-1001`. |
| `POST /freights/book`, `/freights/booking` | Always `403`. |

An optional `/api/v1` prefix is accepted, so both `http://localhost:3001` and
`http://localhost:3001/api/v1` work as your base URL.

## Tuning (optional, for your own dev loop)

Graders run the defaults. While developing you can make it fast and reliable:

```bash
MOCK_QUOTE_MIN_MS=0 MOCK_QUOTE_MAX_MS=0 MOCK_FAILURE_RATE=0 node mock/server.js
```

| Env var | Default | Meaning |
|---|---|---|
| `PORT` | `3001` | Port to listen on |
| `MOCK_QUOTE_MIN_MS` / `MOCK_QUOTE_MAX_MS` | `4000` / `16000` | Quote latency range |
| `MOCK_FAILURE_RATE` | `0.15` | Fraction of quote calls that fail transiently |

The fixtures the mock serves live in [`fixtures/`](fixtures/) — read them to see the
exact shapes you're working with.
