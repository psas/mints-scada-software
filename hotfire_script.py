# --- TIMING VARIABLES ---
ipa_lead_time = 1.0         # Seconds IPA flows before LOX
igniter_overlap = 2.0       # Seconds igniter stays on AFTER LOX opens
total_burn_duration = 5.0   # Total seconds LOX is flowing
# ------------------------

# Calculate the remaining burn time after the igniter turns off
main_burn_time = total_burn_duration - igniter_overlap

print("Beginning static fire.")

#xv-23 & xv-24 should be open and allowing the tanks to be pressurized at this point.

print("Turning igniter on...")
mints.devices["igniter"].set(True)
print("Igniter turned on.")

print("Opening XV-25 (IPA)...")
mints.devices[f"ipa_liquid (XV-25)"].open()

print(f"Waiting {ipa_lead_time}s for propellant flow...")
wait(ipa_lead_time)

print("Opening XV-26 (LOX)...")
mints.devices[f"lox_liquid (XV-26)"].open()
print("Ignition! Both main valves are open.")

print(f"Holding igniter on for {igniter_overlap}s overlap...")
wait(igniter_overlap)

print("Turning igniter off...")
mints.devices["igniter"].set(False)

print(f"Running main phase of engine burn for {main_burn_time}s...")
wait(main_burn_time)

print("Burn complete. Closing main valves...")
mints.devices[f"n2_ipa (XV-23)"].close()
mints.devices[f"n2_lox (XV-24)"].close()
mints.devices[f"ipa_liquid (XV-25)"].close()
mints.devices[f"lox_liquid (XV-26)"].close()
print("XV-23, XV-24, XV-25, and XV-26 closed.")

print("Opening XV-27 for N2 purge...")
mints.devices["n2_purge (XV-27)"].open()

print("Waiting 10 seconds for N2 purge...")
wait(10.0)

print("Closing XV-27...")
mints.devices["n2_purge (XV-27)"].close()

print("Static fire complete.")
