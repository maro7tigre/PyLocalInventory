"""Single source of truth for the running application's build identifier.

Bump APP_BUILD_ID whenever attachment/permission/networking code changes.
Editing source files does NOT change what a packaged .exe on a Host or
Client PC actually runs - this string is the only reliable way to confirm,
from the logs, that a given machine is running the build that contains a
given fix rather than a stale one.
"""

APP_BUILD_ID = "sales-table-total-ht-ttc-2026-08-05-v2"
