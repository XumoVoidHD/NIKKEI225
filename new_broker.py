import asyncio
import time

import pytz
import datetime as dt
import credentials

from ib_insync import *
import pandas as pd


#util.logToConsole('DEBUG')

class IBTWSAPI:

    def __init__(self, creds: dict):

        self.client = None
        self.CREDS = creds

    def _round_stop_price(self, price):
        return int(round(price / 5.0) * 5)

    def _resolve_option_contract(self, symbol: str, expiry: str, strike: float, right: str,
                                 exchange: str = credentials.exchange):
        contract = Option(
            symbol=symbol,
            lastTradeDateOrContractMonth=expiry,
            strike=strike,
            right=right,
            exchange=exchange,
            currency=credentials.currency,
            multiplier=credentials.multiplier,
            tradingClass=credentials.tradingClass
        )
        details = self.client.reqContractDetails(contract)
        if not details:
            raise ValueError(
                f"Unable to resolve option contract: symbol={symbol}, expiry={expiry}, "
                f"strike={strike}, right={right}, exchange={exchange}, "
                f"tradingClass={credentials.tradingClass}, multiplier={credentials.multiplier}"
            )
        return details[0].contract

    def _create_contract(self, contract: str, symbol: str, exchange: str, expiry: str = ..., strike: int = ...,
                         right: str = ...):
        """
        Creates contract object for api\n
        """

        if contract == "stocks":
            return Stock(symbol=symbol, exchange=exchange, currency=credentials.currency)

        elif contract == "options":
            return self._resolve_option_contract(
                symbol=symbol,
                expiry=expiry,
                strike=strike,
                right=right,
                exchange=exchange
            )

        elif contract == "futureContracts":
            return ContFuture(symbol=symbol, exchange=exchange, currency=credentials.currency)

    async def connect(self) -> bool:
        """
        Connect the system with TWS account\n
        """
        # try:
        host, port = credentials.host, credentials.port
        self.client = IB()
        self.ib = self.client
        self.client.connect(host=host, port=port, clientId=self.CREDS["client_id"], timeout=60)
        print("Connected")

    def is_connected(self) -> bool:
        """
        Get the connection status\n
        """
        return self.client.isConnected()

    def get_account_info(self):
        """
        Returns connected account info\n
        """
        account_info = self.client.accountSummary()
        return account_info

    def get_account_balance(self) -> float:
        """
        Returns account balance\n
        """
        for acc in self.get_account_info():
            if acc.tag == "AvailableFunds":
                return float(acc.value)

    async def get_positions(self):
        return self.client.positions()

    async def get_open_orders(self):
        x = self.client.reqOpenOrders()
        self.client.sleep(7)
        return x

    async def close_all_open_orders(self):
        open_orders = self.client.reqOpenOrders()
        for order in open_orders:
            self.client.cancelOrder(order=order.orderStatus)

    async def get_contract_info(self, contract: str, symbol: str, exchange: str) -> dict:
        """
        Returns info of the contract\n
        """
        c = self._create_contract(contract=contract, symbol=symbol, exchange=exchange)
        if contract in ["options"]:
            c.strike = ""
            c.lastTradeDateOrContractMonth = ""

        contract_info = self.client.reqContractDetails(contract=c)

        return {
            "contract_obj": contract_info[0].contract,
            "expiry": contract_info[0].contract.lastTradeDateOrContractMonth
        }

    async def get_expiries_and_strikes(self, technology: str, ticker: str) -> dict:
        """
        """
        # Creating contract
        if technology.lower() == "options":
            c = Option()
        else:
            c = FuturesOption()
        c.symbol = ticker
        c.strike = ""
        c.lastTradeDateOrContractMonth = ""
        contract_info = self.client.reqContractDetails(contract=c)
        # print(contract_info)

        ens = {}
        for contractDetails in contract_info:
            # print(contractDetails.contract.strike, contractDetails.contract.lastTradeDateOrContractMonth, contractDetails.contract.exchange, contractDetails.contract.symbol, contractDetails.contract.right)
            s_exp = contractDetails.contract.lastTradeDateOrContractMonth
            exp = dt.date(int(s_exp[:4]), int(s_exp[4:6]), int(s_exp[-2:]))
            strike = float(contractDetails.contract.strike)

            if exp not in ens: ens[exp] = []
            if strike not in ens[exp]: ens[exp].append(strike)
        current_datetime = dt.datetime.now(pytz.timezone("UTC"))
        return {k: sorted(ens[k]) for k in sorted(ens.keys()) if k > current_datetime.date()}

    async def fetch_strikes(self, symbol, exchange, secType='STK'):
        """ STK: Stocks like AAPL
            IND: SPX and stuff
        """

        if secType == 'IND':
            contract = Index(symbol, exchange, credentials.currency)

        elif secType == 'STK':
            contract = Stock(symbol, exchange, credentials.currency)
        else:
            raise ValueError(f"Unsupported secType: {secType}. Use 'IND' or 'STK'.")

        qc = self.client.qualifyContracts(contract)

        self.client.reqMarketDataType(4)

        chains = self.client.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
        chain = next(c for c in chains if c.tradingClass == credentials.tradingClass and c.exchange == exchange)
        strikes = chain.strikes

        return strikes

    async def place_market_order(self, contract, qty, side):
        if isinstance(contract, Option):
            details = self.client.reqContractDetails(contract)
            if details:
                contract = details[0].contract
        buy_order = MarketOrder(side, qty)
        buy_trade = self.client.placeOrder(contract, buy_order)
        n = 1
        while True:
            if buy_trade.isDone():
                fill_price = buy_trade.orderStatus.avgFillPrice
                order_id = buy_trade.order.orderId
                return buy_trade, fill_price, order_id
            else:
                n += 1
                if n == 10:
                    return 0, 0, buy_trade.order.orderId
                await asyncio.sleep(1)

    async def current_price(self, symbol, exchange=credentials.exchange):
        spx_contract = Index(symbol, exchange, credentials.currency)

        market_data = self.client.reqMktData(spx_contract)
        self.ib.sleep(2)

        while util.isNan(market_data.last):
            self.ib.sleep(3)
        if market_data.close > 0:
            return market_data.last
        else:
            return None

    async def get_stock_price(self, symbol, exchange=credentials.exchange):
        stock_contract = Stock(symbol, exchange, credentials.currency)
        self.client.qualifyContracts(stock_contract)
        self.client.reqMarketDataType(4)  # Use frozen or delayed market data if live is unavailable

        ticker = self.client.reqMktData(stock_contract, '', snapshot=True)
        while util.isNan(ticker.last):
            await asyncio.sleep(0.1)

        if ticker.last > 0:
            return ticker.last
        else:
            return None

    async def get_option_chain(self, symbol: str, exp_list: list) -> dict:
        """
        """
        exps = {}
        df = pd.DataFrame(columns=['strike', 'kind', 'close', 'last'])
        self.client.reqMarketDataType(1)
        for i in exp_list:
            cds = self.client.reqContractDetails(Option(symbol, i, exchange=credentials.exchange))
            # print(cds)
            options = [cd.contract for cd in cds]
            # print(options)
            l = []
            for x in options:
                # print(x)
                contract = Option(symbol, i, x.strike, x.right, credentials.exchange,
                                  currency=credentials.currency)
                # print(contract)
                snapshot = self.client.reqMktData(contract, "", True, False)
                l.append([x.strike, x.right, snapshot])
            # print(snapshot)

            while util.isNan(snapshot.bid):
                self.client.sleep()
            for ii in l:
                df = df.append(
                    {'strike': ii[0], 'kind': ii[1], 'close': ii[2].close, 'last': ii[2].last, 'bid': ii[2].bid,
                     'ask': ii[2].ask, 'mid': (ii[2].bid + ii[2].ask) / 2, 'volume': ii[2].volume}, ignore_index=True)
                exps[i] = df

        return exps

    async def get_candle_data(self, contract: str, symbol: str, timeframe: str, period: str = '2d',
                              exchange: str = credentials.exchange) -> pd.DataFrame:
        """
        Returns candle data of a ticker\n
        """
        _tf = {
            's': "sec",
            'm': "min",
            "h": "hour"
        }

        # Creating contract
        c = self._create_contract(contract=contract, symbol=symbol, exchange=exchange)

        # Parsing timeframe
        timeframe = timeframe[:-1] + ' ' + _tf[timeframe[-1]] + ('s' if timeframe[:-1] != '1' else '')

        # Parsing period
        period = ' '.join([i.upper() for i in period])

        data = self.client.reqHistoricalData(c, '', barSizeSetting=timeframe, durationStr=period, whatToShow='MIDPOINT',
                                             useRTH=True)
        df = pd.DataFrame([(
            {
                "datetime": i.date,
                "open": i.open,
                "high": i.high,
                "low": i.low,
                "close": i.close,
            }
        ) for i in data])
        df.set_index('datetime', inplace=True)
        return df

    async def place_order(
            self,
            contract: str,
            symbol: str,
            side: str,
            quantity: int,
            order_type: str = "MARKET",
            price: float = ...,
            exchange: str = credentials.exchange,
    ) -> dict:
        """
        Places order in TWS account\n
        """

        # Creating contract
        c = self._create_contract(contract=contract, symbol=symbol, exchange=exchange)

        # Parsing order type
        if order_type.upper() == "MARKET":
            order = MarketOrder(action=side.upper(), totalQuantity=quantity)
        elif order_type.upper() == "LIMIT":
            order = LimitOrder(action=side.upper(), totalQuantity=quantity, lmtPrice=price)
        elif order_type.upper() == "STOP":
            order = StopOrder(action=side.upper(), totalQuantity=quantity, stopPrice=price)

        order_info = self.client.placeOrder(contract=c, order=order)
        return order_info

    async def simple_order(self, c, order):
        return self.client.placeOrder(c, order)

    async def place_bracket_order(
            self,
            symbol: str,
            quantity: int,
            price: float = ...,
            stoploss: float = None,
            targetprofit: float = None,
            expiry: str = None,
            strike: float = None,
            right: str = None,
            trailingpercent: float = False,
            convert_to_mkt_order_in: int = 0
    ) -> dict:
        get_exit_side = "BUY"
        c = self._create_contract(contract="options", symbol=symbol, exchange=credentials.exchange, expiry=expiry, strike=strike,
                                  right=right)

        entry_order_info, stoploss_order_info, targetprofit_order_info = None, None, None
        parent_id = self.client.client.getReqId()

        en_order = LimitOrder(action="SELL", totalQuantity=quantity, lmtPrice=price)
        await asyncio.sleep(5)
        en_order.orderId = parent_id
        en_order.transmit = False

        def create_trailing_stop(quantity, parent_id=None):
            sl_order = Order()
            sl_order.action = get_exit_side
            sl_order.totalQuantity = quantity
            sl_order.orderType = "TRAIL"
            sl_order.trailingPercent = trailingpercent
            if parent_id:
                sl_order.parentId = parent_id
            sl_order.transmit = True
            return sl_order

        if trailingpercent:
            sl_order = create_trailing_stop(quantity, en_order.orderId)
        elif stoploss:
            sl_order = StopOrder(action=get_exit_side, totalQuantity=quantity, stopPrice=stoploss)
            sl_order.transmit = True

        entry_order_info = self.client.placeOrder(contract=c, order=en_order)
        self.client.sleep(1)
        if stoploss or trailingpercent:
            stoploss_order_info = self.client.placeOrder(contract=c, order=sl_order)
            n = 0
            while True:
                if entry_order_info.isDone():
                    fill_price = entry_order_info.orderStatus.avgFillPrice
                    return {
                        "parent_id": parent_id,
                        "entry": entry_order_info,
                        "stoploss": stoploss_order_info,
                        "targetprofit": targetprofit_order_info,
                        "contract": c,
                        "order": sl_order,
                        "avgFill": fill_price,
                        "order_info": entry_order_info
                    }
                elif convert_to_mkt_order_in > 0 and n >= convert_to_mkt_order_in:  # Modified condition
                    market_order = MarketOrder(action="SELL", totalQuantity=quantity)
                    market_order.orderId = self.client.client.getReqId()
                    market_order.transmit = True

                    await self.cancel_order(parent_id)
                    self.client.sleep(5)

                    entry_order_info = self.client.placeOrder(contract=c, order=market_order)
                    self.client.sleep(5)

                    if entry_order_info.isDone():
                        fill_price = entry_order_info.orderStatus.avgFillPrice
                        # Place trailing stop after market order fills
                        trailing_stop = create_trailing_stop(quantity)
                        stoploss_order_info = self.client.placeOrder(contract=c, order=trailing_stop)

                        return {
                            "parent_id": parent_id,
                            "entry": entry_order_info,
                            "stoploss": stoploss_order_info,
                            "targetprofit": targetprofit_order_info,
                            "contract": c,
                            "order": trailing_stop,
                            "avgFill": fill_price,
                            "order_info": entry_order_info
                        }
                else:
                    n += 1
                    await asyncio.sleep(1)
        else:
            return None

    async def cancel_order(self, order_id: int) -> None:
        """
        Cancel open order\n
        """
        orders = self.client.reqOpenOrders()
        for order in orders:
            if order.orderStatus.orderId == order_id:
                self.client.cancelOrder(order=order.orderStatus)

    async def check_positions(self):
        x = await self.get_positions()
        return x

    async def cancel_hedge(self):
        positions = await self.get_positions()
        for position in positions:
            if position.position > 0:
                action = "SELL"
                quantity = abs(position.position)
                contract = Option(
                    symbol=position.contract.symbol,
                    lastTradeDateOrContractMonth=position.contract.lastTradeDateOrContractMonth,
                    strike=position.contract.strike,
                    right=position.contract.right,
                    exchange=credentials.exchange,
                    currency=credentials.currency,
                    multiplier=credentials.multiplier,
                    tradingClass=credentials.tradingClass
                )
                try:
                    buy_order = MarketOrder(action, quantity)
                    buy_trade = self.client.placeOrder(contract, buy_order)

                    self.client.sleep(1)
                except Exception as e:
                    raise e
                # await self.place_market_order(contract=contract, qty=quantity, side=action)
                print(f"Position closed: {position.contract.localSymbol}")

    async def cancel_call(self, hedge_strike, position_strike, close_hedge):
        hedge_contract = Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=hedge_strike,
            right="C",
            exchange=credentials.exchange,
            currency=credentials.currency,
            multiplier=credentials.multiplier,
            tradingClass=credentials.tradingClass
        )
        contract = Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=position_strike,
            right="C",
            exchange=credentials.exchange,
            currency=credentials.currency,
            multiplier=credentials.multiplier,
            tradingClass=credentials.tradingClass
        )

        await self.place_market_order(contract=contract, qty=credentials.call_position, side="BUY")
        print("ATM call position closed")
        if close_hedge:
            await self.place_market_order(contract=hedge_contract, qty=credentials.call_hedge_quantity, side="SELL")
            print("Call hedge closed")

    async def cancel_put(self, hedge_strike, position_strike, close_hedge):
        hedge_contract = Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=hedge_strike,
            right="P",
            exchange=credentials.exchange,
            currency=credentials.currency,
            multiplier=credentials.multiplier,
            tradingClass=credentials.tradingClass
        )
        contract = Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=position_strike,
            right="P",
            exchange=credentials.exchange,
            currency=credentials.currency,
            multiplier=credentials.multiplier,
            tradingClass=credentials.tradingClass
        )

        await self.place_market_order(contract=contract, qty=credentials.put_position, side="BUY")
        print("ATM put position closed")
        if close_hedge:
            await self.place_market_order(contract=hedge_contract, qty=credentials.put_hedge_quantity, side="SELL")
            print("Put hedge closed")

    async def cancel_positions(self):
        positions = await self.get_positions()
        for position in positions:
            if position.position < 0:
                action = "BUY"
                quantity = abs(position.position)
                contract = Option(
                    symbol=position.contract.symbol,
                    lastTradeDateOrContractMonth=position.contract.lastTradeDateOrContractMonth,
                    strike=position.contract.strike,
                    right=position.contract.right,
                    exchange=credentials.exchange,
                    currency=credentials.currency,
                    multiplier=credentials.multiplier,
                    tradingClass=credentials.tradingClass
                )
                buy_order = MarketOrder(action, quantity)
                buy_trade = self.client.placeOrder(contract, buy_order)
                self.client.sleep(1)
                # await self.place_market_order(contract=contract, qty=quantity, side=action)
                print(f"Position closed: {position.contract.localSymbol}")

    async def query_order(self, order_id: int) -> dict:
        """
        Queries order\n
        """

        all_orders = self.client.openOrders() + [i.order for i in self.client.reqCompletedOrders(True)]

        for order in all_orders:
            if order.permId == order_id:
                return order

    async def modify_trailing_stop_percent(self, order_id, new_trailing_percent):
        # Get the existing order
        trades = self.client.trades()
        target_trade = next((t for t in trades if t.order.orderId == order_id), None)

        if not target_trade:
            raise ValueError(f"Order with ID {order_id} not found")

        # Create a new order with modified trailing percent
        modified_order = target_trade.order
        modified_order.trailingPercent = new_trailing_percent

        # Submit the modification
        self.client.placeOrder(target_trade.contract, modified_order)

        await self.client.sleep(10)

        return modified_order

    async def connect_app(self, app) -> None:
        """
        Connect main app with api\n
        """
        self.app = app

    async def get_latest_premium_price(self, symbol, expiry, strike, right, exchange=credentials.exchange,
                                       print_data=False):

        option_contract = self._resolve_option_contract(
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            right=right,
            exchange=exchange
        )

        self.client.reqMarketDataType(1)
        market_data = self.client.reqMktData(option_contract, '', snapshot=True)
        self.ib.sleep(5)
        premium_price = {
            "bid": market_data.bid,
            "ask": market_data.ask,
            "last": market_data.last,
            "mid": (market_data.bid + market_data.ask) / 2 if market_data.bid and market_data.ask else None
        }
        return premium_price

    async def modify_option_trail_percent(self, trade, new_trailing_percent=0.14):
        modified_order = Order(
            orderId=trade.order.orderId,
            action=trade.order.action,
            totalQuantity=trade.order.totalQuantity,
            orderType='TRAIL',
            tif=trade.order.tif,
            ocaGroup=trade.order.ocaGroup,
            ocaType=trade.order.ocaType,
            parentId=trade.order.parentId,
            displaySize=trade.order.displaySize,
            trailStopPrice=trade.order.trailStopPrice,
            trailingPercent=new_trailing_percent,
            openClose=trade.order.openClose,
            account=trade.order.account,
            clearingIntent=trade.order.clearingIntent,
            dontUseAutoPriceForHedge=trade.order.dontUseAutoPriceForHedge
        )

        # self.client.cancelOrder(trade.order)

        # self.client.sleep(4)

        new_trade = self.client.placeOrder(trade.contract, modified_order)

        self.client.sleep(3)

        return new_trade

    async def place_stp_order(self, contract, side, quantity, sl):
        details = self.client.reqContractDetails(contract)
        if not details:
            raise ValueError("Invalid contract. Please check the option details.")
        contract = details[0].contract
        stop_order = StopOrder(side, quantity, self._round_stop_price(sl))
        trade = self.client.placeOrder(contract, stop_order)
        self.client.sleep(2)
        print("Stop order placed")

        return trade.order.orderId

    async def modify_stp_order(self, contract, quantity, side, sl, order_id):

        option_details = self.client.reqContractDetails(contract)
        if not option_details:
            raise ValueError("Invalid contract. Please check the option details.")

        stop_order = StopOrder(side, quantity, self._round_stop_price(sl), orderId=order_id)
        trade = self.client.placeOrder(option_details[0].contract, stop_order)

        self.client.sleep(1)
        print("Stop order modified")
