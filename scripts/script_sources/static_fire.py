print("Beginning static fire.")

print("Opening XV-25 and XV-26...")
mints.devices["ipa-xv-25"].open()
mints.devices["lox-xv-26"].open()
print("XV-25 and XV-26 opened.")

print("Waiting 1 second for propellant flow...")
wait(1.0)
print("Propellant flow wait complete.")

print("Turning igniter on...")
mints.devices["igniter"].set(True)
print("Igniter turned on.")

print("Waiting 4 seconds for igniter engagement...")
wait(4.0)
print("Igniter engagement wait complete.")

print("Turning igniter off...")
mints.devices["igniter"].set(False)
print("Igniter turned off.")

print("Running the engine for 10 seconds...")
wait(10.0)
print("Engine run complete.")

print("Closing XV-23, XV-24, XV-25, and XV-26...")
mints.devices["ipa-xv-23"].close()
mints.devices["ig-xv-24"].close()
mints.devices["ipa-xv-25"].close()
mints.devices["lox-xv-26"].close()
print("XV-23, XV-24, XV-25, and XV-26 closed.")

print("Opening XV-27...")
mints.devices["ig-xv-27"].open()
print("XV-27 opened.")

print("Waiting 15 seconds for N2 purge...")
wait(15.0)
print("N2 purge complete.")

print("Closing XV-27...")
mints.devices["ig-xv-27"].close()
print("XV-27 closed.")

print("Static fire complete.")