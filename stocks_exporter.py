"""
Prometheus exporter — Stock indices, IBEX/NASDAQ tickers & Fear-Greed Index
Sources:
  - Yahoo Finance (yfinance)   — indices + stocks, ~15min delay
  - feargreedchart.com API     — Fear & Greed Index (stocks), no key needed
"""

import os
import time
import requests
import yfinance as yf
from prometheus_client import start_http_server, Gauge

# ── Config ────────────────────────────────────────────────────────────────────
INTERVAL = int(os.getenv("STOCKS_INTERVAL", "300"))   # 5 min between scrapes
PORT     = int(os.getenv("STOCKS_PORT", "9878"))

# ── Tickers ───────────────────────────────────────────────────────────────────
INDICES = {
    "IBEX_35":  "^IBEX",
    "SP_500":   "^GSPC",
    "NASDAQ":   "^IXIC",
}

IBEX_STOCKS = {
    "IAG":    "IAG.MC",    # Iberia / International Airlines Group
    "Repsol": "REP.MC",
}

NASDAQ_STOCKS = {
    "Apple":     "AAPL",
    "Microsoft": "MSFT",
    "Nvidia":    "NVDA",
    "Amazon":    "AMZN",
    "Alphabet":  "GOOGL",
    "Meta":      "META",
    "Tesla":     "TSLA",
    "GitLab":    "GTLB",
}

ALL_TICKERS = {**INDICES, **IBEX_STOCKS, **NASDAQ_STOCKS}

# ── Prometheus metrics ────────────────────────────────────────────────────────
LABELS = ["symbol", "name", "type", "exchange"]

price           = Gauge("stock_price",             "Current price (or index value)",      LABELS)
change_pct      = Gauge("stock_change_pct",        "Price change % vs previous close",    LABELS)
volume          = Gauge("stock_volume",             "Trading volume (0 for indices)",      LABELS)
market_cap_b    = Gauge("stock_market_cap_billions","Market cap in billions USD",          LABELS)

fear_greed_score = Gauge("market_fear_greed_score",
                         "CNN/Stock Fear & Greed Index (0=Extreme Fear, 100=Extreme Greed)",
                         ["source"])
fear_greed_prev  = Gauge("market_fear_greed_previous",
                         "Fear & Greed Index: previous close value",
                         ["source", "period"])


def classify_ticker(name, symbol):
    if name in INDICES:
        return "index", symbol.replace("^", "").replace(".", "_")
    if name in IBEX_STOCKS:
        return "ibex_stock", "BME"
    return "nasdaq_stock", "NASDAQ"


def fetch_stocks():
    symbols = list(ALL_TICKERS.values())
    try:
        data = yf.download(
            symbols,
            period="2d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )

        for friendly_name, ticker in ALL_TICKERS.items():
            try:
                # yfinance multi-ticker layout
                if len(symbols) > 1:
                    df = data[ticker] if ticker in data.columns.get_level_values(0) else None
                else:
                    df = data

                if df is None or df.empty or len(df) < 1:
                    print(f"  [WARN] No data for {ticker}")
                    continue

                latest = df.iloc[-1]
                prev   = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]

                current_price = float(latest["Close"])
                prev_price    = float(prev["Close"])
                pct_change    = ((current_price - prev_price) / prev_price) * 100 if prev_price else 0.0
                vol           = float(latest.get("Volume", 0) or 0)

                t_type, exchange = classify_ticker(friendly_name, ticker)
                symbol_clean     = ticker.replace("^", "").replace(".", "_")
                label_vals       = [symbol_clean, friendly_name, t_type, exchange]

                price.labels(*label_vals).set(round(current_price, 4))
                change_pct.labels(*label_vals).set(round(pct_change, 4))
                volume.labels(*label_vals).set(vol)

                # Market cap only for individual stocks
                if t_type != "index":
                    try:
                        info   = yf.Ticker(ticker).fast_info
                        mktcap = getattr(info, "market_cap", 0) or 0
                        market_cap_b.labels(*label_vals).set(round(mktcap / 1e9, 2))
                    except Exception:
                        pass

                print(f"  [OK] {friendly_name:12s} ({symbol_clean:8s}) "
                      f"= {current_price:>10.2f}  ({pct_change:+.2f}%)")

            except Exception as e:
                print(f"  [ERR] {ticker}: {e}")

    except Exception as e:
        print(f"[ERR] yfinance batch download failed: {e}")


def fetch_fear_greed():
    """
    Uses feargreedchart.com public API (no key, 5-min cache).
    Endpoint: https://feargreedchart.com/api/?action=all
    """
    url = "https://feargreedchart.com/api/?action=all"
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "stocks-exporter/1.0"})
        r.raise_for_status()
        d = r.json()

        score_now = d["score"]["score"]
        fear_greed_score.labels(source="feargreedchart").set(score_now)

        # Historical snapshots
        for component in d["score"].get("components", []):
            pass  # components are sub-indicators, not time periods

        # The API also returns previous period values in score history if available
        history = d.get("history", [])
        periods = {"yesterday": 1, "1_week_ago": 7, "1_month_ago": 30}
        for label, days_ago in periods.items():
            if len(history) > days_ago:
                val = history[days_ago].get("score", 0)
                fear_greed_prev.labels(source="feargreedchart", period=label).set(val)

        print(f"  [OK] Fear & Greed = {score_now} "
              f"({d['score'].get('label','?')})")

    except Exception as e:
        print(f"  [ERR] Fear & Greed fetch failed: {e}")
        # Fallback: CNN dataviz endpoint (unofficial but widely used)
        try:
            cnn_url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            r2 = requests.get(cnn_url, timeout=10,
                              headers={"User-Agent": "Mozilla/5.0"})
            r2.raise_for_status()
            d2   = r2.json()
            fng  = d2.get("fear_and_greed", {})
            val  = fng.get("score", 0)
            fear_greed_score.labels(source="cnn").set(val)

            # Previous values
            prev_map = {
                "yesterday":   fng.get("previous_close", 0),
                "1_week_ago":  fng.get("previous_1_week", 0),
                "1_month_ago": fng.get("previous_1_month", 0),
            }
            for period, v in prev_map.items():
                if v:
                    fear_greed_prev.labels(source="cnn", period=period).set(v)

            print(f"  [OK] Fear & Greed (CNN fallback) = {val}")
        except Exception as e2:
            print(f"  [ERR] CNN fallback also failed: {e2}")


# ── Main loop ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Starting stocks exporter on port {PORT} — interval {INTERVAL}s")
    start_http_server(PORT)
    while True:
        print("\n── Fetching stocks ──────────────────────────────")
        fetch_stocks()
        print("── Fetching Fear & Greed ────────────────────────")
        fetch_fear_greed()
        print(f"── Done. Sleeping {INTERVAL}s ──────────────────\n")
        time.sleep(INTERVAL)
