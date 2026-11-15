# btc-race-bot

A long-only cbBTC/USDC trading bot for the make.fun competition
**btc-race-24h-20261115-0828** ("Race a BTC trading bot live for 24 hours",
$250 prize pool, top 10 paid). Paper money only — $1,000 starting capital,
no real money is traded.

## How it works

The bot speaks `agent-fun/bars-replay/v1`: one JSON line per minute (a
1-minute cbBTC/USD bar from the Orca Whirlpool), one reply per batch with
buy/sell orders. Orders fill at the next minute's open, charged 4 bps fee +
2 bps slippage + constant-product price impact against the bar's pool depth.

Strategy — two complementary long entries, one exit discipline:

- **Breakout**: buy when the close makes a new 60-minute high (by 0.05%).
  Catches a bounce while it is already moving up.
- **Deep dip**: buy when the close is ≥ 3.0% below the 120-minute high and
  the 5-minute return is positive (the fall has stopped and turned).
  Catches sharp washout bottoms.
- **Exits**: stop loss −0.50% from the VWAP entry; trailing stop (arms at
  +0.40%, sells 0.50% below the peak since entry) so a big bounce runs to
  several percent; time stop after 8 hours. Full size (100% of cash) on
  every entry; no new entries after batch 1400.

## Dev-window result

Frozen 24h dev window (2026-11-14 08:28 UTC – 2026-11-15 08:28 UTC),
measured with a local replay that implements the harness fill math exactly
(fee/slippage/impact, pool walking, flatten, equity points):

| metric | value |
|---|---|
| Net PnL | **+$42.28 (+4.23%)** |
| Max drawdown | 1.02% (race limit 25%) |
| Round trips | 4 (3 wins) |
| Fees paid | $3.26 |
| Buy-and-hold on the same window | −$44.01 |

The window trends down −4.0% overall, so almost every long-only rule loses
money on it; this bot makes money by staying flat through the grind and
catching the sharp dips and breakouts. The largest single trade (+$42)
rode the day's washout low back up with the trailing stop.

## Files

- `main.py` — the bot (Python 3.13 stdlib only).
- `vendor/makefun_bars.py` — the kit's bars-replay/v1 bot shim, byte-for-byte
  copy of `sdk/makefun_bars.py` from the competition kit.
- `LICENSE` — MIT.

## Run

```sh
python3 -P -s main.py
```

Deterministic: no clock, no network, no files, no randomness. Two runs on
the same data produce byte-identical replies.
