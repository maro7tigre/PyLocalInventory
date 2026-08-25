"""
User/role/permission management for LAN network access.

Operates on an already-connected Database instance (its Users/Roles/RolePermissions
tables, created by Database._ensure_user_tables). This is server-side only - remote
clients never touch this module directly, they go through core.network.client.
"""
import hashlib
import secrets


# Maps every table/registered-section actually written to in the codebase onto the
# handful of sections shown in the permission matrix UI. Child/reference tables
# inherit their parent's permission (e.g. Sales_Items and Payments follow Sales).
SECTION_GROUP = {
    'Products': 'Products',
    'Door_Types': 'Products',
    'Wood_Types': 'Products',
    'Services': 'Services',
    'Clients': 'Clients',
    'Suppliers': 'Suppliers',
    'Sales': 'Sales',
    'Sales_Items': 'Sales',
    'Payments': 'Sales',
    'Imports': 'Imports',
    'Import_Items': 'Imports',
    'Reports': 'Reports',
    'Charges': 'Charges',
    'Charge_Categories': 'Charges',
    'Charge_Recurring_Templates': 'Charges',
    'Charge_Items': 'Charges',
}

# Postgres identifiers used in raw SQL (core/database.py, ui/**) are unquoted
# and get folded to lowercase by the parser, and call sites are inconsistent
# about the case they type ('sales' vs 'Sales'). Both forms hit the same
# physical table, so the permission lookup must be case-insensitive too, or a
# lowercase-cased query for a perfectly valid table (e.g. `FROM sales`) gets
# rejected as "no permission mapping" even though 'Sales' is a mapped section.
_SECTION_GROUP_CASEFOLD = {key.casefold(): value for key, value in SECTION_GROUP.items()}

MATRIX_SECTIONS = ['Products', 'Services', 'Clients', 'Suppliers', 'Sales', 'Imports', 'Reports', 'Charges']

_EMPTY_PERMISSIONS = {'read': False, 'write': False, 'delete': False}
_FULL_PERMISSIONS = {'read': True, 'write': True, 'delete': True}


