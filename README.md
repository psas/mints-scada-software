# mints-scada-software

### Installation
This program uses Python's venv, so make sure that is installed first
* `$ python -m venv .venv `
* `$ .venv/bin/activate`
* `$ pip install -r requirements.txt`

### Running
* `$ .venv/bin/activate`
* `$ python main.py`

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