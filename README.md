# Warp Freight — Engineering Challenge

A take-home build against a freight API. Pick **one** of two projects, spend about a
**half day (~4 hours)**, and submit within **2 days**. We care far more about the
decisions you make than about how many features you finish — a smaller thing done well
beats a broad thing half-working.

## Pick one

- [`slack-quote/`](slack-quote/README.md) — a Slack app for quoting, tracking, and
  pulling docs on freight, without leaving Slack.
- [`voice-agent/`](voice-agent/README.md) — a browser voice agent a customer can talk to
  for support, grounded in the freight API.

Each folder has its own brief (`README.md`). Read both, then choose the one that plays to
your strengths.

## The API — you build against a local mock

You do **not** need a Warp key for this round. The repo ships a local stand-in for the
Warp freight API in [`mock/`](mock/README.md):

```bash
node mock/server.js        # http://localhost:3001, zero dependencies
```

Point your app at it with `WARP_API_BASE_URL=http://localhost:3001`. Your code is exactly
what you'd write against the real API — same routes, same request and response shapes.
Only the URL differs, so if you advance we hand you a real key and you change one line.

**Read [`mock/README.md`](mock/README.md) before you start.** The mock is deliberately a
realistic, imperfect upstream — slow quote calls, transient failures, unsorted and
mixed-unit data, input-dependent responses. Handling that well is the challenge.

For the **voice-agent** project you bring your **own** speech + LLM provider — use
whatever you have working access to (OpenAI, ElevenLabs, Groq's free tier, local models).
The **slack-quote** project needs no paid keys — just a free Slack workspace.

## Scope — read-only

This exercise is **read-only**: quote, track, list shipments, pull documents, read
invoices. There's no booking flow to build — the mock returns `403` for
`/freights/book` and `/freights/booking`, mirroring how the real API gates the one action
that actually dispatches freight. Everything up to that line is fair game.

## How to submit

See [`SUBMISSION.md`](SUBMISSION.md). In short: click **"Use this template"** to make your
own private repo, build, invite `rahulharikumarr`, and send us the link, your README, and
a short screen recording.

## Using AI — encouraged

We build with AI here, and you should too. Use Claude Code, Cursor, Copilot — whatever
you're fastest in; we expect fluency with these tools and want to see it, not a
from-memory boilerplate exercise. The one thing that matters: the result has to be
**yours**. You understand every line, the design calls were deliberate, and you can
explain and extend it live on a follow-up call. AI-generated code you can't defend is
what sinks a submission — not the AI.

## What we value

Judgment and craft over coverage: how you handle the messy edges the mock throws at you,
how honestly you ground what you build in real data, and how clearly you explain the
calls you made. Use whatever stack you're fastest in.
