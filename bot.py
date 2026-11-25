import os
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# SICHERHEIT: Ausschließlich Alpaca Paper Trading
PAPER = True
ENABLE_ORDERS = os.getenv("ENABLE_PAPER_ORDERS", "false").lower() == "true"

# Startkapital ungefähr 1.000 Euro
MAX_POSITIONS = 6
MAX_POSITION_PERCENT = 0.15
MAX_TOTAL_INVESTED = 0.75

# Große, liquide US-Aktien und ETFs
SYMBOLS = [
    "SPY", "QQQ", "IWM", "DIA", "AAPL",
    "MSFT", "NVDA", "AMZN", "GOOGL", "META",
    "AVGO", "AMD", "JPM", "COST", "LLY"
]


def main():
    key = os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("APCA_API_SECRET_KEY")

    if not key or not secret:
        raise RuntimeError("Alpaca API-Schlüssel fehlen.")

    trading = TradingClient(key, secret, paper=PAPER)
    data = StockHistoricalDataClient(key, secret)

    account = trading.get_account()

    if account.trading_blocked or account.account_blocked:
        print("Konto ist für den Handel gesperrt. Abbruch.")
        return

    equity = float(account.equity)
    cash = float(account.cash)

    positions = trading.get_all_positions()
    held = {p.symbol: p for p in positions}

    invested = sum(float(p.market_value) for p in positions)
    print(f"Zeit: {datetime.now(timezone.utc)}")
    print(f"Kontowert: ${equity:.2f}")
    print(f"Bargeld: ${cash:.2f}")
    print(f"Investiert: ${invested:.2f}")
    print(f"Positionen: {len(positions)}")
    print(f"Ordermodus aktiviert: {ENABLE_ORDERS}")

    request = StockBarsRequest(
        symbol_or_symbols=SYMBOLS,
        timeframe=TimeFrame.Day,
        start=datetime.now(timezone.utc) - timedelta(days=180),
        end=datetime.now(timezone.utc) - timedelta(minutes=20),
    )

    bars = data.get_stock_bars(request).df

    if bars.empty:
        print("Keine Kursdaten erhalten.")
        return

    signals = {}

    for symbol in SYMBOLS:
        try:
            df = bars.xs(symbol, level="symbol").copy()
            df = df.sort_index()

            if len(df) < 55:
                continue

            close = df["close"]
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()

            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, pd.NA)
            rsi = 100 - (100 / (1 + rs))

            price = float(close.iloc[-1])
            momentum = price / float(close.iloc[-21]) - 1
            current_rsi = float(rsi.iloc[-1])

            buy_signal = (
                price > float(ema20.iloc[-1])
                and float(ema20.iloc[-1]) > float(ema50.iloc[-1])
                and 50 < current_rsi < 70
                and momentum > 0
            )

            sell_signal = (
                price < float(ema20.iloc[-1])
                or current_rsi < 40
            )

            signals[symbol] = (buy_signal, sell_signal, price)

            print(
                f"{symbol}: Kurs ${price:.2f}, "
                f"RSI {current_rsi:.1f}, "
                f"Momentum {momentum:.1%}"
            )

        except Exception as error:
            print(f"{symbol}: Daten konnten nicht ausgewertet werden: {error}")

    # Bestehende Positionen prüfen
    for symbol, position in held.items():
        if symbol not in signals:
            continue

        _, sell_signal, _ = signals[symbol]

        if sell_signal:
            print(f"VERKAUFSSIGNAL: {symbol}")

            if ENABLE_ORDERS:
                trading.submit_order(
                    MarketOrderRequest(
                        symbol=symbol,
                        qty=float(position.qty),
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY,
                    )
                )

    # Neue Kaufgelegenheiten suchen
    if len(held) >= MAX_POSITIONS:
        print("Maximale Anzahl an Positionen erreicht.")
        return

    budget_per_position = equity * MAX_POSITION_PERCENT
    max_total = equity * MAX_TOTAL_INVESTED

    for symbol in SYMBOLS:
        if symbol in held or symbol not in signals:
            continue

        buy_signal, _, price = signals[symbol]

        if not buy_signal:
            continue

        if len(held) >= MAX_POSITIONS:
            break

        available_room = max_total - invested
        order_value = min(budget_per_position, available_room, cash * 0.95)

        if order_value < 20:
            print("Nicht genügend freies Budget.")
            break

        quantity = round(order_value / price, 4)

        if quantity <= 0:
            continue

        print(f"KAUFSIGNAL: {symbol}, ungefähr ${order_value:.2f}")

        if ENABLE_ORDERS:
            trading.submit_order(
                MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
            )

            cash -= order_value
            invested += order_value
            held[symbol] = True

    print("Analyse abgeschlossen.")


if __name__ == "__main__":
    main()
