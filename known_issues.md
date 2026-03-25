# Known-Issues

## This place is used to store any strange issues that is found


## Template

What happened: This is placeholder for template

Reproducibility: This is placeholder for template

This is placeholder for template

- a template
- a template
- a template
- a template

---

## 1. Logic bug after close controller window during recording

What happened: respawn the controller window after start recording, it will jump back to not recording on recording clock, and can not click stop recording button because the button think it's not in recording. Also, the listener think user is still in recording so for user side, they can not even turn off the software because it will respawn every time they close it.

Reproducibility: Happen everytime. make run -> start recording -> close controller window

Possible causes:

- gui/controller_window.py
- backend/*

---

## 2. Logic bug after enter playback mode

What happened: By design playback mode is entirely saparated from live mode, which means everything inside will be static including logs to make a full replay. Right now when enter playback mode, the logs still apply "live mode backend" and mix the logs.

Reproducibility: Happen everytime when enter playback mode.

Possible causes:

- gui/controller_window.py
- gui/scada_window.py

---

## 3. Software crash after drag and drop widget to workspace

What happened: By drag and drop widget to workspace in controller window, the software will frozen, crash and close itself.

Reproducibility: Happen everytime when drag and drop to workspace.

Possible causes:

- gui/controller_window.py

---

## 4. Software crash after click run script button in script control

What happened: By click run script button in script control in controller window, the software will crash.

Reproducibility: Happen everytime when click on the button.

Possible causes:

- gui/controller_window.py

---