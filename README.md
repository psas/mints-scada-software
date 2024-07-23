# mints-scada-software

### Installation
These instructions are intended for Linux.
* If you use a Mac, you may have to install Python 3.12 and call it differently in the setup.
* If you use Windows, good luck!

You need to have:
* Python 3.12. Make sure you use it for the setup commands, but not the run commands.
* venv

To set up for the first time (as normal user):

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

### Running
Use these commands to run the software. Execute them in the same folder as `main.py`

    source .venv/bin/activate
    python main.py

### Logging file format
Each line in the log file represents a single DataPacket. Both incoming and outgoing packets are logged. Several extra characters are added for ease of reading by humans. An example logged packet and its explanation are listed below

```22:01:04.655796 .0 >64 #26 !80: 00 00 00 00 00 00```
| Value             | Explanation
|-------------------|-------------
| 22:01:04.655796   | Packet receive/transmit time
| .                 | Error bit, `.` for no error or `E` for error
| 0                 | Reserved bit, `0` or `1`
| >                 | Packet direction. `>` is to the address, `<` is from it
| 64                | Packet address. Hex encoded
| 26                | Sequence number. Hex encoded
| 80                | Command. Hex encoded
| 00 00 00 00 00 00 | Packet data as 6 hex encoded bytes

### User-Provided scripts
This program allows the user to run scripts. This is intended for allowing the automation of tests. These scripts are run as-is, and not sandboxed in any way. This is a security vulnerability, so only run scripts that you trust to not break things. The program is written in this way since it is much easier than trying to properly sandbox the executed code while still giving it access to the required resources to be useful. It may be worth redoing this in the future to be more secure, but for the moment it is fine. Also, the risk isn't much higher than running the base code since it all runs locally on the machine. You have been warned.

Additionally, user-provided scripts CAN NOT be killed once they are started. The script can be asked to stop (which it will be in case of an abort), but Python does not seem to be capable of actually killing the script if it doesn't play nice. It appears that as long as what you are doing is entirely in Python and is non blocking, it stops properly when requested, but this may not be the case if you're including other library code. Keep this in mind while writing your scipts. In future script execution should probably be moved to a subprocess to help ensure that it can't break the main program, but this is out of the scope of this project.

In your script, you are given access to a few special functions and variables:
| Name                      | Use
|---------------------------|-----
| `print(message: str)`     | Prints `str` to the console. Only a single argument can be passes, so use format strings if you want to combine stuff. This overrides the default Python print so that messages appear in the console.
| `mints`                   | a `MintsScriptAPI` that holds aspects of the minTS system.
| `mints.devices`           | a dictionary of `name: str` to `BusRider` containing all devices created in `devices` in `settings.py`
| `mints.graph`             | the `GraphView` in the interface, this can be used to do things like clearing the graph or setting its length.
| `mints.exporter`          | an exporter you can use to automatically export results after each test
| `mitns.autopoller`        | the autopoller, provided so you can start/stop it as needed
| `abort(msg: str = None)`  | Triggers an abort sequence. An optional message can be provided to show up in error messages and logs. 
| `wait(time: float)`       | Waits `time` seconds. Use this as opposed to `time.sleep` since it is interruptable by aborts, while `time.sleep` is not. Beware that this may not be precise, but should be within a few milliseconds.

You may do exception handeling in your script if you want. Just be careful that if you catch a `PleaseStopNowException` you must stop now, and/or pass it on to ensure that your script actually stops before an abort sequence is triggered. `PleaseStopNowException` is not a subclass of `Exception`, so `catch Exception:` will not cause problems.