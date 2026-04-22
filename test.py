from ib_insync import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# -----------------------------
# 1) INDEX PRICE (works in your setup)
# -----------------------------
index = Index(symbol='N225', exchange='OSE.JPN', currency='JPY')
ib.qualifyContracts(index)

t_idx = ib.reqMktData(index, '', False, False)
ib.sleep(2)

idx_price = t_idx.last or t_idx.close
print("\n=== INDEX ===")
print("Index Price:", idx_price)

# -----------------------------
# 2) NIKKEI 225 INDEX OPTION (OSE) - NO conId
# -----------------------------
opt = Option(
    symbol='N225',
    lastTradeDateOrContractMonth='20260507',  # MAY 08 '26
    strike=59750,
    right='C',
    exchange='OSE.JPN',
    currency='JPY',
    tradingClass='225',
    multiplier='1000',
)

# Try to qualify; if ambiguous, inspect candidates
details = ib.reqContractDetails(opt)
if not details:
    raise Exception("❌ No matching option contract (check expiry/strike/class).")

# Pick the first match (or filter if multiple)
opt = details[0].contract
ib.qualifyContracts(opt)

# -----------------------------
# 3) MARKET DATA
# -----------------------------
t_opt = ib.reqMktData(opt, '', False, False)
ib.sleep(2)

print("\n=== OPTION ===")
print("Bid:", t_opt.bid)
print("Ask:", t_opt.ask)
print("Last:", t_opt.last)

# -----------------------------
# 4) BUY + STOP
# -----------------------------
qty = 1
entry = t_opt.ask

if entry and entry == entry:  # not NaN
    buy = LimitOrder('BUY', qty, entry)
    trade = ib.placeOrder(opt, buy)

    ib.sleep(2)
    print("\nBUY Status:", trade.orderStatus.status)

    # Stop (10% below)
    stop_price = round(entry * 0.9, 0)
    stp = StopOrder('SELL', qty, stop_price)
    ib.placeOrder(opt, stp)

    print("Stop placed at:", stop_price)
else:
    print("❌ No valid option price")

ib.disconnect()