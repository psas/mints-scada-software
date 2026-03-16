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