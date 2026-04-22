import argparse

import credentials
from ib_insync import IB, Index, MarketOrder, Option, StopOrder, util


class StrategyLiveFlowTester:
    def __init__(self):
        self.ib = IB()
        self.strikes = None
        self.otm_closest_call = credentials.call_hedge
        self.otm_closest_put = credentials.put_hedge
        self.call_target_price = credentials.call_strike
        self.put_target_price = credentials.put_strike
        self.call_percent = credentials.call_sl
        self.put_percent = credentials.put_sl
        self.call_contract = None
        self.put_contract = None
        self.atm_call_id = None
        self.atm_put_id = None
        self.otm_call_id = None
        self.otm_put_id = None
        self.call_stp_id = None
        self.put_stp_id = None
        self.atm_call_fill = None
        self.atm_put_fill = None
        self.otm_call_fill = None
        self.otm_put_fill = None
        self.atm_call_sl = None
        self.atm_put_sl = None
        self.call_order_placed = False
        self.put_order_placed = False

    def connect(self):
        self.ib.connect(
            host=credentials.host,
            port=credentials.port,
            clientId=214,
            timeout=60,
        )
        print(f"Connected: {self.ib.isConnected()}")

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()
            print("Disconnected.")

    def hedges_enabled(self):
        return (
            (credentials.active_close_hedges and not credentials.close_hedges)
            or (credentials.close_hedges and credentials.active_close_hedges)
        )

    def build_option_contract(self, strike, right):
        return Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=strike,
            right=right,
            exchange=credentials.exchange,
            currency=credentials.currency,
            multiplier="100",
            tradingClass=credentials.tradingClass,
        )

    def fetch_strikes(self):
        contract = Index(credentials.instrument, credentials.exchange, credentials.currency)
        self.ib.qualifyContracts(contract)
        self.ib.reqMarketDataType(credentials.data_type)
        chains = self.ib.reqSecDefOptParams(contract.symbol, "", contract.secType, contract.conId)
        chain = next(
            c for c in chains
            if c.tradingClass == credentials.tradingClass and c.exchange == credentials.exchange
        )
        return chain.strikes

    def current_price(self):
        contract = Index(credentials.instrument, credentials.exchange, credentials.currency)
        ticker = self.ib.reqMktData(contract)
        self.ib.sleep(2)

        while util.isNan(ticker.last):
            self.ib.sleep(1)

        if ticker.last and ticker.last > 0:
            return ticker.last
        return ticker.close

    def get_latest_premium_price(self, strike, right):
        contract = self.build_option_contract(strike, right)
        self.ib.qualifyContracts(contract)
        self.ib.reqMarketDataType(credentials.data_type)
        ticker = self.ib.reqMktData(contract, "", snapshot=True)
        self.ib.sleep(5)
        return {
            "bid": ticker.bid,
            "ask": ticker.ask,
            "last": ticker.last,
            "mid": (ticker.bid + ticker.ask) / 2 if ticker.bid and ticker.ask else None,
        }

    def place_market_order(self, contract, qty, side):
        order = MarketOrder(side, qty)
        trade = self.ib.placeOrder(contract, order)
        print(contract)
        print(order)
        print("waiting for order to be placed")

        seconds = 1
        while True:
            if trade.isDone():
                fill_price = trade.orderStatus.avgFillPrice
                order_id = trade.order.orderId
                print("Order placed successfully")
                print("Order ID:", order_id)
                print("Fill price:", fill_price)
                return trade, fill_price, order_id

            print(f"Waiting...{contract.right}... {seconds} seconds")
            seconds += 1
            if seconds == 10:
                return trade, 0, trade.order.orderId
            self.ib.sleep(1)

    def place_stp_order(self, contract, side, quantity, sl):
        details = self.ib.reqContractDetails(contract)
        if not details:
            raise ValueError("Invalid contract for stop order.")

        qualified_contract = details[0].contract
        stop_order = StopOrder(side, quantity, round(sl, 1))
        trade = self.ib.placeOrder(qualified_contract, stop_order)
        self.ib.sleep(2)
        print(f"done {trade.orderStatus.status}")
        return trade.order.orderId

    def cancel_order(self, order_id):
        orders = self.ib.reqOpenOrders()
        for trade in orders:
            if trade.orderStatus.orderId == order_id:
                self.ib.cancelOrder(trade.orderStatus)

    def prepare_session(self):
        self.strikes = self.fetch_strikes()
        current_price = int(self.current_price())
        closest_strike = min(self.strikes, key=lambda x: abs(x - current_price))

        if credentials.calc_values:
            self.otm_closest_call = closest_strike + (credentials.OTM_CALL_HEDGE * 5)
            self.otm_closest_put = closest_strike - (credentials.OTM_PUT_HEDGE * 5)
            self.call_target_price = closest_strike
            if credentials.ATM_CALL > 0:
                self.call_target_price += 5 * credentials.ATM_CALL
            self.put_target_price = closest_strike
            if credentials.ATM_CALL > 0:
                self.put_target_price -= 5 * credentials.ATM_CALL

        return {
            "current_price": current_price,
            "closest_strike": closest_strike,
            "call_target_price": self.call_target_price,
            "put_target_price": self.put_target_price,
            "otm_closest_call": self.otm_closest_call,
            "otm_closest_put": self.otm_closest_put,
        }

    def inspect_contract(self, label, strike, right):
        contract = self.build_option_contract(strike, right)
        qualified = self.ib.qualifyContracts(contract)
        premium = self.get_latest_premium_price(strike, right)
        print(f"\n[{label}]")
        print(f"Contract: {contract}")
        print(f"Qualified: {bool(qualified)}")
        print(f"Quote: bid={premium['bid']} ask={premium['ask']} last={premium['last']} mid={premium['mid']}")
        return contract, premium

    def place_hedge_orders(self):
        call_contract = self.build_option_contract(self.otm_closest_call, "C")
        put_contract = self.build_option_contract(self.otm_closest_put, "P")
        self.ib.qualifyContracts(call_contract)
        self.ib.qualifyContracts(put_contract)

        print("\nPlacing hedge CALL...")
        _, self.otm_call_fill, self.otm_call_id = self.place_market_order(
            contract=call_contract,
            qty=credentials.call_hedge_quantity,
            side="BUY",
        )

        print("Placing hedge PUT...")
        _, self.otm_put_fill, self.otm_put_id = self.place_market_order(
            contract=put_contract,
            qty=credentials.put_hedge_quantity,
            side="BUY",
        )

    def place_atm_put_order(self):
        premium_price = self.get_latest_premium_price(self.put_target_price, "P")
        self.put_contract = self.build_option_contract(self.put_target_price, "P")
        qualified = self.ib.qualifyContracts(self.put_contract)
        if not qualified:
            raise ValueError("Failed to qualify ATM PUT contract.")

        print(f"ATM PUT last price: {premium_price['last']}")
        _, self.atm_put_fill, self.atm_put_id = self.place_market_order(
            contract=self.put_contract,
            qty=credentials.put_position,
            side="SELL",
        )
        self.put_order_placed = True
        self.atm_put_sl = self.atm_put_fill * (1 + (self.put_percent / 100))
        self.put_stp_id = self.place_stp_order(
            contract=self.put_contract,
            side="BUY",
            quantity=credentials.put_position,
            sl=self.atm_put_sl,
        )

    def place_atm_call_order(self):
        premium_price = self.get_latest_premium_price(self.call_target_price, "C")
        self.call_contract = self.build_option_contract(self.call_target_price, "C")
        qualified = self.ib.qualifyContracts(self.call_contract)
        if not qualified:
            raise ValueError("Failed to qualify ATM CALL contract.")

        print(f"ATM CALL last price: {premium_price['last']}")
        _, self.atm_call_fill, self.atm_call_id = self.place_market_order(
            contract=self.call_contract,
            qty=credentials.call_position,
            side="SELL",
        )
        self.call_order_placed = True
        self.atm_call_sl = self.atm_call_fill * (1 + (self.call_percent / 100))
        self.call_stp_id = self.place_stp_order(
            contract=self.call_contract,
            side="BUY",
            quantity=credentials.call_position,
            sl=self.atm_call_sl,
        )

    def close_call(self):
        if not self.call_order_placed:
            return

        contract = self.build_option_contract(self.call_target_price, "C")
        self.ib.qualifyContracts(contract)
        self.place_market_order(contract=contract, qty=credentials.call_position, side="BUY")
        self.call_order_placed = False

    def close_put(self):
        if not self.put_order_placed:
            return

        contract = self.build_option_contract(self.put_target_price, "P")
        self.ib.qualifyContracts(contract)
        self.place_market_order(contract=contract, qty=credentials.put_position, side="BUY")
        self.put_order_placed = False

    def close_open_hedges(self):
        if self.otm_call_id is not None:
            call_contract = self.build_option_contract(self.otm_closest_call, "C")
            self.ib.qualifyContracts(call_contract)
            self.place_market_order(
                contract=call_contract,
                qty=credentials.call_hedge_quantity,
                side="SELL",
            )

        if self.otm_put_id is not None:
            put_contract = self.build_option_contract(self.otm_closest_put, "P")
            self.ib.qualifyContracts(put_contract)
            self.place_market_order(
                contract=put_contract,
                qty=credentials.put_hedge_quantity,
                side="SELL",
            )

    def cleanup_orders_and_positions(self, close_hedges):
        if self.call_stp_id:
            self.cancel_order(self.call_stp_id)
        if self.put_stp_id:
            self.cancel_order(self.put_stp_id)
        if self.atm_call_id:
            self.cancel_order(self.atm_call_id)
        if self.atm_put_id:
            self.cancel_order(self.atm_put_id)

        self.close_call()
        self.close_put()

        if close_hedges:
            self.close_open_hedges()

    def run_test(self, place_orders, cleanup):
        self.connect()
        try:
            session = self.prepare_session()
            print("\n=== SESSION CALCULATION ===")
            for key, value in session.items():
                print(f"{key}: {value}")

            self.inspect_contract("ATM PUT", self.put_target_price, "P")
            self.inspect_contract("ATM CALL", self.call_target_price, "C")

            hedges = self.hedges_enabled()
            if hedges:
                self.inspect_contract("HEDGE PUT", self.otm_closest_put, "P")
                self.inspect_contract("HEDGE CALL", self.otm_closest_call, "C")

            if not place_orders:
                print("\nDry run complete. No orders were sent.")
                return

            print("\n=== LIVE ORDER TEST ===")
            if hedges:
                self.place_hedge_orders()

            self.place_atm_put_order()
            self.place_atm_call_order()

            print("\n=== ORDER SUMMARY ===")
            print(f"atm_put_id={self.atm_put_id} fill={self.atm_put_fill} sl={self.atm_put_sl} stop_id={self.put_stp_id}")
            print(f"atm_call_id={self.atm_call_id} fill={self.atm_call_fill} sl={self.atm_call_sl} stop_id={self.call_stp_id}")
            if hedges:
                print(f"otm_put_id={self.otm_put_id} fill={self.otm_put_fill}")
                print(f"otm_call_id={self.otm_call_id} fill={self.otm_call_fill}")

            if cleanup:
                print("\nCleaning up test orders and positions...")
                self.cleanup_orders_and_positions(close_hedges=hedges)
                print("Cleanup complete.")
            else:
                print("\nOrders/positions left open because cleanup was disabled.")
        finally:
            self.disconnect()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Live flow test for NIKKIE225 strategy and broker wiring.",
    )
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Actually place the hedge and ATM orders using the same logic as main.py.",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep any placed test orders/positions open after the script finishes.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    tester = StrategyLiveFlowTester()
    tester.run_test(
        place_orders=args.place_orders,
        cleanup=not args.no_cleanup,
    )


if __name__ == "__main__":
    main()
