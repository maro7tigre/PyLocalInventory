# PyLocalInventory

PyLocalInventory is a Windows desktop inventory and business-management
application for managing products, services, clients, suppliers, sales,
imports, reports, profiles, permissions, attachments, payments, and database
backups.

The application uses a PySide6 interface and stores business data in
PostgreSQL. It can be used directly on the computer hosting PostgreSQL, connect
to a remote PostgreSQL server, or serve authenticated clients on a local
network.

## Overview

PyLocalInventory is designed for small businesses that need a desktop
application for catalog, stock, customer, supplier, purchasing, and sales
workflows. Business data is separated by profile. New profiles use a dedicated
PostgreSQL database; legacy schema-based profiles remain supported by the
application.

The normal local workflow connects the desktop application directly to
PostgreSQL. The PostgreSQL server may run on the same computer or on another
reachable computer. PyLocalInventory can also host its own HTTP/JSON service on
the LAN so other PyLocalInventory installations can sign in with application
users and role-based permissions.

## Main Features

- Business profiles with company details, optional profile images, duplication,
  deletion, and password-based locking.
- Product catalog, pricing, stock quantities, stock alerts, categories, door
  types, and wood types.
- Service, client, and supplier management.
- Sales and imports with multiple line items and automatically calculated
  totals.
- Stock tracking based on imported and sold quantities.
- Sale payments, progress tracking, and receipt generation.
- PDF report generation from the included HTML templates using Playwright and
  Chromium.
- JPG, PNG, WEBP, and PDF attachments for supported business records.
- PostgreSQL backup and restore, including profile files and attachments.
- LAN hosting with authenticated users, roles, and section-level permissions.
- English, French, and Spanish interface options.
- Windows packaging through PyInstaller in one-directory mode.

## Technology Stack

| Component | Technology |
| --- | --- |
| Application language | Python |
| Desktop interface | PySide6 `>=6.8,<7` |
| Database | PostgreSQL |
| PostgreSQL driver | psycopg2-binary `>=2.9,<3` |
| Profile password support | cryptography `>=44,<50` |
| PDF rendering | Playwright `1.60.0` with Chromium |
| Windows packaging | PyInstaller, configured by `PyLocalInventory.spec` |

PyInstaller and Pillow are installed by `build_windows.ps1`; they are build
dependencies rather than runtime entries in `requirements.txt`.

## Project Structure

```text
PyLocalInventory/
|-- classes/                 # Business entity and operation models
|-- core/                    # Database, profiles, backups, networking, and security
|   `-- network/             # LAN client, server, and protocol
|-- report/                  # HTML report templates and report assets
|-- scripts/
|   `-- migrate_sqlite_to_postgres.py
|-- tests/                   # unittest-based regression tests
|-- ui/                      # Main window, tabs, dialogs, and widgets
|-- build_windows.ps1        # Reproducible Windows build script
|-- LICENSE                  # GNU GPL version 3 license
|-- logo.png                 # Application icon
|-- main.py                  # Application entry point
|-- PyLocalInventory.spec    # PyInstaller build definition
|-- README.md
`-- requirements.txt
```

Generated folders such as `.venv`, `.playwright-browsers`, `build`, `dist`,
`output`, and `tmp` are intentionally omitted from this tree.

## Requirements

To run the application from source:

- Windows for the documented commands and desktop workflow.
- Python 3.10 or newer. This minimum is enforced by the Windows build script;
  use a Python release compatible with the versions in `requirements.txt`.
- `pip`.
- PostgreSQL with a reachable server and credentials that can connect to the
  maintenance database and create or access profile databases.
- The Python packages in `requirements.txt`.
- A Playwright Chromium installation for PDF report generation.

A virtual environment is strongly recommended. PostgreSQL's `pg_dump` and
`pg_restore` command-line tools are additionally required for backup and
restore.

## Installation

Download or open the project folder, then start PowerShell or Command Prompt in
the directory that contains `main.py`.

Create a virtual environment:

```powershell
py -m venv .venv
```

Activate it in Command Prompt:

```bat
.venv\Scripts\activate
```

Or activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the Python dependencies:

```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

Install Chromium for PDF generation when running from source:

```powershell
py -m playwright install --only-shell chromium
```

The Windows build script performs its own dependency and Chromium installation
inside `.venv`.

## Database Configuration

PyLocalInventory stores its shared PostgreSQL connection settings in:

