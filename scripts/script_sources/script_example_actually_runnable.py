print("This is an example script showing how to write the script for the new GUI.")
print("Notice that the device variables are based on the id in settings.py, no longer the name.")
print("This script is not meant to be run, but it is actually runnable.")
print("Begin fire")



wait (3.0)

mints.devices[f"ipa-xv-23"].open()

wait (1.0)

mints.devices[f"ig-xv-24"].open()

wait (1.0)

mints.devices[f"igniter"].set(True)

wait (2.0)

mints.devices[f"igniter"].set(False)

wait (1.0)

mints.devices[f"ipa-xv-23"].close()

wait (1.0)

mints.devices[f"ig-xv-24"].close()

wait (1.0)

print("End fire")