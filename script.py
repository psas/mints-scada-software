# Steps taken from MinTS Firing SOP (Operation table)
# https://docs.googlsoue.com/document/d/1effB3ocMFTA--6McFJt2t-bL2E5HSzYe/edit

print("Begin Fire")

# pressurize IPA and LOX tanks (SOP lines 1 & 2)
# mints.devices[f"n2_ipa (XV-23)"].open()
# wait(0.5)
mints.devices[f"n2_lox (XV-24)"].open()
wait(0.5)

# Flow IPA and LOX (SOP lines 3 & 4)
mints.devices[f"ipa_liquid (XV-25)"].open()
wait(0.5)
mints.devices[f"lox_liquid (XV-26)"].open()

# Let lines chill and flow stabilize (SOP line 5)
wait(1)

# Ignite fuel mixture (SOP line 6)
mints.devices["igniter"].set(True)
wait(3)
mints.devices["igniter"].set(False)

# Burn for 10 seconds (SOP line 7)
wait(7)

# Shut liquid flow and pressurization valves (SOP line 8)
# mints.devices[f"n2_ipa (XV-23)"].close()
# wait(0.5)
mints.devices[f"n2_lox (XV-24)"].close()
wait(0.5)
mints.devices[f"ipa_liquid (XV-25)"].close()
wait(0.5)
mints.devices[f"lox_liquid (XV-26)"].close()
wait(0.5)

# N2 purge (SOP line 9)
mints.devices[f"n2_purge (XV-27)"].open()
wait(10)

# N2 finish purge (SOP line 10)
mints.devices[f"n2_purge (XV-27)"].close()


print("Fire Complete")