# Headless server

`PyLocalInventoryServer.exe` (or `python server.py` from source) hosts a
profile on the LAN without opening the desktop window. It is the same
`DatabaseServer` the Hosting tab starts, run in its own process.

## Why it exists

Hosting from the desktop app puts every client request in the same Python
interpreter as the window. Python runs one thread at a time per process, so
whenever the window is busy (filling a large table, building a report, a long
C call) client requests wait behind it, and when the window is closed or stops
responding, every client is cut off.

Measured on one machine against a database of 8 000 sales and 40 000 sale
lines. A client loads the Sales page, the Products page and the dashboard in a
loop while a host window does the work named in the first column. The window
work is simulated (a script, not an operator clicking), so read the numbers as
the size of the effect, not as a prediction for a given PC:

| Host window is...         | Server inside the window          | Server in its own process |
| ------------------------- | --------------------------------- | ------------------------- |
| idle                      | 19 ms median                      | 21 ms median              |
| running Python code       | 71 ms median                      | 20 ms median              |
| filling a 4 000 row table | 588 ms median, 1.3 s worst        | 23 ms median              |
| inside one long C call    | 8 of 13 calls failed, 3.8 s worst | 22 ms median, none failed |

A separate process also keeps serving when the window is closed, and it can
start with Windows before anyone signs in to the app.

## Commands

```
PyLocalInventoryServer profiles
PyLocalInventoryServer create-admin [--profile NAME] [--username NAME]
PyLocalInventoryServer serve [--profile NAME] [--port 8765]
PyLocalInventoryServer status [--host 127.0.0.1] [--port 8765]
```

- `profiles` lists the profiles found on this computer.
- `create-admin` creates a Super Admin and asks for the password twice.
  `--password-stdin` reads it from standard input for scripted setups.
- `serve` hosts until Ctrl+C. `--profile` can be left out when only one
  profile exists. If no Super Admin exists yet and it runs in a terminal, it
  offers to create one first.
- `status` exits with code 0 when a server answers on the port.

From source the same commands are `python server.py serve`, and so on.

## What it reuses

Nothing is duplicated. The server reads the PostgreSQL settings saved by
**Network > Database Config** and the profiles created in the desktop app, from
the same per-user folder (`%LOCALAPPDATA%\PyLocalInventory`). Create the
profile and enter the database settings in the desktop app once, then the
server needs no further setup.

Because that folder is per Windows user, run the server as the same Windows
user who set up the app. Under another account it will report that no profile
exists.

## What it does on its own

- Waits for PostgreSQL at startup instead of exiting, so it can start at boot
  before the PostgreSQL service is ready.
- Restarts the listener if the serving thread ever exits, on the same port,
  keeping signed-in sessions.
- Probes the database every 30 seconds and rebuilds its connection pool after
  three failed probes, which is what a PostgreSQL restart needs.
- Rereads the profile's company details when they are edited, so report
  headers on clients stay current.
- Refuses to start when something already answers on the port. Windows would
  otherwise let two hosts bind the same port and split the traffic.

Logs go to the same `logs` folder as the desktop app. Look for
`headless_server_startup`, `listener_down`, and `database_probe_failed` next
to the existing `host_state` and `host_heartbeat` lines.

## Using the desktop app next to it

On the host computer, stop hosting in **Network > Network Config** (only one
process can own the port), then either:

- keep using the app as before with the local profile. It talks to
  PostgreSQL directly and keeps every admin screen; or
- sign in as a network client to `127.0.0.1`, exactly like the other PCs.

A Super Admin signed in over the network, from the host or any other PC, can
open **Network > Network Config** to manage users, passwords, roles and
permissions. Database settings, profiles and restore stay on the host
computer because they act on the host's own files and PostgreSQL install.

Role changes apply at the user's next sign-in, as before.

## Start it with Windows

Task Scheduler runs it at boot with no window and restarts it if it ever
exits. Run `PyLocalInventoryServer serve` once by hand first: Windows Firewall
only shows its "allow on private networks" prompt to a program started from
your desktop, never to a scheduled task, and without that rule clients on
other PCs time out. Allow it, press Ctrl+C, then set up the task.

All steps first, in the Task Scheduler GUI:

1. Open **Task Scheduler**, choose **Create Task** (not Basic Task).
2. **General**: name it `PyLocalInventory Server`. Select your own Windows
   user, **Run whether user is logged on or not**, and leave **Run with
   highest privileges** unchecked.
3. **Triggers**: **New**, begin the task **At startup**.
4. **Actions**: **New**, **Start a program**. Program: the full path to
   `PyLocalInventoryServer.exe`. Arguments: `serve --profile "YourProfile" --port 8765`.
5. **Conditions**: uncheck **Start the task only if the computer is on AC
   power**.
6. **Settings**: check **If the task fails, restart every 1 minute**, attempts
   `999`. Uncheck **Stop the task if it runs longer than**. For **If the task
   is already running**, keep **Do not start a new instance**.
7. Save, enter your Windows password when asked, then right-click the task and
   choose **Run**.

Check it from any terminal:

```
PyLocalInventoryServer status
```

If that prints `Running`, sign in from a client PC. If it prints
`Not reachable`, open the task's **History** tab and the `logs\app.log` file
beside the executable before changing anything.

The host PC must not go to sleep: in **Settings > System > Power**, set sleep
to **Never** while plugged in. A sleeping host is unreachable no matter how
the server is started.
