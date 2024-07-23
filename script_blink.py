print("Blinky light time!")
lights = []
wt = 0.25
for i in range(8):
	lights.append(mints.devices[f"Solenoid {i}"])
for l in lights:
	l.open()
	wait(wt)
for l in lights:
	l.close()
	wait(wt)