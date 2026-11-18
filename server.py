"""Headless LAN server: hosts a profile without opening the desktop window.

The desktop app can host from its own process, but then every client request
shares one Python interpreter with the window, so a busy or frozen window
stalls every connected PC. This entry point runs the same DatabaseServer on
its own, with no Qt event loop to compete with, and restarts the listener by
itself when PostgreSQL or the serving thread goes away.

    python server.py profiles
    python server.py create-admin --profile NAME
    python server.py serve --profile NAME --port 8765
    python server.py status --port 8765
"""
import argparse
import getpass
import logging
import os
import signal
import sys
import threading
import urllib.error
import urllib.request

from core.build_info import APP_BUILD_ID
from core.network.protocol import DEFAULT_PORT

logger = logging.getLogger("server_cli")
logger.setLevel(logging.INFO)

# How often the supervisor checks the listener, and the longest it waits
# between attempts to bring a failed listener or database back.
_SUPERVISE_SECONDS = 2.0
_MAX_RETRY_SECONDS = 30.0
# Consecutive failed database probes before the connection pool is rebuilt.
_DATABASE_FAILURES_BEFORE_RESTART = 3
_DATABASE_PROBE_SECONDS = 30.0

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _say(message=""):
    print(message, flush=True)


def _one_line(error):
    """First line of an error message; psycopg2 appends multi-line hints."""
    lines = str(error).strip().splitlines()
    return lines[0] if lines else type(error).__name__


def _load_profile(profile_name):
    """Return (profile_manager, profile), choosing the only profile when no
    name is given. Raises SystemExit with a readable message otherwise."""
    from core.profiles import ProfileManager

    manager = ProfileManager()
    names = sorted(manager.available_profiles)
    if not names:
        raise SystemExit(
            "No profile found. Create one in the desktop app first "
            f"(profiles are read from {manager.profiles_path})."
        )
    if profile_name is None:
        if len(names) > 1:
            raise SystemExit(
                "Several profiles exist, choose one with --profile: " + ", ".join(names)
            )
        profile_name = names[0]
    if not manager.load_profile(profile_name):
        raise SystemExit(
            f"Profile '{profile_name}' not found. Available: " + ", ".join(names)
        )
    return manager, manager.selected_profile


def _open_database(manager):
    """Connect to the selected profile and bring its schema up to date."""
    from classes.registry import register_all
    from core.database import Database

    database = Database(manager)
    register_all(database)
    if not database.connect():
        raise ConnectionError(database.last_error or "Could not connect to PostgreSQL")
    return database


def _prompt_new_password():
    while True:
        password = getpass.getpass("Password: ")
        if not password:
            _say("Password cannot be empty.")
            continue
        if getpass.getpass("Repeat password: ") == password:
            return password
        _say("Passwords do not match, try again.")


def _create_admin(database, username=None, password=None):
    from core.user_manager import UserManager

    username = (username or input("Admin username: ")).strip()
    if not username:
        raise SystemExit("Username cannot be empty.")
    if password is None:
        password = _prompt_new_password()
    try:
        UserManager(database).create_user(username, password, is_superadmin=True)
    except ValueError as error:
        database.conn.rollback()
        raise SystemExit(str(error))
    _say(f"Super admin '{username}' created.")


