# How to submit

This is a take-home. Budget about **half a day (~4 hours)** of work, and submit within
**2 days** of receiving it.

## 1. Pick one project

Build **either** [`slack-quote/`](slack-quote/README.md) **or**
[`voice-agent/`](voice-agent/README.md) — your choice. Do one well rather than both
halfway. Read each brief before you start.

## 2. Set up

- **Warp API:** run the local mock — `node mock/server.js` — and point your app at it
  with `WARP_API_BASE_URL=http://localhost:3001`. No Warp key needed. Read
  [`mock/README.md`](mock/README.md) first; it behaves like a real, imperfect upstream on
  purpose.
- **Slack project:** use your own free Slack workspace (slack.com/get-started).
- **Voice project:** use any speech + LLM provider you have working access to (OpenAI,
  ElevenLabs, Groq's free tier, local models — your call). Keep every key server-side and
  out of the repo.

## 3. Build

Meet the must-haves in your project's brief first, then reach for stretch goals if time
allows. The mock is intentionally slow, flaky, and messy — handling that gracefully is
the point, not an edge case.

## 4. Submit

1. Click **"Use this template" → Create a new repository** (top of this repo's GitHub
   page). Set your new repo to **Private**. (Please use the template rather than forking,
   so your work stays your own.)
2. Build your project inside your new repo.
3. When you're done, invite **`rahulharikumarr`** as a collaborator so we can see it.
4. Send us:
   - the **repo link**
   - your **README**, including a short **"Decisions & tradeoffs"** section: what you
     chose, what you cut, and what you'd do next with more time
   - a **2–3 minute screen recording** (Loom or similar) of it working — include one
     moment where the mock misbehaves (a slow or failed quote, a bad input) and your app
     handles it cleanly

## What we're looking for

Judgment and craft over raw coverage. **Using AI is encouraged** — Claude Code, Cursor,
Copilot, whatever you're fastest in; we expect fluency with these tools. Expect a
follow-up call where we walk through your code together and ask you to extend it live, so
build something that's genuinely yours — you understand every line and can defend it.

Do not call any booking endpoint, even against the mock — this is read-only.