```text
%LOCALAPPDATA%\PyLocalInventory\profiles\_server_config.json
```

Configure these settings through **Network > Database Config**, which opens the
**Database Server** tab:

| Setting | Purpose |
| --- | --- |
| Host | PostgreSQL server hostname or IP address |
| Port | PostgreSQL server port |
| Maintenance Database | Existing database used to test the connection and create profile databases |
| User | PostgreSQL username |
| Password | PostgreSQL password |
| PostgreSQL Bin Directory | Optional folder containing `pg_dump.exe` and `pg_restore.exe` |

Use **Test Connection** before saving. New profiles generate and use a dedicated
PostgreSQL database automatically, so the profile database name is not entered
in this screen.

Do not commit or share `_server_config.json`: it is a local runtime file and may
contain a database password. The application does not use a `.env` file for
these settings.

For a remote PostgreSQL server, its network listening configuration,
host-based authentication rules, operating-system firewall, and database user
privileges must allow the connection. Configure those controls according to
your PostgreSQL installation and network policy.

## Running the Application

Open a terminal in the project root—the directory containing `main.py`—and
normally activate the virtual environment first.

Primary command:

```powershell
py main.py
```

Alternative:

```powershell
python main.py
```

Complete PowerShell example:

```powershell
cd path\to\PyLocalInventory
.\.venv\Scripts\Activate.ps1
py main.py
```

## Building the Windows Application

The verified build script is `build_windows.ps1`. There is no
`build_windows.py` in this repository.

Run the build from PowerShell in the project root:

```powershell
cd path\to\PyLocalInventory
.\build_windows.ps1
```

The script:

1. Locates `py` or `python` and creates `.venv` when needed.
2. Installs or updates pip, setuptools, wheel, PyInstaller, Pillow, and the
   packages in `requirements.txt`.
3. Installs the Playwright Chromium headless shell into
   `.playwright-browsers`.
4. Deletes and recreates the generated `build` and `dist` directories.
5. Runs PyInstaller with `PyLocalInventory.spec`.
6. Verifies the executable, `_internal` runtime directory, logo, report assets,
   and bundled Chromium engine.

The specification bundles `logo.png`, the `report` directory, Playwright,
Chromium, and any supported optional asset directories that exist at build
time. It creates a folder-based application, not a single-file executable and
not an installer.

To launch the application automatically after a successful build:

```powershell
.\build_windows.ps1 -RunAfterBuild
```

## Running the Built Application

The verified output executable is:

```text
dist\PyLocalInventory\PyLocalInventory.exe
```

Launch it from PowerShell with:

```powershell
.\dist\PyLocalInventory\PyLocalInventory.exe
```

The executable depends on the adjacent `dist\PyLocalInventory\_internal`
directory. Keep and distribute the complete `dist\PyLocalInventory` folder;
do not copy `PyLocalInventory.exe` by itself. The build does not create a
Windows installer.

## PostgreSQL Backup Requirements

Creating a backup requires `pg_dump`; restoring one requires `pg_restore`.
Both tools are normally installed with PostgreSQL.

PyLocalInventory searches for these tools in this order:

1. The **PostgreSQL Bin Directory** saved in the Database Server settings.
2. `POSTGRES_BIN`, `POSTGRESQL_BIN`, or `PG_BIN`.
3. The `bin` directory below `PGHOME`.
4. The system `PATH`.
5. Installed PostgreSQL version folders below the Windows Program Files
   locations, preferring newer versions.

An example installation folder is:

```text
C:\Program Files\PostgreSQL\<version>\bin
```

In Command Prompt, verify tool discovery with:

```bat
where pg_dump
where pg_restore
```

In PowerShell, use:

```powershell
where.exe pg_dump
where.exe pg_restore
```

Backups use PostgreSQL's custom dump format and are stored below the selected
profile's `backups` directory in the per-user application data area. A backup
also includes the profile configuration and available attachments. Restoring a
backup replaces the profile's current database content, so create and verify a
current backup before restoring older data.

## Usage

1. Start PyLocalInventory from source or from the built application folder.
2. Open **Network > Database Config**, enter the PostgreSQL settings, and test
   the connection.
3. Create or select a business profile and unlock it if it is protected.
4. Add products and services.
5. Add clients and suppliers.
6. Record imports to capture incoming stock and purchase costs.
7. Record sales, line items, payments, and attachments.
8. Generate and review PDF reports.
9. Use **Backups** to create regular PostgreSQL backups.

