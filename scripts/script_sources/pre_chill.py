print("Beginning pre-chill.")

print("Opening XV-23, XV-24, and XV-26...")
mints.devices["ipa-xv-23"].open()
mints.devices["ig-xv-24"].open()
mints.devices["lox-xv-26"].open()
print("XV-23, XV-24, and XV-26 opened.")

print("Waiting 3 seconds for the system to chill...")
wait(3.0)
print("Pre-chill wait complete.")

print("Closing XV-26 while keeping XV-23 and XV-24 open for static fire...")
mints.devices["lox-xv-26"].close()
print("XV-26 closed. XV-23 and XV-24 remain open for static fire.")

print("Pre-chill complete.")