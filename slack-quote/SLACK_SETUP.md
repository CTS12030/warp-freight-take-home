# Connecting a real Slack workspace

Everything in the main README runs without Slack. This is the extra wiring to drive it
from an actual workspace.

## 1. Expose the local app

Slack needs a public HTTPS URL to reach you. Either works:

```bash
cloudflared tunnel --url http://localhost:8000
# or
ngrok http 8000
```

Copy the `https://…` address it prints. Call it `$BASE` below. It changes each time you
restart the tunnel, and every URL in the Slack app config has to be updated when it does.

If cloudflared keeps retrying and never prints a URL, the network is likely blocking QUIC.
`cloudflared tunnel --protocol http2 --url http://localhost:8000` gets around it.

## 2. Create the app from the manifest

At <https://api.slack.com/apps> choose **Create New App → From a manifest**, pick your
workspace, and paste in [`slack-app-manifest.json`](slack-app-manifest.json) with every
`REPLACE_WITH_YOUR_PUBLIC_URL` swapped for `$BASE`.

Use the dialog's **JSON** tab rather than the YAML one. The same manifest is in
[`slack-app-manifest.yaml`](slack-app-manifest.yaml) if you prefer reading it, but YAML
is indentation-sensitive and a copy-paste that shifts one list item by a space is
rejected with an unhelpful marker. JSON does not have that failure mode.

That registers all three slash commands and switches interactivity on in one go, so you
can skip sections 4 and 5 below — they are kept for anyone configuring the app by hand.

## 3. Copy the signing secret

**Basic Information → App Credentials → Signing Secret**. Put it in `slack-quote/.env`:

```
SLACK_SIGNING_SECRET=<the secret>
```

Restart the app after changing this. It is the only Slack credential needed — replies go
back through the `response_url` that arrives with each request, so there is no bot token
to create or store.

## 4. Register the three commands *(already done by the manifest)*

**Slash Commands → Create New Command**, three times. The description and hint are what
users see in Slack's autocomplete, so they are worth filling in properly.

| Command | Request URL | Short description | Usage hint |
|---|---|---|---|
| `/quote` | `$BASE/slack/commands` | Rate-shop a lane, cheapest first | `90001 to 60601, 2 pallets, 1000 lbs` |
| `/track` | `$BASE/slack/commands` | Where is my shipment? | `S-1001-IN` |
| `/shipments` | `$BASE/slack/commands` | Recent shipments on the account | *(none)* |

## 5. Turn on interactivity *(already done by the manifest)*

**Interactivity & Shortcuts → toggle on**, Request URL:

```
$BASE/slack/interactivity
```

This is what makes the *Show all*, *Share to channel*, *Details* and *Next page* buttons
work. Without it the buttons render but do nothing.

If there is no Request URL field on that page, Socket Mode is on — it is the default for a
blank app. Turn it off under **Settings → Socket Mode** and the field appears. This app is
plain HTTP request/response, so Socket Mode is not wanted here.

## 6. Install

**Install App → Install to Workspace.** No scopes are required beyond what the slash
commands add automatically.

## 7. Check it

In any channel:

```
/quote 90001 to 60601, 2 pallets, 1000 lbs
```

You should see the acknowledgement immediately and the rate card five to fifteen seconds
later.

## If something is wrong

**`dispatch_failed` in Slack** — the app did not answer within three seconds. Check that
it is running and that the tunnel URL matches what is configured.

**Nothing happens at all** — look at the app's log for
`Rejected an unverified request: signature mismatch`. That means the signing secret in
`.env` does not match the one in the Slack app config.

**The acknowledgement arrives but the rates never do** — the delayed reply failed. The log
will show `Gave up delivering a delayed reply`. Usually the mock API is not running.

**Buttons do nothing** — interactivity is off, or its Request URL still points at an old
tunnel address.
