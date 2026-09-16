# perp-funding-tracker

Personal CLI tool I use to watch funding rates on perpetual contracts across multiple venues and run simulated delta-neutral carry positions.

I got tired of clicking through exchange UIs and wanted a fast terminal view of annualized funding APRs plus a lightweight paper-portfolio runner to see how funding harvest strategies perform with real fees and rebalancing drag.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/username/perp-funding-tracker.git
cd perp-funding-tracker
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

Fetch latest funding rates across tracked venues:

```bash
perp-tracker rates --symbols BTC,ETH,SOL
```

Filter for APR spreads above a threshold:

```bash
perp-tracker arb --min-apr 15.0
```

Poll continuously and log snapshots into local SQLite database:

```bash
perp-tracker collect --interval 300
```

Start a simulated delta-neutral carry position:

```bash
perp-tracker sim open --symbol ETH --size 5000 --long spot --short binance
```

View paper trading game stats and realized yields:

```bash
perp-tracker sim stats
```

## License

MIT

<!-- updated: 2026-09-16 -->
