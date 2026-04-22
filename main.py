from new_broker import IBTWSAPI
import credentials
import asyncio
from ib_insync import *
import nest_asyncio
from datetime import datetime
from pytz import timezone
from discord_bot import send_discord_message
import os
import logging


def setup_logging():
    os.makedirs('logs', exist_ok=True)

    eastern = timezone('US/Eastern')
    current_date = datetime.now(eastern).strftime('%Y-%m-%d')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s: %(message)s',
        handlers=[
            logging.FileHandler(f'logs/strategy_log_{current_date}.txt', mode='w'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


nest_asyncio.apply()

creds = {
    "host": credentials.host,
    "port": credentials.port,
    "client_id": 14
}


class Strategy:

    def __init__(self):
        self.close_and_open_hedges_with_position = False
        self.atm_call_id = None
        self.atm_put_id = None
        self.otm_call_id = None
        self.otm_put_id = None
        self.otm_put_fill = None
        self.otm_call_fill = None
        self.call_contract = None
        self.put_contract = None
        self.call_stp_id = None
        self.put_stp_id = None
        self.atm_put_sl = None
        self.atm_call_sl = None
        self.atm_call_fill = None
        self.atm_put_fill = None
        self.otm_closest_call = credentials.call_hedge
        self.otm_closest_put = credentials.put_hedge
        self.call_target_price = credentials.call_strike
        self.put_target_price = credentials.put_strike
        self.broker = IBTWSAPI(creds=creds)
        self.strikes = None
        self.call_percent = credentials.call_sl
        self.put_percent = credentials.put_sl
        self.call_rentry = 0
        self.put_rentry = 0
        self.call_order_placed = False
        self.put_order_placed = False
        self.first_sl_leg = None
        self.call_trail_activated = False
        self.put_trail_activated = False
        self._sl_state_lock = asyncio.Lock()
        self.should_continue = True
        self.testing = True
        self.reset = False
        self.func_test = False
        self.enable_logging = credentials.enable_logging
        self.logger = setup_logging() if self.enable_logging else None

    async def dprint(self, phrase):
        print(phrase)
        if self.enable_logging:
            self.logger.info(phrase)
        await send_discord_message(phrase)

    async def lprint(self, phrase):
        if self.enable_logging:
            self.logger.info(phrase)

    def _may_move_put_sl_to_cost(self):
        if not credentials.opposite_leg_move_to_cost:
            return False
        if not credentials.opposite_leg_move_to_cost_respect_trailing:
            return True
        return not self.put_trail_activated

    def _may_move_call_sl_to_cost(self):
        if not credentials.opposite_leg_move_to_cost:
            return False
        if not credentials.opposite_leg_move_to_cost_respect_trailing:
            return True
        return not self.call_trail_activated

    def _first_sl_reentry_lock_enabled(self):
        return credentials.restrict_reentry_to_first_stopped_leg

    async def _register_stop_loss_hit(self, leg):
        if not self._first_sl_reentry_lock_enabled():
            return None
        async with self._sl_state_lock:
            if self.first_sl_leg is None:
                self.first_sl_leg = leg
            return self.first_sl_leg

    def _is_reentry_blocked(self, leg):
        if not self._first_sl_reentry_lock_enabled():
            return False
        opposite_leg = "put" if leg == "call" else "call"
        return self.first_sl_leg == opposite_leg

    def _round_stop_price(self, price):
        return int(round(price / 5.0) * 5)

    async def main(self):
        await send_discord_message("." * 100)
        await self.dprint("\n1. Testing connection...")
        await self.broker.connect()
        await self.dprint(f"Connection status: {self.broker.is_connected()}")

        if self.reset:
            await self.close_all_positions(test=True)
            return

        if self.func_test:
            await self.broker.cancel_hedge()
            return

        if credentials.active_close_hedges and credentials.close_hedges:
            self.close_and_open_hedges_with_position = True
        else:
            self.close_and_open_hedges_with_position = False

        while True:
            current_time = datetime.now(timezone('US/Eastern'))
            start_time = current_time.replace(
                hour=credentials.entry_hour,
                minute=credentials.entry_minute,
                second=credentials.entry_second,
                microsecond=0)
            closing_time = current_time.replace(
                hour=credentials.exit_hour,
                minute=credentials.exit_minute,
                second=credentials.exit_second,
                microsecond=0)
            await self.lprint(f"Current Time: {current_time}")
            if (start_time <= current_time <= closing_time) or self.testing:
                self.strikes = await self.broker.fetch_strikes(credentials.instrument, credentials.exchange,
                                                               secType="IND")
                current_price = await self.broker.current_price(credentials.instrument, credentials.exchange)
                current_price = int(current_price)

                closest_strike = min(self.strikes, key=lambda x: abs(x - current_price))

                await self.lprint("\n\nNew Trading Session Start\n")
                await self.lprint(f"CURRENT PRICE: {current_price}")
                await self.lprint(f"CLOSEST CURRENT PRICE: {closest_strike}")

                if credentials.calc_values:
                    self.otm_closest_call = closest_strike + (credentials.OTM_CALL_HEDGE * 125)
                await self.lprint(f"CALL HEDGE STRIKE PRICE: {self.otm_closest_call}")

                if credentials.calc_values:
                    self.otm_closest_put = closest_strike - (credentials.OTM_PUT_HEDGE * 125)
                await self.lprint(f"PUT HEDGE STRIKE PRICE: {self.otm_closest_put}")

                if credentials.calc_values:
                    self.call_target_price = closest_strike
                    if credentials.ATM_CALL > 0:
                        self.call_target_price += 125 * credentials.ATM_CALL
                await self.lprint(f"CALL POSITION STRIKE PRICE: {self.call_target_price}")

                if credentials.calc_values:
                    self.put_target_price = closest_strike
                    if credentials.ATM_CALL > 0:
                        self.put_target_price -= 125 * credentials.ATM_CALL
                await self.lprint(f"PUT POSITION STRIKE PRICE: {self.put_target_price}")
                if ((credentials.active_close_hedges and not credentials.close_hedges)
                        or (credentials.close_hedges and credentials.active_close_hedges)):
                    await self.place_hedge_orders(call=True, put=True)

                await self.place_atm_put_order()
                await self.place_atm_call_order()
                await self.lprint(
                    "[CONFIG] Linked rules for this session: "
                    f"restrict_reentry_to_first_stopped_leg={self._first_sl_reentry_lock_enabled()} "
                    "(if True, only the first SL-hit leg may re-enter for this session). "
                    f"move_opposite_leg_to_cost={credentials.opposite_leg_move_to_cost} "
                    f"(if True, when one leg hits SL the other leg's stop can move to entry). "
                    f"respect_opposite_trailing={credentials.opposite_leg_move_to_cost_respect_trailing} "
                    f"(if True, skip that move once the opposite leg's trailing SL has tightened). "
                    f"max_re_entries_first_stopped_leg={credentials.number_of_re_entry} "
                    "(when first-stop restriction is enabled, only that leg may use these; otherwise each leg uses its own limit)."
                )
                break
            else:
                await self.dprint("Market hasn't opened yet")
            await asyncio.sleep(10)

        await asyncio.gather(
            self.call_trail_check(),
            self.close_all_positions(test=False),
            self.put_trail_check(),
            self.put_hedge_check(),
            self.call_hedge_check(),
        )

        if credentials.active_close_hedges and not credentials.close_hedges:
            await self.close_open_hedges(close_put=True, close_call=True)

    async def close_all_positions(self, test):
        if credentials.close_positions and not test:
            return
        else:
            while True:
                current_time = datetime.now(timezone('US/Eastern'))
                target_time = current_time.replace(
                    hour=credentials.exit_hour,
                    minute=credentials.exit_minute,
                    second=credentials.exit_second,
                    microsecond=0)

                if current_time >= target_time or test:
                    self.should_continue = False

                    if self.atm_call_id:
                        await self.lprint(f"atm call id: {self.atm_call_id}")
                        await self.broker.cancel_order(self.call_stp_id)
                        await self.broker.cancel_order(self.atm_call_id)
                    if self.atm_put_id:
                        await self.lprint(f"atm put id: {self.atm_put_id}")
                        await self.broker.cancel_order(self.put_stp_id)
                        await self.broker.cancel_order(self.atm_put_id)
                    try:
                        await asyncio.gather(
                            self.close_call(),
                            self.close_put(),
                        )
                        await self.dprint("All position closed")
                    except Exception as e:
                        await self.dprint(e)
                    break

                await asyncio.sleep(10)

    async def close_call(self):
        if self.call_order_placed:
            await self.broker.cancel_call(hedge_strike=self.otm_closest_call, position_strike=self.call_target_price,
                                          close_hedge=self.close_and_open_hedges_with_position)
        else:
            return

    async def close_put(self):
        if self.put_order_placed:
            await self.broker.cancel_put(hedge_strike=self.otm_closest_put, position_strike=self.put_target_price,
                                         close_hedge=self.close_and_open_hedges_with_position)
        else:
            return

    async def place_hedge_orders(self, call, put):
        if call:
            spx_contract_call = Option(
                symbol=credentials.instrument,
                lastTradeDateOrContractMonth=credentials.date,
                strike=self.otm_closest_call,
                right='C',
                exchange=credentials.exchange,
                currency=credentials.currency,
                multiplier=credentials.multiplier,
                tradingClass=credentials.tradingClass
            )
            try:
                await self.dprint("Placing Hedge Call Order")
                m, self.otm_call_fill, self.otm_call_id = await self.broker.place_market_order(
                    contract=spx_contract_call,
                    qty=credentials.call_hedge_quantity, side="BUY")

                while self.should_continue:
                    open_orders = await self.broker.get_open_orders()
                    matching_order = next((trade for trade in open_orders if trade.order.orderId == self.otm_call_id),
                                          None)

                    if matching_order:
                        self.otm_call_fill = matching_order.orderStatus.avgFillPrice
                        if self.otm_call_fill > 0:
                            await self.lprint(f"Call hedge {self.otm_call_fill} is filled.")
                            break
                        else:
                            await self.lprint("Call hedge still open but not filled")
                    else:
                        await self.lprint(
                            f"Call hedge {self.otm_call_fill} is no longer in open orders — might be cancelled or filled.")
                        break

                    await asyncio.sleep(1)

            except Exception as e:
                await self.dprint(f"Error placing call hedge order: {str(e)}")

        if put:
            spx_contract_put = Option(
                symbol=credentials.instrument,
                lastTradeDateOrContractMonth=credentials.date,
                strike=self.otm_closest_put,
                right='P',
                exchange=credentials.exchange,
                currency=credentials.currency,
                multiplier=credentials.multiplier,
                tradingClass=credentials.tradingClass
            )
            try:
                await self.dprint("Placing Hedge Put Order")
                n, self.otm_put_fill, self.otm_put_id = await self.broker.place_market_order(contract=spx_contract_put,
                                                                                             qty=credentials.put_hedge_quantity,
                                                                                             side="BUY")

                while self.should_continue:
                    open_orders = await self.broker.get_open_orders()
                    matching_order = next((trade for trade in open_orders if trade.order.orderId == self.otm_put_id),
                                          None)

                    if matching_order:
                        self.otm_put_fill = matching_order.orderStatus.avgFillPrice
                        if self.otm_put_fill > 0:
                            await self.lprint(f"Put Hedge {self.otm_put_fill} is filled.")
                            break
                        else:
                            await self.lprint("Put Hedge still open but not filled")
                    else:
                        await self.lprint(
                            f"Put Hedge {self.otm_put_fill} is no longer in open orders — might be cancelled or filled.")
                        break

                    await asyncio.sleep(1)

            except Exception as e:
                await self.dprint(f"Error placing put hedge order: {str(e)}")

    async def close_open_hedges(self, close_put=False, close_call=False):
        if close_call:
            spx_contract_call = Option(
                symbol=credentials.instrument,
                lastTradeDateOrContractMonth=credentials.date,
                strike=self.otm_closest_call,
                right='C',
                exchange=credentials.exchange,
                currency=credentials.currency,
                multiplier=credentials.multiplier,
                tradingClass=credentials.tradingClass
            )
            qualified_contracts = self.broker.client.qualifyContracts(spx_contract_call)
            if not qualified_contracts:
                raise ValueError("Failed to qualify contract with IBKR.")
            try:
                await self.broker.place_market_order(contract=spx_contract_call, qty=credentials.call_hedge_quantity,
                                                     side="SELL")
                await self.dprint("Closing Call Hedge")
            except Exception as e:
                await self.dprint(f"Error closing call hedge: {str(e)}")

        if close_put:
            spx_contract_put = Option(
                symbol=credentials.instrument,
                lastTradeDateOrContractMonth=credentials.date,
                strike=self.otm_closest_put,
                right='P',
                exchange=credentials.exchange,
                currency=credentials.currency,
                multiplier=credentials.multiplier,
                tradingClass=credentials.tradingClass
                
            )
            qualified_contracts = self.broker.client.qualifyContracts(spx_contract_put)
            if not qualified_contracts:
                raise ValueError("Failed to qualify contract with IBKR.")
            try:
                await self.broker.place_market_order(contract=spx_contract_put, qty=credentials.put_hedge_quantity,
                                                     side="SELL")
                await self.dprint("Closing Put Hedge")
            except Exception as e:
                await self.dprint(f"Error closing put hedge: {str(e)}")

    async def place_atm_call_order(self):
        premium_price = await self.broker.get_latest_premium_price(
            symbol=credentials.instrument,
            expiry=credentials.date,
            strike=self.call_target_price,
            right="C"
        )
        self.call_contract = Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=self.call_target_price,
            right='C',
            exchange=credentials.exchange,
            currency=credentials.currency,
            multiplier=credentials.multiplier,
            tradingClass=credentials.tradingClass
        )

        qualified_contracts = self.broker.client.qualifyContracts(self.call_contract)
        if not qualified_contracts:
            raise ValueError("Failed to qualify contract with IBKR.")
        await self.lprint(f"Call last price is {premium_price['last']}")

        try:
            k, self.atm_call_fill, self.atm_call_id = await self.broker.place_market_order(contract=self.call_contract,
                                                                                           qty=credentials.call_position,
                                                                                           side="SELL")
            while self.should_continue:
                open_orders = await self.broker.get_open_orders()
                matching_order = next((trade for trade in open_orders if trade.order.orderId == self.atm_call_id), None)

                if matching_order:
                    self.atm_call_fill = matching_order.orderStatus.avgFillPrice
                    if self.atm_call_fill > 0:
                        await self.lprint(f"Call Position {self.atm_call_id} is filled.")
                        break
                    else:
                        await self.lprint("Call Position still open but not filled")
                else:
                    await self.lprint(
                        f"Call Position {self.atm_call_id} is no longer in open orders — might be cancelled or filled.")
                    break

                await asyncio.sleep(1)

            self.call_order_placed = True
            self.call_trail_activated = False
            self.atm_call_sl = self._round_stop_price(
                self.atm_call_fill * (1 + (self.call_percent / 100))
            )
            await self.dprint(f"Call Order placed at {self.atm_call_fill}")
            await self.dprint(f"Call Order sl is {self.atm_call_sl}")
            await asyncio.sleep(1)
            self.call_stp_id = await self.broker.place_stp_order(contract=self.call_contract, side="BUY",
                                                                 quantity=credentials.call_position,
                                                                 sl=self.atm_call_sl)
        except Exception as e:
            await self.dprint(f"Error in placing sell side call order: {str(e)}")

    async def call_hedge_check(self):
        while self.should_continue:
            if self.call_order_placed:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.call_target_price,
                    right="C"
                )
                await self.lprint(f"Call Hedge Premium: {premium_price}")
                open_trades = await self.broker.get_positions()

                call_exists = any(
                    trade.contract.secType == 'OPT' and trade.contract.right == 'C' and
                    trade.contract.symbol == credentials.instrument and trade.contract.strike == self.call_target_price
                    for trade in open_trades
                )

                if not call_exists and self.should_continue:
                    controlling_leg = await self._register_stop_loss_hit("call")
                    if not self._first_sl_reentry_lock_enabled():
                        await self.lprint(
                            "[CALL SL] Call leg stopped out. First-stop re-entry restriction is disabled, "
                            "so Call and Put may continue managing re-entry independently."
                        )
                    elif controlling_leg == "call":
                        await self.lprint(
                            "[CALL SL] Call leg stopped out first. "
                            f"Re-entry: only Call allowed, up to {credentials.number_of_re_entry} times "
                            f"(completed so far: {self.call_rentry}). Put re-entry is blocked for this session."
                        )
                    else:
                        await self.lprint(
                            "[CALL SL] Call leg stopped out, but Put had already stopped out first. "
                            "Re-entry: only Put is allowed; Call will not re-enter."
                        )
                    if (
                        self._may_move_put_sl_to_cost()
                        and self.put_order_placed
                        and self.put_stp_id
                        and self.put_contract is not None
                        and self.atm_put_fill is not None
                    ):
                        self.atm_put_sl = self._round_stop_price(self.atm_put_fill)
                        await self.broker.modify_stp_order(
                            contract=self.put_contract,
                            side="BUY",
                            quantity=credentials.put_position,
                            sl=self.atm_put_sl,
                            order_id=self.put_stp_id
                        )
                        await self.lprint(
                            f"[MOVE-TO-COST] Put stop moved to entry/cost price {self.atm_put_sl} "
                            "(allowed because Put trailing had not started yet, or respect-trailing is False)."
                        )
                        await self.dprint(
                            f"[PUT] Opposite leg SL moved to cost: {self.atm_put_sl}"
                        )
                    elif (
                        credentials.opposite_leg_move_to_cost
                        and self.put_order_placed
                        and self.put_trail_activated
                        and credentials.opposite_leg_move_to_cost_respect_trailing
                    ):
                        await self.lprint(
                            "[MOVE-TO-COST] Put stop not changed: Put trailing SL had already tightened and "
                            "respect_trailing is True."
                        )
                        await self.dprint(
                            "[PUT] Move-to-cost skipped: put trailing SL already adjusted"
                        )
                    elif not credentials.opposite_leg_move_to_cost:
                        await self.lprint(
                            "[MOVE-TO-COST] Put stop not changed: move_opposite_leg_to_cost is False in credentials."
                        )
                    elif credentials.opposite_leg_move_to_cost:
                        await self.lprint(
                            "[MOVE-TO-COST] Put stop not changed: Put not open, or no stop order / fill data — "
                            "nothing to modify."
                        )
                    self.call_order_placed = False
                    self.call_stp_id = None
                    if self.close_and_open_hedges_with_position:
                        await self.close_open_hedges(close_call=True, close_put=False)
                    await self.dprint("[CALL] Stop loss triggered - Executing market buy")
                    continue

            await asyncio.sleep(1)

    async def call_trail_check(self):
        temp_percentage = 1
        while self.should_continue:
            if self.call_order_placed:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.call_target_price,
                    right="C"
                )
                await self.lprint(f"Call Sell Leg Premium: {premium_price}")
                if premium_price['ask'] <= self.atm_call_fill - temp_percentage * (
                        credentials.call_entry_price_changes_by / 100) * self.atm_call_fill:
                    self.atm_call_sl = self._round_stop_price(
                        self.atm_call_sl - (self.atm_call_fill * (credentials.call_change_sl_by / 100))
                    )
                    await self.dprint(f"[CALL] Trailing stop updated to {self.atm_call_sl}")
                    await self.broker.modify_stp_order(contract=self.call_contract, side="BUY",
                                                       quantity=credentials.call_position, sl=self.atm_call_sl,
                                                       order_id=self.call_stp_id)
                    self.call_trail_activated = True
                    temp_percentage += 1

                await asyncio.sleep(credentials.call_check_time)
            else:
                if self._is_reentry_blocked("call"):
                    await self.lprint(
                        "[RE-ENTRY] Call re-entry task ending: Put stop was hit first, so only Put may re-enter."
                    )
                    await self.dprint("Call re-entry blocked because put SL was hit first.")
                    return
                await self.lprint("Checking for call re-entry")
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.call_target_price,
                    right="C"
                )
                await self.lprint(f"Call Sell Leg Re-entry Premium: {premium_price}")
                if premium_price['ask'] <= self.atm_call_fill and self.call_rentry < credentials.number_of_re_entry:
                    await self.dprint("[CALL] Re-entry condition met - Initiating new position")
                    self.call_rentry += 1
                    await self.dprint(f"[CALL] Re-entry count: {self.call_rentry}")
                    if self.close_and_open_hedges_with_position:
                        await self.place_hedge_orders(call=True, put=False)
                    await self.place_atm_call_order()
                    temp_percentage = 1
                    self.call_order_placed = True
                    continue

                if not self.call_rentry < credentials.number_of_re_entry:
                    await self.dprint("Call re-entry limit reached")
                    return

                await asyncio.sleep(credentials.call_reentry_time)

    async def place_atm_put_order(self):
        premium_price = await self.broker.get_latest_premium_price(
            symbol=credentials.instrument,
            expiry=credentials.date,
            strike=self.put_target_price,
            right="P"
        )
        self.put_contract = Option(
            symbol=credentials.instrument,
            lastTradeDateOrContractMonth=credentials.date,
            strike=self.put_target_price,
            right='P',
            exchange=credentials.exchange,
            currency=credentials.currency,
            multiplier=credentials.multiplier,
            tradingClass=credentials.tradingClass
        )

        qualified_contracts = self.broker.client.qualifyContracts(self.put_contract)
        if not qualified_contracts:
            raise ValueError("Failed to qualify contract with IBKR.")
        await self.lprint(f"Put last price is {premium_price['last']}")

        try:
            k, self.atm_put_fill, self.atm_put_id = await self.broker.place_market_order(contract=self.put_contract,
                                                                                         qty=credentials.put_position,
                                                                                         side="SELL")

            while self.should_continue:
                open_orders = await self.broker.get_open_orders()
                matching_order = next((trade for trade in open_orders if trade.order.orderId == self.atm_put_id), None)

                if matching_order:
                    self.atm_put_fill = matching_order.orderStatus.avgFillPrice
                    if self.atm_put_fill > 0:
                        await self.lprint(f"Put Position {self.atm_put_id} is filled.")
                        break
                    else:
                        await self.lprint("Put Position still open but not filled")
                else:
                    await self.lprint(
                        f"Put Position {self.atm_put_id} is no longer in open orders — might be cancelled or filled."
                    )
                    break

                await asyncio.sleep(1)

            self.put_order_placed = True
            self.put_trail_activated = False
            self.atm_put_sl = self._round_stop_price(
                self.atm_put_fill * (1 + (self.put_percent / 100))
            )
            await self.dprint(f"Put Order placed at {self.atm_put_fill}")
            await self.dprint(f"Put Order sl is {self.atm_put_sl}")
            await asyncio.sleep(1)
            self.put_stp_id = await self.broker.place_stp_order(contract=self.put_contract, side="BUY",
                                                                quantity=credentials.put_position,
                                                                sl=self.atm_put_sl)
        except Exception as e:
            await self.dprint(f"Error in placing sell side put order: {str(e)}")

    async def put_hedge_check(self):
        while self.should_continue:
            if self.put_order_placed:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.put_target_price,
                    right="P"
                )
                await self.lprint(f"Put Hedge Premium: {premium_price}")
                open_trades = await self.broker.get_positions()

                put_exists = any(
                    trade.contract.secType == 'OPT' and trade.contract.right == 'P' and
                    trade.contract.symbol == credentials.instrument and trade.contract.strike == self.put_target_price
                    for trade in open_trades
                )

                if not put_exists and self.should_continue:
                    controlling_leg = await self._register_stop_loss_hit("put")
                    if not self._first_sl_reentry_lock_enabled():
                        await self.lprint(
                            "[PUT SL] Put leg stopped out. First-stop re-entry restriction is disabled, "
                            "so Call and Put may continue managing re-entry independently."
                        )
                    elif controlling_leg == "put":
                        await self.lprint(
                            "[PUT SL] Put leg stopped out first. "
                            f"Re-entry: only Put allowed, up to {credentials.number_of_re_entry} times "
                            f"(completed so far: {self.put_rentry}). Call re-entry is blocked for this session."
                        )
                    else:
                        await self.lprint(
                            "[PUT SL] Put leg stopped out, but Call had already stopped out first. "
                            "Re-entry: only Call is allowed; Put will not re-enter."
                        )
                    if (
                        self._may_move_call_sl_to_cost()
                        and self.call_order_placed
                        and self.call_stp_id
                        and self.call_contract is not None
                        and self.atm_call_fill is not None
                    ):
                        self.atm_call_sl = self._round_stop_price(self.atm_call_fill)
                        await self.broker.modify_stp_order(
                            contract=self.call_contract,
                            side="BUY",
                            quantity=credentials.call_position,
                            sl=self.atm_call_sl,
                            order_id=self.call_stp_id
                        )
                        await self.lprint(
                            f"[MOVE-TO-COST] Call stop moved to entry/cost price {self.atm_call_sl} "
                            "(allowed because Call trailing had not started yet, or respect-trailing is False)."
                        )
                        await self.dprint(
                            f"[CALL] Opposite leg SL moved to cost: {self.atm_call_sl}"
                        )
                    elif (
                        credentials.opposite_leg_move_to_cost
                        and self.call_order_placed
                        and self.call_trail_activated
                        and credentials.opposite_leg_move_to_cost_respect_trailing
                    ):
                        await self.lprint(
                            "[MOVE-TO-COST] Call stop not changed: Call trailing SL had already tightened and "
                            "respect_trailing is True."
                        )
                        await self.dprint(
                            "[CALL] Move-to-cost skipped: call trailing SL already adjusted"
                        )
                    elif not credentials.opposite_leg_move_to_cost:
                        await self.lprint(
                            "[MOVE-TO-COST] Call stop not changed: move_opposite_leg_to_cost is False in credentials."
                        )
                    elif credentials.opposite_leg_move_to_cost:
                        await self.lprint(
                            "[MOVE-TO-COST] Call stop not changed: Call not open, or no stop order / fill data — "
                            "nothing to modify."
                        )
                    self.put_order_placed = False
                    self.put_stp_id = None
                    if self.close_and_open_hedges_with_position:
                        await self.close_open_hedges(close_call=False, close_put=True)
                    await self.dprint("[PUT] Stop loss triggered - Executing market buy")
                    continue

            await asyncio.sleep(1)

    async def put_trail_check(self):
        temp_percentage = 1
        while self.should_continue:
            if self.put_order_placed:
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.put_target_price,
                    right="P"
                )
                await self.lprint(f"Put Sell Leg Premium: {premium_price}")
                if premium_price['ask'] <= self.atm_put_fill - temp_percentage * (
                        credentials.put_entry_price_changes_by / 100) * self.atm_put_fill:
                    self.atm_put_sl = self._round_stop_price(
                        self.atm_put_sl - (self.atm_put_fill * (credentials.put_change_sl_by / 100))
                    )
                    await self.dprint(f"[PUT] Trailing stop updated to {self.atm_put_sl}")
                    await self.broker.modify_stp_order(contract=self.put_contract, side="BUY",
                                                       quantity=credentials.put_position, sl=self.atm_put_sl,
                                                       order_id=self.put_stp_id)
                    self.put_trail_activated = True
                    temp_percentage += 1

                await asyncio.sleep(credentials.put_check_time)
            else:
                if self._is_reentry_blocked("put"):
                    await self.lprint(
                        "[RE-ENTRY] Put re-entry task ending: Call stop was hit first, so only Call may re-enter."
                    )
                    await self.dprint("Put re-entry blocked because call SL was hit first.")
                    return
                await self.lprint("Checking for put re-entry")
                premium_price = await self.broker.get_latest_premium_price(
                    symbol=credentials.instrument,
                    expiry=credentials.date,
                    strike=self.put_target_price,
                    right="P"
                )
                await self.lprint(f"Put Sell Leg Re-entry Premium: {premium_price}")
                if premium_price['ask'] <= self.atm_put_fill and self.put_rentry < credentials.number_of_re_entry:
                    await self.dprint("[PUT] Re-entry condition met - Initiating new position")
                    self.put_rentry += 1
                    await self.dprint(f"[PUT] Re-entry count: {self.put_rentry}")
                    if self.close_and_open_hedges_with_position:
                        await self.place_hedge_orders(call=False, put=True)
                    await self.place_atm_put_order()
                    temp_percentage = 1
                    self.put_order_placed = True
                    continue

                if not self.put_rentry < credentials.number_of_re_entry:
                    await self.dprint("Put re-entry limit reached")
                    return

                await asyncio.sleep(credentials.put_reentry_time)


if __name__ == "__main__":
    s = Strategy()
    asyncio.run(s.main())
