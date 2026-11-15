"""btc-race-bot: a long-only cbBTC/USDC trader for make.fun
btc-race-24h-20261115-0828 (bars-replay/v1, $1,000 paper money).

Strategy: two complementary long entries, one exit discipline.

Entries (flat only, one open position max):
  1. BREAKOUT: the close makes a new 60-minute high (by 0.05%). Catches
     the start of a bounce while it is already moving up.
  2. DEEP DIP: the close is >= 3.0% below the 120-minute high AND the
     5-minute return is positive (the fall has stopped and turned).
     Catches the sharp washout bottoms that a slow downtrend produces.

Exits (while holding, evaluated on every close against the volume-weighted
average entry price, fees included):
  - STOP LOSS: close <= entry * (1 - 0.50%).
  - TRAILING STOP: once the position is +0.40% in profit, sell when the
    close falls 0.50% below the highest close since entry. Lets a big
    bounce run to several percent while banking small ones.
  - TIME STOP: close the position after 480 bars (8 hours) if the
    trailing stop has not fired.
  - RE-ENTRY COOLDOWN: no new entry for 30 bars after an exit, so a
    stop-loss exit is not immediately chased back into the same move.
    Uses the exit sequence already tracked; neutral on the dev window
    (same 8 trades, same PnL).

Sizing: 100% of cash on every entry (the weight cap is 100% of equity).
No new entries after batch 1400, so nothing is left to the end-of-window
flatten except a position the trailing stop is still riding.

Dev-window result (frozen 24h, 2026-11-14 08:28 UTC - 2026-11-15 08:28 UTC,
exact local replay of the harness fill math): net PnL +$42.28 (+4.23%),
max drawdown 1.02%, 4 round trips (3 wins), fees $3.26. Buy-and-hold on
the same window is -$44.01.

Deterministic: no clock, no network, no files, no randomness. The only
state is the close history and the position's entry cost/quantity, both
derived from the batches the harness sends. Two runs on the same data
produce byte-identical replies.

Standard library only. Runs as: python3 -P -s /bot/main.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

# --- strategy parameters (chosen by sweeping the dev window) ---
BREAKOUT_WINDOW = 60        # bars for the breakout high
BREAKOUT_BPS = 5            # new high by this many bps (0.05%)
DIP_WINDOW = 120            # bars for the dip high
DIP_PCT = 0.030             # deep-dip threshold (3.0%)
DIP_CONFIRM_BARS = 5        # 5-minute return must be positive
STOP_LOSS_PCT = 0.005       # -0.50% from entry
TRAIL_ARM_PCT = 0.004       # trailing arms at +0.40%
TRAIL_PCT = 0.005           # sell 0.50% below the peak since entry
MAX_HOLD_BARS = 480         # 8 hours
COOLDOWN_BARS = 30          # no re-entry for 30 bars after an exit
LAST_ENTRY_SEQ = 1400
MAX_SLIPPAGE_BPS = 200
SYMBOL = "CBBTC"


class Bot:
    def __init__(self):
        self.closes = []        # close prices in USD, one per batch
        self.entry_usd = None   # VWAP entry price (cost incl. fees), USD
        self.entry_seq = None
        self.peak_usd = None    # highest close since entry
        self.cost_units = 0     # quote units spent on the current position
        self.qty_units = 0      # asset units held (from fills)
        self.buy_pending = False
        self.last_exit_seq = -10 ** 9
        self.order_no = 0

    def _new_id(self):
        self.order_no += 1
        return "o%d" % self.order_no

    def on_batch(self, state, batch):
        seq = batch["seq"]
        close = int(batch["bars"][0]["c"]) / 1e5
        # Update the position from the fills this batch carries. A buy
        # fill sets (or refreshes) the VWAP entry; a sell fill clears it.
        for fill in batch["fills"]:
            if fill["status"] != "filled":
                continue
            if fill["side"] == "buy":
                self.cost_units += int(fill["notional_quote_units"])
                self.qty_units += int(fill["qty"])
                # VWAP in USD: (cost/1e6 USD) / (qty/1e8 BTC)
                self.entry_usd = self.cost_units * 100.0 / self.qty_units
                if self.entry_seq is None:
                    self.entry_seq = seq
                if self.peak_usd is None:
                    self.peak_usd = self.entry_usd
                self.buy_pending = False
            else:
                self.entry_usd = None
                self.entry_seq = None
                self.peak_usd = None
                self.cost_units = 0
                self.qty_units = 0
                self.last_exit_seq = seq
        self.closes.append(close)

        account = batch["account"]
        cash = int(account["cash_quote_units"])
        qty = 0
        if account["positions"]:
            qty = int(account["positions"][0]["qty"])

        # ---- holding: exits
        if qty > 0 and self.entry_usd is not None:
            if self.peak_usd is None:
                self.peak_usd = self.entry_usd
            if close > self.peak_usd:
                self.peak_usd = close
            entry = self.entry_usd
            sell = False
            if close <= entry * (1 - STOP_LOSS_PCT):
                sell = True
            elif self.peak_usd >= entry * (1 + TRAIL_ARM_PCT) and \
                    close <= self.peak_usd * (1 - TRAIL_PCT):
                sell = True
            elif self.entry_seq is not None and seq - self.entry_seq >= MAX_HOLD_BARS:
                sell = True
            if sell:
                return [{"side": "sell", "client_id": self._new_id(),
                         "symbol": SYMBOL, "qty": str(qty),
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []

        # ---- flat: entries
        if self.buy_pending or qty > 0:
            return []
        if seq >= LAST_ENTRY_SEQ:
            return []
        if seq - self.last_exit_seq < COOLDOWN_BARS:
            return []
        n = len(self.closes)
        if n < DIP_WINDOW + 1:
            return []

        breakout = False
        if n > BREAKOUT_WINDOW:
            high60 = max(self.closes[-BREAKOUT_WINDOW:-1])
            breakout = close >= high60 * (1 + BREAKOUT_BPS / 10000.0)

        deep_dip = False
        high120 = max(self.closes[-DIP_WINDOW:])
        dip = (high120 - close) / high120
        if dip >= DIP_PCT and close > self.closes[-1 - DIP_CONFIRM_BARS]:
            deep_dip = True

        if not (breakout or deep_dip):
            return []
        if cash < 1000000:  # below the $1 minimum notional
            return []
        self.buy_pending = True
        return [{"side": "buy", "client_id": self._new_id(),
                 "symbol": SYMBOL, "notional_quote_units": str(cash),
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]


makefun_bars.run(Bot().on_batch)
