# Default Values #close_hedges
port = 7497
host = "127.0.0.1"
data_type = 4
instrument = "N225"
tradingClass = "225"
exchange = "OSE.JPN"
currency = "JPY"
multiplier = "1000"
close_positions = False
enable_logging = True
calc_values = True
active_close_hedges = False
close_hedges = True
# if active_close_hedges is false then don't open the hedges at all if true
# And close_hedges is true then close and open hedges accordingly
# And if close-hedges is False then just open the hedges but don't close them
WEBHOOK_URL = "https://discord.com/api/webhooks/1479071097134649496/P4FPegjWst-GJJbbl6ULBwZP1o1FQOwNDmK6thSHOXfnOfJf9vEpJEWF10dCAEoVAU4y"

# Changeable Values
date = "20260507"  # Date of contract (YYYY-MM-DD)
restrict_reentry_to_first_stopped_leg = True  # If True, only the first SL-hit leg can re-enter; if False, Call/Put re-enter independently
number_of_re_entry = 0  # Re-entry attempts allowed for the first stopped leg (set >1 for multiple re-entries)
opposite_leg_move_to_cost = True  # When one ATM leg stops out, move the other leg's stop to entry (cost)
# If True, skip move-to-cost when the opposite leg's trailing SL has tightened at least once
opposite_leg_move_to_cost_respect_trailing = True
OTM_CALL_HEDGE = 20  # How far away the call hedge is (10 means that its $50 away from current price)
OTM_PUT_HEDGE = 40  # How far away the put hedge is (10 means that its $50 away from current price)
ATM_CALL = 2  # How far away call position is (2 means that its $10 away from current price)
ATM_PUT = 2  # How far away put position is (2 means that its $10 away from current price)
call_sl = 70  # From where the call stop loss should start from (15 here means 15% of entry price)
call_entry_price_changes_by = 50  # What % should call entry premium price should change by to update the trailing %
call_change_sl_by = 50  # What % of entry price should call sl change when trailing stop loss updates
put_sl = 70  # From where the put stop loss should start from (15 here means 15% of entry price)
put_entry_price_changes_by = 50  # What % should put entry premium price should change by to update the trailing %
put_change_sl_by = 50  # What % of entry price should put sl change when trailing stop loss updates
conversion_time = 10  # Deprecated (No use)
entry_hour = 9  # Entry time in hours
entry_minute = 35  # Entry time in minutes
entry_second = 00  # Entry time in seconds
exit_hour = 15  # Exit time in hours
exit_minute = 55  # Exit time in minutes
exit_second = 00  # Exit time in seconds
call_hedge_quantity = 1  # Quantity for call hedge
put_hedge_quantity = 1  # Quantity for put hedge
call_position = 1  # Quantity for call position
put_position = 1  # Quantity for put position
call_hedge = 5400
call_strike = 5415
put_hedge = 5350
put_strike = 5405
call_check_time = 1
call_reentry_time = 5
put_check_time = 1
put_reentry_time = 5
