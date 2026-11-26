
import os
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# PAPER TRADING ONLY
PAPER = True
ENABLE_ORDERS = False

# Budget: ca. 1.000 EUR in USD.
# Konservativer, vorläufiger Wechselkurs-Puffer.
BUDGET_USD = 1150.0

MAX_TOTAL_INVESTED = 0.75
MAX_POSITION_PERCENT = 0.15
MAX_DAILY_LOSS = 0.02
MAX_DRAWDOWN = 0.08

SYMBOLS = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "AMZN",
    "GOOGL", "META", "AVGO", "AMD",
    "JPM", "COST", "LLY"
]


def main():
    key = os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("APCA_API_SECRET_KEY")

    if not key or not secret:
        raise RuntimeError("Alpaca API-Schlüssel fehlen.")

    trading = TradingClient(key, secret, paper=True)
    data = StockHistoricalDataClient(key, secret)

    account = trading.get_account()

    if account.trading_blocked or account.account_blocked:
        raise RuntimeError("Alpaca-Konto ist gesperrt.")

    positions = trading.get_all_positions()

    equity = float(account.equity)
    cash = float(account.cash)

    # Tatsächlich verfügbares Budget auf 1.150 USD begrenzen.
    budget = min(BUDGET_USD, equity)
    invested = sum(float(p.market_value) for p in positions)

    print("PAPER TRADING – NUR ANALYSE")
    print("Zeit:", datetime.now(timezone.utc))
    print(f"Budget: ${budget:.2f}")
    print(f"Kontowert: ${equity:.2f}")
    print(f"Bargeld: ${cash:.2f}")
    print(f"Investiert: ${invested:.2f}")
    print(f"Positionen: {len(positions)}")

    request = StockBarsRequest(
        symbol_or_symbols=SYMBOLS,
        timeframe=TimeFrame.Day,
        start=datetime.now(timezone.utc) - timedelta(days=180),
        end=datetime.now(timezone.utc) - timedelta(minutes=20),
    )

    bars = data.get_stock_bars(request).df

    if bars.empty:
        print("Keine Kursdaten verfügbar.")
        return

    held = {p.symbol for p in positions}

    for symbol in SYMBOLS:
        try:
            df = bars.xs(symbol, level="symbol").sort_index()

            if len(df) < 55:
                continue

            close = df["close"]
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()

            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi = 100 - (100 / (1 + rs))

            price = float(close.iloc[-1])
            current_rsi = float(rsi.iloc[-1])
            momentum = price / float(close.iloc[-21]) - 1

            buy = (
                price > float(ema20.iloc[-1])
                and float(ema20.iloc[-1]) > float(ema50.iloc[-1])
                and 50 < current_rsi < 70
                and momentum > 0
            )

            print(
                f"{symbol}: ${price:.2f}, "
                f"RSI {current_rsi:.1f}, "
                f"Momentum {momentum:.1%}, "
                f"Kaufsignal: {buy}"
            )

            if buy and symbol not in held:
                position_budget = budget * MAX_POSITION_PERCENT
                available_budget = (
                    budget * MAX_TOTAL_INVESTED - invested
                )

                possible = min(
                    position_budget,
                    available_budget,
                    max(0, cash)
                )

                print(
                    f"Mögliches Budget für {symbol}: "
                    f"${possible:.2f}"
                )

        except Exception as error:
            print(f"{symbol}: Analysefehler: {error}")

    print("Analyse abgeschlossen.")
    print("Orders bleiben deaktiviert.")


if __name__ == "__main__":
    main()