def hash_password(password, salt=None):
    """PBKDF2-HMAC-SHA256 one-way hash. stdlib only - no new dependency needed."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100_000)
    return digest.hex(), salt


class UserManager:
    """Manages Users/Roles/RolePermissions rows in the profile's Postgres schema."""

    def __init__(self, database):
        self.database = database

    # ---------------- Roles ----------------

    def create_role(self, name):
        cur = self.database.cursor
        cur.execute("INSERT INTO Roles (name) VALUES (%s) RETURNING id", (name,))
        self.database.conn.commit()
        return cur.fetchone()[0]

    def rename_role(self, role_id, new_name):
        cur = self.database.cursor
        cur.execute("UPDATE Roles SET name = %s WHERE id = %s", (new_name, role_id))
        self.database.conn.commit()

    def delete_role(self, role_id):
        cur = self.database.cursor
        cur.execute("SELECT COUNT(*) FROM Users WHERE role_id = %s", (role_id,))
        if cur.fetchone()[0] > 0:
            raise ValueError("Cannot delete a role that is still assigned to users")
        cur.execute("DELETE FROM RolePermissions WHERE role_id = %s", (role_id,))
        cur.execute("DELETE FROM Roles WHERE id = %s", (role_id,))
        self.database.conn.commit()

    def list_roles(self):
        cur = self.database.cursor
        cur.execute("SELECT id, name FROM Roles ORDER BY name")
        return [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]

    def set_role_permission(self, role_id, section, can_read, can_write, can_delete):
        if section not in MATRIX_SECTIONS:
            raise ValueError(f"Unknown section: {section}")
        cur = self.database.cursor
        cur.execute(
            "INSERT INTO RolePermissions (role_id, section, can_read, can_write, can_delete) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT(role_id, section) DO UPDATE SET "
            "can_read=excluded.can_read, can_write=excluded.can_write, can_delete=excluded.can_delete",
            (role_id, section, int(can_read), int(can_write), int(can_delete))
        )
        self.database.conn.commit()

    def get_role_permissions(self, role_id):
        """Returns {section: {'read':bool,'write':bool,'delete':bool}} for every matrix section."""
        cur = self.database.cursor
        cur.execute(
            "SELECT section, can_read, can_write, can_delete FROM RolePermissions WHERE role_id = %s",
            (role_id,)
        )
        perms = {row[0]: {'read': bool(row[1]), 'write': bool(row[2]), 'delete': bool(row[3])}
                 for row in cur.fetchall()}
        for section in MATRIX_SECTIONS:
            perms.setdefault(section, dict(_EMPTY_PERMISSIONS))
        return perms

    # ---------------- Users ----------------

    def create_user(self, username, password, role_id=None, is_superadmin=False):
        cur = self.database.cursor
        cur.execute("SELECT COUNT(*) FROM Users WHERE username = %s", (username,))
        if cur.fetchone()[0] > 0:
            raise ValueError(f"Username '{username}' already exists")
        password_hash, salt = hash_password(password)
        cur.execute(
            "INSERT INTO Users (username, password_hash, salt, role_id, is_superadmin) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (username, password_hash, salt, role_id, int(is_superadmin))
        )
        self.database.conn.commit()
        return cur.fetchone()[0]

    def delete_user(self, user_id):
        cur = self.database.cursor
        cur.execute("DELETE FROM Users WHERE id = %s", (user_id,))
        self.database.conn.commit()

    def list_users(self):
        cur = self.database.cursor
        cur.execute(
            "SELECT Users.id, Users.username, Users.role_id, Users.is_superadmin, Roles.name "
            "FROM Users LEFT JOIN Roles ON Users.role_id = Roles.id ORDER BY Users.username"
        )
        return [
            {'id': r[0], 'username': r[1], 'role_id': r[2], 'is_superadmin': bool(r[3]), 'role_name': r[4]}
            for r in cur.fetchall()
        ]

    def has_any_superadmin(self):
        cur = self.database.cursor
        cur.execute("SELECT COUNT(*) FROM Users WHERE is_superadmin = 1")
        return cur.fetchone()[0] > 0

    def change_password(self, user_id, new_password):
        password_hash, salt = hash_password(new_password)
        cur = self.database.cursor
        cur.execute("UPDATE Users SET password_hash = %s, salt = %s WHERE id = %s", (password_hash, salt, user_id))
        self.database.conn.commit()

    def set_user_role(self, user_id, role_id):
        cur = self.database.cursor
        cur.execute("UPDATE Users SET role_id = %s WHERE id = %s", (role_id, user_id))
        self.database.conn.commit()

    def verify_login(self, username, password):
        """Returns a dict describing the authenticated user (with resolved
        permissions), or None if the credentials are wrong."""
        cur = self.database.cursor
        cur.execute(
            "SELECT id, password_hash, salt, role_id, is_superadmin FROM Users WHERE username = %s",
            (username,)
        )
        row = cur.fetchone()
        if not row:
            return None
        user_id, password_hash, salt, role_id, is_superadmin = row
        check_hash, _ = hash_password(password, salt)
        if not secrets.compare_digest(check_hash, password_hash):
            return None

        is_superadmin = bool(is_superadmin)
        if is_superadmin:
            permissions = {s: dict(_FULL_PERMISSIONS) for s in MATRIX_SECTIONS}
        elif role_id:
            permissions = self.get_role_permissions(role_id)
        else:
            permissions = {s: dict(_EMPTY_PERMISSIONS) for s in MATRIX_SECTIONS}

        return {
            'id': user_id,
            'username': username,
            'is_superadmin': is_superadmin,
            'role_id': role_id,
            'permissions': permissions,
        }

    @staticmethod
    def section_for_table(table_name):
        """Resolve a raw-SQL table name to its canonical permission section.

        Accepts any case ('sales', 'Sales') and an optional schema qualifier
        ('public.sales') so every valid spelling of a mapped table resolves
        to the same section - this is an exact, case-insensitive match
        against SECTION_GROUP's own keys, never fuzzy/substring matching, so
        an unmapped or unrelated table still correctly returns None.
        """
        if not table_name:
            return None
        bare = str(table_name).rsplit('.', 1)[-1]
        return _SECTION_GROUP_CASEFOLD.get(bare.casefold())
