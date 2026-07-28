# Warp Work Trial — Support Voice Agent

A half-day build (~4 hours). This is a real item off our roadmap — a voice agent our
customers can talk to for support. We care far more about the decisions you make than
about how many features you finish; a smaller thing done well beats a broad thing
half-working.

## What you're building

A voice agent, in the browser, that a Warp customer can talk to about their freight.
They speak; it answers out loud — **grounded in the freight API** (a local mock this
round), not made up.

Examples of what a caller should be able to ask:

- "Where's my shipment S-…?" → live status and latest events
- "What would it cost to ship two pallets from 90001 to 60601?" → a real rate
- "What do I owe on order P-…?" → the invoice total
- "Can you send me the BOL?" → the document link

You build and test it in the browser (mic in, voice out). You'll submit a repo and a
recording of an actual spoken conversation — see [`../SUBMISSION.md`](../SUBMISSION.md).

## The stack

For this round: the **Warp API is the local mock** (no Warp key needed). For the voice
itself, use **any provider you have working access to** — OpenAI, ElevenLabs, Groq's free
tier, local models, whatever gets you a working pipeline. Keep every key server-side.

How you assemble them is up to you. Two reasonable paths:

- **Roll your own pipeline** — OpenAI for speech-to-text and the reasoning/tool-calling
  model, ElevenLabs for the spoken reply, wired together yourself.
- **Use ElevenLabs' Conversational AI agent** — and give it custom tools (webhooks) that
  hit a small Warp proxy you write.

Either is fine. What is **not** optional: the agent must actually call the freight API
and answer from what it returns. An agent that sounds great but invents shipment statuses
fails the exercise.

Because these speech and LLM APIs change often, work from your provider's current official
docs rather than memory — checking the live docs is part of the job.

## The Warp API — a local mock

You build against the mock in [`../mock/`](../mock/README.md) — no Warp key this round:

```bash
node mock/server.js          # from the repo root; http://localhost:3001
```

- **Base URL:** `WARP_API_BASE_URL=http://localhost:3001`
- Your server-side calls still send an `apikey` header; the mock ignores it.
- **Read [`../mock/README.md`](../mock/README.md) first** — it's slow and flaky on
  purpose, which is exactly what a voice agent has to survive gracefully.

Read endpoints your agent will lean on:

| Endpoint | Use |
|---|---|
| `POST /freights/tracking` | Status + location for a tracking number |
| `GET /freights/events/:shipmentId` | A shipment's event timeline |
| `GET /freights/shipments` | Recent shipments on the account |
| `POST /freights/quote` (or `/freights/freight-quote`) | A rate for a lane |
| `GET /freights/invoices/:orderId` | What's owed on an order |
| `GET /freights/documents/:orderId` | BOL / POD links |

Full docs: https://developer.wearewarp.com/docs/freight/

## The parts that are actually hard

Read these before you start — they're the difference between a demo and a real agent.

- **Latency and turn-taking.** A voice agent lives or dies on responsiveness. Stream the
  pieces so it feels like a conversation, not a walkie-talkie, and ideally let the caller
  interrupt (barge-in). Getting the round-trip to feel natural is the single most
  important thing we're looking at.
- **Grounding.** Every factual answer — a status, a price, a balance — must come from an
  actual API call. If the mock returns `not_found` for a shipment, the agent says so or
  asks for the number again. It never guesses.
- **Recovery, out loud.** The caller mumbles a tracking number, the order doesn't exist,
  the API times out — the agent handles it inside the conversation. No dead air, no crash.
- **Guardrails.** The agent never books a shipment and never promises to, and never
  invents a price or ETA. It's read-only support, up to the same line as everything else
  here.

## Requirements

**Must have**

- A working spoken conversation in the browser: you talk, it answers in voice.
- At least **one** Warp tool wired and genuinely grounded — e.g. the agent tracks a real
  shipment and reads back its real status.
- Graceful recovery when things go wrong (mis-heard input, unknown order, API error),
  handled in the conversation.
- Every key stays server-side — never in the browser bundle, the repo, or a log.
- **Every call is logged** (we ship nothing without usage data): the transcript, which
  tools were called with what result, and the turn latencies. Any store is fine as long
  as it could answer "how many calls this week, and what did people ask for."
- A short README: how to run it, the decisions you made, and what you'd do next for
  production.

**Stretch — pick what interests you; don't grind through all of it**

- More than one tool (quote + track + invoice + documents).
- Barge-in / interruption handling.
- A live transcript UI beside the conversation.
- A real phone number (Twilio) instead of the browser.
- A latency budget with measured numbers, and what you did to hit it.
- Deploy it and send a live URL.

## Out of scope

The agent is read-only: it never calls `/book` or `/freights/booking` (the mock returns
`403` anyway — that's the one action the real API gates, since it dispatches freight), and
never claims it has booked something. Everything read-only is fair game. It also must not
invent data to sound helpful; "I don't have that" is a correct answer.

## What to hand in

See [`../SUBMISSION.md`](../SUBMISSION.md) — your repo link, a README with a
"Decisions & tradeoffs" section, and a recording of a real spoken conversation that
includes one moment where it fetches data and one where something goes wrong and it
recovers.

## Stack

Your choice of language and framework. We're judging judgment and craft — how the agent
feels to talk to and how honestly it's grounded — not a specific tool.

Good luck, and have fun with it.