class _Supervisor:
    """Keeps one DatabaseServer listening until asked to stop."""

    def __init__(self, manager, profile, port):
        self.manager = manager
        self.profile = profile
        self.port = port
        self.stop_requested = threading.Event()
        self.database = None
        self.server = None
        # True while waiting on a terminal prompt, where a stop signal has to
        # interrupt the blocking read instead of only setting the event.
        self.prompting = False
        self._profile_mtime = self._config_mtime()

    def _config_mtime(self):
        try:
            return os.path.getmtime(self.profile.config_path)
        except OSError:
            return None

    def _wait(self, seconds):
        return self.stop_requested.wait(seconds)

    def _connect_database(self):
        """Block until PostgreSQL accepts the connection.

        At boot this process can start before the PostgreSQL service does, so
        a refused connection is retried instead of treated as fatal.
        """
        delay = 2.0
        while not self.stop_requested.is_set():
            try:
                self.database = _open_database(self.manager)
                return True
            except Exception as error:
                logger.warning("database_unavailable category=%s", type(error).__name__)
                _say(f"PostgreSQL not reachable ({_one_line(error)}). Retrying in {delay:.0f}s...")
                if self._wait(delay):
                    return False
                delay = min(delay * 2, _MAX_RETRY_SECONDS)
        return False

    def _start_listener(self):
        """Start (or restart) the listener, retrying until it holds."""
        from core.network.server import DatabaseServer

        delay = 2.0
        while not self.stop_requested.is_set():
            try:
                if self.server is None:
                    self.server = DatabaseServer(self.database, port=self.port)
                self.server.start()
                if self.server.is_running:
                    return True
                reason = self.server.snapshot().get("reason")
            except Exception as error:
                reason = _one_line(error)
            logger.warning("listener_start_failed port=%d", self.port)
            _say(f"Could not start listening on port {self.port} ({reason}). "
                 f"Retrying in {delay:.0f}s...")
            if self._wait(delay):
                return False
            delay = min(delay * 2, _MAX_RETRY_SECONDS)
        return False

    def _reload_profile_if_changed(self):
        """Pick up company details edited in the desktop app; they are sent to
        clients at login for report headers."""
        mtime = self._config_mtime()
        if mtime is not None and mtime != self._profile_mtime:
            self._profile_mtime = mtime
            self.profile.load_config_data()
            logger.info("profile_config_reloaded")

    def run(self):
        if not self._connect_database():
            return EXIT_OK
        from core.user_manager import UserManager

        if not UserManager(self.database).has_any_superadmin():
            if not sys.stdin or not sys.stdin.isatty():
                _say("No super admin exists yet. Run: server create-admin")
                return EXIT_ERROR
            _say("No super admin exists yet. Create one to manage users and roles.")
            self.prompting = True
            try:
                _create_admin(self.database)
            finally:
                self.prompting = False
        # The schema is initialized; requests use the server's own pool, so
        # this connection would only sit idle and go stale across a
        # PostgreSQL restart.
        self.database.close()

        if not self._start_listener():
            return EXIT_OK
        from core.network.server import DatabaseServer

        _say()
        _say(f"PyLocalInventory server is running (build {APP_BUILD_ID})")
        _say(f"  Profile : {self.profile.name}")
        _say(f"  Address : {DatabaseServer.local_ip()}  port {self.server.port}")
        _say("  Clients sign in with that address, the port, and their username.")
        _say("  Press Ctrl+C to stop.")
        _say()

        self._supervise()
        _say("Stopping...")
        self.server.stop(reason="operator_stop")
        return EXIT_OK

    def _supervise(self):
        """Watch the listener and the database until a stop is requested."""
        database_failures = 0
        since_probe = 0.0
        while not self._wait(_SUPERVISE_SECONDS):
            self._reload_profile_if_changed()
            if not self.server.is_running:
                state = self.server.snapshot().get("state")
                logger.error("listener_down state=%s action=restart", state)
                _say(f"Listener stopped unexpectedly ({state}), restarting...")
                self._restart()
                database_failures = 0
                continue
            since_probe += _SUPERVISE_SECONDS
            if since_probe < _DATABASE_PROBE_SECONDS:
                continue
            since_probe = 0.0
            if self.server.health_status(check_database=True).get("database_accessible"):
                database_failures = 0
                continue
            database_failures += 1
            if database_failures >= _DATABASE_FAILURES_BEFORE_RESTART:
                # Pooled connections do not recover from a PostgreSQL restart
                # on their own; rebuilding the pool does. Sessions survive
                # because they live on the server object, not in the pool.
                logger.error("database_probe_failed count=%d action=restart", database_failures)
                _say("PostgreSQL stopped answering, reconnecting...")
                self._restart()
                database_failures = 0

    def _restart(self):
        try:
            self.server.stop(reason="supervisor_restart")
        except Exception as error:
            logger.error("supervisor_stop_failed category=%s", type(error).__name__)
        if self._start_listener():
            _say("Listening again.")


