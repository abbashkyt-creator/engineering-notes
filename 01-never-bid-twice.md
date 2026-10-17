# 01 · Bids reach the API at most once, and never above the limit

**When:** September 2026 · **Where:** the bidding path (Python services behind a Node.js proxy)

GhostNode places bids with real money. Two rules cannot break: a bid never exceeds the buyer's limit, and a bid is never sent twice.

## Why duplicates happen

A bid is a non-idempotent request, so what to do after a failure depends on where it failed:

| What came back | Did the bid get through? | What the system does |
|---|---|---|
| Connection refused, DNS failure: nothing was sent | No | Retries within a short budget |
| Connection reset after sending, read timeout, no status | Unknown | Never retries. Reports the bid as unconfirmed |
| A 5xx response | Unknown | Never retries. Reports the bid as unconfirmed |
| A 2xx or 4xx response | The response says | Acts on the response |

The unknown rows are how systems bid twice: the first request may have landed, and only the answer was lost. An unconfirmed bid is settled by the next read of the auction's state, not by sending the bid again.

## What the system does

- **The proxy hop.** The Node.js proxy between the console and the API retries a mutating request only on pre-connection errors.
  - A test drives the proxy against an upstream that resets mid-request and checks the request is not replayed.
  - Another test checks that a bid issued while the API is restarting arrives exactly once.
  - All 8 checks pass. This covers the proxy hop.
  - The console reports the same three outcomes to the buyer: "did not go through" (safe to try again), "not confirmed" (check before trying again), and "failed" with the marketplace's reason.
- **The limit.** The amount to bid is computed per marketplace, and the computation returns no bid when the next legal bid would pass the buyer's limit. For the marketplace with three bidding strategies, a test checks that none of them overshoots. On the main marketplace, the call that sends a bid also refuses an amount above the limit, as a second check. The tests are `test_every_strategy_stops_at_the_ceiling_none_of_them_overshoots` and `test_urgent_rejects_above_ceiling` (the product code is private).
- **The amount.** A bid once failed because an amount went out in a type the receiving API didn't accept. Now a guard refuses to build any request whose amount, read back from the wire format, isn't exactly the intended value. Malformed input becomes a refusal, never a wrong bid.
- **Dependent bids.** One bid can depend on the outcome of another. Right before each send, a gate re-checks that the dependency still allows the bid. If the check itself fails, nothing is sent.
- **Who is winning.** "Am I the high bidder?" is answered from fresh data from the marketplace, never from a local flag that might be stale.
- **Late extensions.** Many auctions extend when a late bid arrives. The bidder follows the extension and bids again when outbid, up to the limit.

## The other hop, and what is not covered

The tests above cover the hop from the console to the API. The API's own call to the marketplace is a separate hop:

- It is a single POST that is never retried.
- If it times out, the attempt is logged and nothing is resent. The next decision comes from a fresh read of the lot, so a bid that did land shows up there (we are the high bidder) instead of going out again.
- Two gaps remain. The log records such an attempt as failed, not unconfirmed. And this hop has no replay test of its own yet.