To share a profile over a LAN, use **Network > Network Config** on the host.
Start hosting, create the initial Super Admin when prompted, and create
application users and roles. Client computers sign in with the host address,
hosting port, username, and password. The default hosting port is `8765`; it
must be allowed through the host firewall for LAN clients.

## Permissions and User Roles

LAN access uses application users and configurable roles stored with the
selected profile.

- A **Super Admin** has full read, write, and delete access to every permission
  section and can manage hosting, users, roles, and permissions.
- A regular user receives permissions from the assigned role.
- An account without a role has no section permissions.
- Permissions are configured separately as **Read**, **Write**, and **Delete**
  for Products, Services, Clients, Suppliers, Sales, Imports, and Reports.
- Related records inherit their parent permission. For example, sale items and
  payments follow Sales permissions.
- Sections without read permission are hidden from a network user's main
  interface. The server also enforces permissions on requests.

Application user passwords are stored as salted PBKDF2-HMAC-SHA256 hashes.
The LAN transport is plain HTTP/JSON, so use it only on a trusted network or
behind appropriate network protection.

## Troubleshooting

### Python command not found

Check whether the Python launcher is available:

```powershell
py --version
```

If it is not found, install Python and enable the Windows Python launcher or
make `python` available in the terminal.

### Missing Python packages

Activate `.venv`, then reinstall the declared dependencies:

```powershell
py -m pip install -r requirements.txt
```

### PowerShell blocks virtual-environment activation

Allow local script activation for the current PowerShell session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Application cannot connect to PostgreSQL

Verify that:

- PostgreSQL is running.
- The host and port are correct.
- The maintenance database exists.
- The username and password are correct.
- The user can create or access the selected profile database.
- The firewall allows PostgreSQL traffic for remote database connections.
- PostgreSQL accepts connections from the client computer.

Use **Network > Database Config > Test Connection** to see the connection
error returned by PostgreSQL.

### A LAN client cannot connect

- Confirm that hosting is running on the host computer.
- Confirm the host IP address and port; the default port is `8765`.
- Allow the hosting port through the host firewall.
- Verify the application username and password.
- Check that the user's role grants the required section permission.

### `pg_dump` or `pg_restore` not found

Run `where.exe pg_dump` and `where.exe pg_restore` in PowerShell. If a tool is
not found, install the PostgreSQL command-line tools, add their `bin` directory
to `PATH`, or select that directory under **Network > Database Config >
PostgreSQL Bin Directory**.

### Backup creation reports that a file already exists

Backup names must be unique within the current profile. Choose a different
name or rename/delete the existing backup from the Backups Manager.

### PDF reports cannot be generated

When running from source, install the required Chromium engine:

```powershell
py -m playwright install --only-shell chromium
```

For a packaged build, keep the entire application folder together because the
bundled browser is stored below `_internal`.

### Application does not start

Run it from the project root in a terminal so the complete error is visible:

```powershell
py main.py
```

## Development Notes

- Install dependencies from `requirements.txt` and run from source with
  `py main.py`.
- Run the unittest suite with:

  ```powershell
  py -m unittest discover -s tests
  ```

- Test database, backup, restore, report, and LAN permission changes carefully.
- Review terminal output and relevant per-user log files when diagnosing an
  error.
- `scripts\migrate_sqlite_to_postgres.py` is a migration utility for legacy
  data; inspect its arguments and back up source data before using it.
- Do not commit generated builds, virtual environments, local configuration,
  profiles, logs, reports, or customer data. The repository's `.gitignore`
  excludes the corresponding common runtime and build paths.

## Security

- Never commit or share database passwords, API keys, private configuration,
  customer information, attachment data, or production backups.
- Protect `%LOCALAPPDATA%\PyLocalInventory`, especially
  `profiles\_server_config.json`, with appropriate Windows account and file
  permissions.
- Restrict PostgreSQL accounts to the permissions required by the application.
- Keep PostgreSQL and Python dependencies updated within the supported version
  constraints.
- The built-in LAN service uses plain HTTP rather than TLS. Do not expose its
  port directly to the public internet.
- Verify backups and store protected copies outside the application computer.

## License

PyLocalInventory is licensed under the GNU General Public License version 3.
See [LICENSE](LICENSE) for the full terms, including the warranty disclaimer.

## Author and Maintainers

The repository does not currently provide public maintainer contact
information. Use the repository's established contribution or issue workflow
when one is available.
