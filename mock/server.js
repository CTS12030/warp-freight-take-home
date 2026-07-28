#!/usr/bin/env node
/**
 * Warp Freight — mock API for the take-home challenge.
 *
 * A local stand-in for the real Warp freight API (https://gw.wearewarp.com/api/v1).
 * Zero dependencies — just `node mock/server.js`. It ignores the apikey header:
 * there is no auth here, because there is no real service behind it.
 *
 * It is deliberately NOT a friendly happy-path stub. It mimics a real, imperfect
 * upstream so your app has to be built like production software:
 *
 *   - Quote endpoints are SLOW (always > 3s) and sometimes FAIL (503/429 + Retry-After).
 *   - Rate-shop options come back UNSORTED, transit times in raw SECONDS, prices with
 *     long decimals, and one option missing its serviceLevel.
 *   - Responses depend on your INPUT: invalid ZIPs return no rates, unknown ids 404,
 *     shipments are paginated.
 *   - Booking endpoints are BLOCKED (403). This is read-only.
 *   - Missing required fields → 400.
 *
 * Everything is tunable via env vars (see README). Graders run it on defaults.
 */

const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = Number(process.env.PORT || 3001);
// Quote latency floor is >3s ON PURPOSE so the Slack 3-second-ack problem always bites.
const QUOTE_MIN_MS = Number(process.env.MOCK_QUOTE_MIN_MS || 4000);
const QUOTE_MAX_MS = Number(process.env.MOCK_QUOTE_MAX_MS || 16000);
// Fraction of quote calls that fail transiently. Set to 0 while developing if you like.
const FAILURE_RATE = Number(process.env.MOCK_FAILURE_RATE || 0.15);

const FIX = path.join(__dirname, 'fixtures');
const load = (f) => JSON.parse(fs.readFileSync(path.join(FIX, f), 'utf8'));
const freightQuote = load('freight-quote.json');
const singleQuote = load('quote.json');
const tracking = load('tracking.json');
const events = load('events.json');
const shipments = load('shipments.json');
const documents = load('documents.json');
const invoices = load('invoices.json');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rand = (min, max) => Math.floor(min + Math.random() * (max - min));

function send(res, status, body, headers = {}) {
  const payload = typeof body === 'string' ? body : JSON.stringify(body, null, 2);
  res.writeHead(status, { 'Content-Type': 'application/json', ...headers });
  res.end(payload);
}
// Error envelope matches the real Warp API: { code, message }.
const err = (res, status, code, message, headers) => send(res, status, { code, message }, headers);

function readJson(req) {
  return new Promise((resolve) => {
    let raw = '';
    req.on('data', (c) => (raw += c));
    req.on('end', () => {
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); } catch { resolve(null); } // null = malformed JSON
    });
  });
}

// An invalid US ZIP (not 5 digits, or a 00xxx placeholder) means "no rates on this lane".
const isDeadZip = (z) => !/^\d{5}$/.test(String(z || '')) || String(z).startsWith('00');

// Shared slow/flaky gate for the two quote endpoints.
async function quoteGate(res) {
  await sleep(rand(QUOTE_MIN_MS, QUOTE_MAX_MS));
  if (Math.random() < FAILURE_RATE) {
    const which = Math.random() < 0.5 ? 503 : 429;
    if (which === 429) {
      err(res, 429, 'rate_limit_exceeded', 'Too many requests, slow down.', { 'Retry-After': '3' });
    } else {
      err(res, 503, 'upstream_unavailable', 'Carrier rating service is temporarily unavailable.', { 'Retry-After': '2' });
    }
    return false;
  }
  return true;
}

function validateQuoteBody(body) {
  if (body === null) return 'Request body is not valid JSON.';
  if (!body.pickupDate) return 'pickupDate is required!';
  if (!body.pickupInfo || !body.pickupInfo.zipcode) return 'pickupInfo.zipcode is required!';
  if (!body.deliveryInfo || !body.deliveryInfo.zipcode) return 'deliveryInfo.zipcode is required!';
  const items = body.listItems || body.items;
  if (!Array.isArray(items) || items.length === 0) return 'listItems is required!';
  return null;
}

