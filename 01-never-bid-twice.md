# 01 · A bid must never go above the limit or out twice

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
- **The amount.** A bid once failed because an amount went out in a type the receiving API didn't accept. Now a guard refuses to build any request whose amount, read back from the wire format, isn't exactly the intended value. Malformed input becomes a refusal, never a wrong bid.
- **Dependent bids.** One bid can depend on the outcome of another. Right before each send, a gate re-checks that the dependency still allows the bid. If the check itself fails, nothing is sent.
- **Who is winning.** "Am I the high bidder?" is answered from fresh data from the marketplace, never from a local flag that might be stale.
- **Late extensions.** Many auctions extend when a late bid arrives. The bidder follows the extension and bids again when outbid, up to the limit.
