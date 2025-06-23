import ccxt
import time
import requests
import os
from datetime import datetime
from colorama import Fore, init
init(autoreset=True)

API_KEY = os.environ['API_KEY']
SECRET = os.environ['SECRET']
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['CHAT_ID']

FEE = 0.001
MIN_PROFIT_PCT = 0.5
MAX_PROFIT_PCT = 10.0
MIN_LIQUIDITY = 100
TRADE_USD = 100

STABLES = {'USDT', 'USDC'}
BASE_COINS = {'BTC', 'ETH', 'BNB', 'SOL'}

def get_symbol_type(symbol):
    if symbol in STABLES:
        return 'stable'
    elif symbol in BASE_COINS:
        return 'base'
    else:
        return 'alt'

bybit = ccxt.bybit({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'timeout': 15000,
    'options': {'defaultType': 'spot'}
})

markets = bybit.load_markets()
all_symbols = [s for s in markets if '/' in s]

symbol_types = {}
for s in all_symbols:
    base, quote = s.split('/')
    symbol_types[base] = get_symbol_type(base)
    symbol_types[quote] = get_symbol_type(quote)

def fetch_orderbook(symbol):
    try:
        return bybit.fetch_order_book(symbol)
    except:
        return {'asks': [], 'bids': []}

def get_best_price(book, side, amount_needed):
    total = 0
    qty = 0
    for price, volume in book[side]:
        deal = price * volume
        if total + deal >= amount_needed:
            partial = (amount_needed - total) / price
            qty += partial
            total += partial * price
            break
        total += deal
        qty += volume
    if qty == 0:
        return None, 0
    avg_price = total / qty
    return avg_price, total

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'})

def find_triangles():
    results = []
    for stable_in in STABLES:
        for coin in symbol_types:
            if symbol_types[coin] == 'stable':
                continue
            for stable_out in STABLES:
                if stable_in == stable_out:
                    continue

                pair1 = f"{stable_in}/{stable_out}"
                pair2 = f"{coin}/{stable_in}"
                pair3 = f"{coin}/{stable_out}"

                if pair1 not in markets or pair2 not in markets or pair3 not in markets:
                    continue

                book1 = fetch_orderbook(pair1)
                book2 = fetch_orderbook(pair2)
                book3 = fetch_orderbook(pair3)
                if not book1['asks'] or not book2['asks'] or not book3['bids']:
                    continue

                # 1. stable_in → stable_out
                price1, _ = get_best_price(book1, 'asks', TRADE_USD)
                if not price1:
                    continue
                amount_stable_out = TRADE_USD / price1 * (1 - FEE)

                # 2. Покупаем coin за stable_out
                price2, _ = get_best_price(book2, 'asks', amount_stable_out)
                if not price2:
                    continue
                amount_coin = amount_stable_out / price2 * (1 - FEE)

                # 3. Продаем coin за stable_in
                price3, _ = get_best_price(book3, 'bids', amount_coin)
                if not price3:
                    continue
                final_usdt = amount_coin * price3 * (1 - FEE)

                profit = final_usdt - TRADE_USD
                pct = (profit / TRADE_USD) * 100

                if MIN_PROFIT_PCT <= pct <= MAX_PROFIT_PCT:
                    liq = min(
                        book1['asks'][0][0] * book1['asks'][0][1],
                        book2['asks'][0][0] * book2['asks'][0][1],
                        book3['bids'][0][0] * book3['bids'][0][1],
                    )
                    if liq >= MIN_LIQUIDITY:
                        results.append({
                            'route': f"{pair1} → {pair2} → {pair3}",
                            'profit': profit,
                            'pct': pct,
                            'liq': liq,
                        })
    return sorted(results, key=lambda x: -x['pct'])

def run():
    while True:
        print("\033c")
        now = datetime.now().strftime('%H:%M:%S')
        print(f"[{now}] 🔄 Поиск арбитража...\n")
        found = find_triangles()

        if not found:
            print("❌ Возможности не найдены.")
        else:
            print("📈 ТОП-10 маршрутов:")
            for i, r in enumerate(found[:10]):
                print(f"{i+1}. {r['route']}")
                print(f"   🔹 Прибыль: {r['profit']:.2f} USDT | Спред: {r['pct']:.2f}% | Ликвидность: {r['liq']:.0f} USDT\n")
                send_telegram_message(
                    f"<b>{i+1}. {r['route']}</b>\n"
                    f"💰 Прибыль: <b>{r['profit']:.2f} USDT</b>\n"
                    f"📈 Спред: <b>{r['pct']:.2f}%</b>\n"
                    f"💧 Ликвидность: <b>{r['liq']:.0f} USDT</b>"
                )

        print("♻️ Обновление через 10 сек...\n")
        time.sleep(10)

if __name__ == '__main__':
    run()