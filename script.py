print("Blinky light time!")
led = mints.devices["Light"]
for i in range(20):
    led.set(True)
    wait(0.5)
    led.set(False)
    wait(0.5)
print("All done blinking!")