const server = http.createServer(async (req, res) => {
  const { pathname, searchParams } = new URL(req.url, `http://localhost:${PORT}`);
  const base = `http://localhost:${PORT}`;
  // Strip an optional /api/v1 prefix so both base-url styles work.
  const route = pathname.replace(/^\/api\/v1/, '') || '/';
  const method = req.method.toUpperCase();

  // Health / index
  if (route === '/' ) return send(res, 200, { service: 'warp-mock', ok: true, see: 'mock/README.md' });
  if (route === '/health') return send(res, 200, { ok: true });

  // Booking is out of scope for this exercise — blocked here too.
  if (route === '/freights/book' || route === '/freights/booking') {
    return err(res, 403, 'request_unauthorized', 'Booking is disabled in the challenge environment. This exercise is read-only.');
  }

  // Multi-carrier rate shop (the interesting one).
  if (route === '/freights/freight-quote' && method === 'POST') {
    const body = await readJson(req);
    const bad = validateQuoteBody(body);
    if (bad) return err(res, 400, body === null ? 'invalid_field_data' : 'required_field_missing', bad);
    if (!(await quoteGate(res))) return;
    if (isDeadZip(body.deliveryInfo.zipcode) || isDeadZip(body.pickupInfo.zipcode)) {
      return send(res, 200, { id: freightQuote.id, requestId: freightQuote.requestId, options: [] });
    }
    // Note: options are intentionally returned UNSORTED and un-normalized.
    return send(res, 200, freightQuote);
  }

  // Single all-in quote.
  if (route === '/freights/quote' && method === 'POST') {
    const body = await readJson(req);
    const bad = validateQuoteBody(body);
    if (bad) return err(res, 400, body === null ? 'invalid_field_data' : 'required_field_missing', bad);
    if (!(await quoteGate(res))) return;
    if (isDeadZip(body.deliveryInfo.zipcode) || isDeadZip(body.pickupInfo.zipcode)) {
      return err(res, 404, 'no_rates_found', 'No rates available for this lane.');
    }
    return send(res, 200, singleQuote);
  }

  // Tracking — POST { trackingNumbers: [...] } → array, one entry per number.
  if (route === '/freights/tracking' && method === 'POST') {
    const body = await readJson(req);
    if (body === null) return err(res, 400, 'invalid_field_data', 'Request body is not valid JSON.');
    const nums = body.trackingNumbers;
    if (!Array.isArray(nums) || nums.length === 0) return err(res, 400, 'required_field_missing', 'trackingNumbers is required!');
    await sleep(rand(100, 400));
    const out = nums.map((n) => tracking[n] || { trackingNumber: n, error: 'not_found' });
    return send(res, 200, out);
  }

  // Shipments — paginated list.
  if (route === '/freights/shipments' && method === 'GET') {
    await sleep(rand(100, 400));
    const page = Math.max(1, Number(searchParams.get('page') || 1));
    const pageSize = Math.max(1, Number(searchParams.get('pageSize') || 5));
    const all = shipments.data;
    const start = (page - 1) * pageSize;
    return send(res, 200, { total: all.length, page, pageSize, data: all.slice(start, start + pageSize) });
  }

  // Events for a shipment.
  const evMatch = route.match(/^\/freights\/events\/([^/]+)$/);
  if (evMatch && method === 'GET') {
    await sleep(rand(80, 300));
    const hit = events[decodeURIComponent(evMatch[1])];
    if (!hit) return err(res, 404, 'not_found', 'Shipment not found.');
    return send(res, 200, hit);
  }

  // Documents for an order (URLs point back at this mock, and actually download).
  const docMatch = route.match(/^\/freights\/documents\/([^/]+)$/);
  if (docMatch && method === 'GET') {
    await sleep(rand(80, 300));
    const hit = documents[decodeURIComponent(docMatch[1])];
    if (!hit) return err(res, 404, 'not_found', 'Order not found.');
    const withBase = JSON.parse(JSON.stringify(hit).replace(/__BASE__/g, base));
    return send(res, 200, withBase);
  }

  // Invoices for an order.
  const invMatch = route.match(/^\/freights\/invoices\/([^/]+)$/);
  if (invMatch && method === 'GET') {
    await sleep(rand(80, 300));
    const hit = invoices[decodeURIComponent(invMatch[1])];
    if (!hit) return err(res, 404, 'not_found', 'Order not found.');
    return send(res, 200, hit);
  }

  // A working document download so BOL/POD links aren't dead.
  const fileMatch = route.match(/^\/p\/files\/download\/([^/]+)$/);
  if (fileMatch && method === 'GET') {
    const id = decodeURIComponent(fileMatch[1]);
    res.writeHead(200, { 'Content-Type': 'text/plain', 'Content-Disposition': `inline; filename="${id}.txt"` });
    return res.end(`MOCK DOCUMENT ${id}\nThis stands in for a real BOL/POD PDF.\n`);
  }

  return err(res, 404, 'not_found', `No mock route for ${method} ${route}`);
});

server.listen(PORT, () => {
  console.log(`warp-mock listening on http://localhost:${PORT}`);
  console.log(`  quote latency: ${QUOTE_MIN_MS}-${QUOTE_MAX_MS}ms   failure rate: ${FAILURE_RATE}`);
  console.log(`  point your app's WARP_API_BASE_URL at http://localhost:${PORT}`);
});