def _install_stop_signals(supervisor):
    def request_stop(_signum, _frame):
        supervisor.stop_requested.set()
        if supervisor.prompting:
            raise KeyboardInterrupt

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, name, None)
        if signum is not None:
            try:
                signal.signal(signum, request_stop)
            except (OSError, ValueError):
                pass


def cmd_profiles(_args):
    from core.profiles import ProfileManager

    manager = ProfileManager()
    names = sorted(manager.available_profiles)
    if not names:
        _say(f"No profiles in {manager.profiles_path}")
        return EXIT_ERROR
    for name in names:
        profile = manager.available_profiles[name]
        _say(f"{name}  ({profile.get_value('company name') or 'no company name'})")
    return EXIT_OK


def cmd_create_admin(args):
    manager, _profile = _load_profile(args.profile)
    password = None
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise SystemExit("No password received on standard input.")
        if not args.username:
            raise SystemExit("--password-stdin needs --username.")
    try:
        database = _open_database(manager)
    except Exception as error:
        raise SystemExit(f"Could not connect to PostgreSQL: {_one_line(error)}")
    try:
        _create_admin(database, args.username, password)
    finally:
        database.close()
    return EXIT_OK


def cmd_serve(args):
    if not 1 <= args.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535.")
    manager, profile = _load_profile(args.profile)
    from core.network.server import port_in_use

    if port_in_use(args.port):
        raise SystemExit(
            f"Port {args.port} is already in use. If the desktop app is hosting, "
            "stop hosting there first, or pick another port with --port."
        )
    from core import diagnostics

    diagnostics.set_mode("host")
    logger.info("headless_server_startup build_id=%s pid=%d port=%d",
                APP_BUILD_ID, os.getpid(), args.port)
    supervisor = _Supervisor(manager, profile, args.port)
    _install_stop_signals(supervisor)
    try:
        return supervisor.run()
    finally:
        logger.info("headless_server_shutdown pid=%d", os.getpid())


def cmd_status(args):
    """Exit 0 when a server answers on the port. The health endpoint needs a
    login, so an HTTP 401 is the proof that the service is alive."""
    url = f"http://{args.host}:{args.port}/health"
    try:
        urllib.request.urlopen(url, timeout=3).close()
    except urllib.error.HTTPError as error:
        if error.code == 401:
            _say(f"Running on {args.host}:{args.port}")
            return EXIT_OK
        _say(f"Answering on {args.host}:{args.port} with HTTP {error.code}")
        return EXIT_ERROR
    except Exception as error:
        _say(f"Not reachable on {args.host}:{args.port} ({error})")
        return EXIT_ERROR
    _say(f"Running on {args.host}:{args.port}")
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(
        prog="server",
        description="Host a PyLocalInventory profile on the network without the desktop window.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    profiles = commands.add_parser("profiles", help="list the profiles on this computer")
    profiles.set_defaults(handler=cmd_profiles)

    admin = commands.add_parser("create-admin", help="create a super admin account")
    admin.add_argument("--profile", help="profile name (optional when only one exists)")
    admin.add_argument("--username", help="account name (asked when omitted)")
    admin.add_argument("--password-stdin", action="store_true",
                       help="read the password from standard input instead of prompting")
    admin.set_defaults(handler=cmd_create_admin)

    serve = commands.add_parser("serve", help="start hosting until stopped")
    serve.add_argument("--profile", help="profile name (optional when only one exists)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT,
                       help=f"TCP port to listen on (default {DEFAULT_PORT})")
    serve.set_defaults(handler=cmd_serve)

    status = commands.add_parser("status", help="check whether a server is answering")
    status.add_argument("--host", default="127.0.0.1")
    status.add_argument("--port", type=int, default=DEFAULT_PORT)
    status.set_defaults(handler=cmd_status)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    from core.logging_config import setup_logging

    setup_logging()
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
