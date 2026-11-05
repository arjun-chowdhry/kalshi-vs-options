# Kalshi vs options

Does Kalshi's price for "S&P 500 above X at 4pm today" agree with the probability implied by
same-day SPX option prices, and does any gap survive Kalshi's fees and the bid-ask spread?

Work in progress. Milestone 1 (data feasibility) is in [docs/FEASIBILITY.md](docs/FEASIBILITY.md).
Read-only: public market data only, no orders, no keys.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts\snapshot.py       # during market hours: save + report
.venv\Scripts\python.exe scripts\fit_snapshot.py   # re-fit the latest saved snapshot
```
