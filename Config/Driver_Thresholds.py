"""
Driver diagnostics thresholds for TMC-based motor drivers.

These are NOT enforced yet – they just centralize the values so
Jetson / laptop logic can read them and decide what to do.
All values here are examples; tune them based on real data.
"""

# StallGuard result (sg_result)
SG_RESULT_MIN_OK = 10    # below this, consider "too light" / maybe no load
SG_RESULT_MAX_OK = 90    # above this, consider "too heavy" / maybe stall

# Current scaling (cs_actual)
CS_MIN_OK = 5            # minimum acceptable current scaling
CS_MAX_OK = 31           # maximum acceptable current scaling

# Flags from DUMP_TMC DRV_STATUS
STALLGUARD_EXPECTED = 0  # stallguard == 0 is normal; 1 means stall
OT_EXPECTED = 0          # ot == 0 is normal; 1 means over-temperature
OTPW_EXPECTED = 0        # otpw == 0 is normal; 1 means over-temp warning

