# Adaptive options engine

Paper-only Monday helper for one SPY iron condor. It does not place live trades and it is not financial advice.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --dry-run
```

Run it from this directory. The default path does not call Tradier, Alpaca, or Finnhub.

## Environment

Copy `.env.example` to `.env`. Leave a value blank to use the default. Do not put tokens in source files.

- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` — paper account only
- `ALPACA_PAPER` — default true. The client still hardcodes `paper=True`
- `TRADIER_API_TOKEN`, `TRADIER_SANDBOX` — chain data. Sandbox default false
- `FINNHUB_API_KEY` — optional earnings check. Blank skips it
- `UNDERLYING` — default SPY
- `TARGET_DELTA` — short-strike absolute delta, default 0.16 (the example arm is a 0.15-delta iron condor)
- `MAX_CONTRACTS` — default 1
- `MIN_DTE` — default 7. The Monday job still uses the coming Friday weekly
- `EXECUTE` — default false

## Dry-run and EXECUTE

`python main.py` and `python main.py --dry-run` are dry. They run the New York Monday gate, the CPI/FOMC list, the bandit, and print the 4-leg credit when the chain is already in hand. They do not send an order and do not sleep-loop.

`EXECUTE=true` submits one paper limit iron condor at the net credit (Alpaca's multi-leg price is negative for a credit). `--monitor` with `EXECUTE=true` then polls every 60 seconds. The exit rule closes at 50% of the max credit, or when the credit loss reaches 200% of the credit received. Dry-run prints that rule once.

**EXECUTE=true sends paper orders.** The default is dry-run and sends nothing. Do not turn it on until you mean to submit. It never switches the broker to live.

Pass `--realized-pnl 1.25` to record a pnl for the arm just chosen. The program does not invent a fill.

## Headless

`python main.py --headless` takes no input and does not need a terminal. It appends to `logs/engine.log`. The clock is America/New_York.

- Monday 9:30: the weekly entry pipeline
- Every other check: one pass of the 50% profit / 200% stop rule
- Weekdays 9:30–16:00 ET: sleep 60 seconds
- Market closed: sleep until the next 9:30 open

`python main.py --headless --once` is one dry pass and exits. It does not call the network, even if `EXECUTE=true`.

`python main.py --backtest --data-dir /your/drive` stops with `data directory not available yet`. No sample files are read. The drive layout is not guessed here.

## Restart on reboot

This unit is an example. It is not installed here. On your machine, save it as `/etc/systemd/system/adaptive-options.service`, then `sudo systemctl enable --now adaptive-options.service`. Enabling it is what starts the process again after a reboot. `Restart=on-failure` brings it back if the process crashes.

```
[Unit]
Description=Adaptive options paper engine
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/adaptive_options_engine
ExecStart=/opt/adaptive_options_engine/.venv/bin/python main.py --headless
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Leave `EXECUTE` unset in the unit. `EXECUTE=true` there sends paper orders at Monday 9:30 and can close them from the exit check. The client stays `paper=True`.

## Dates you must edit

`CPI_FOMC_DATES` in `adapters/macro_news.py` ships with placeholders. Change those dates before you rely on the macro gate. Finnhub, when a key is set, also blocks same-day earnings for SPY and QQQ. If that call fails, the run continues on the date list.

## Paper only

No live money. No market orders. No short stock. Orders go out only when `EXECUTE=true`, and only through the paper client.
