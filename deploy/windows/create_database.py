"""Create the NEXTCAM database and its SQL login (what create-database.sql does by hand).

Run by install.ps1 -CreateDatabase with the new release's Python (pyodbc is installed
there). Everything comes from the environment, so no password is on a command line:

    NEXTCAM_INSTALL_SQL_SERVER          e.g. localhost or .\\SQLEXPRESS
    NEXTCAM_INSTALL_DATABASE            e.g. nextcam
    NEXTCAM_INSTALL_SQL_USER            the program's login, e.g. nextcam_app
    NEXTCAM_INSTALL_SQL_PASSWORD        its password
    NEXTCAM_INSTALL_SQL_ADMIN_USER      a sysadmin login; empty = Windows authentication
    NEXTCAM_INSTALL_SQL_ADMIN_PASSWORD

Safe to run again: an existing database or login is kept (an existing login's password is
NOT changed; the script then checks that the given password opens the database). Least
privilege as in create-database.sql. Exit code 0 = ready, 1 = error (message on stderr).
"""

from __future__ import annotations

import os
import re
import sys

import pyodbc

DRIVER = "ODBC Driver 18 for SQL Server"
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def env(name: str, required: bool = True) -> str:
    value = os.environ.get(name, "")
    if required and not value:
        raise SystemExit(f"{name} is not set")
    return value


def connect(server: str, database: str, user: str, password: str) -> pyodbc.Connection:
    secret = password.replace("}", "}}")
    auth = f"UID={{{user}}};PWD={{{secret}}};" if user else "Trusted_Connection=yes;"
    return pyodbc.connect(
        f"DRIVER={{{DRIVER}}};SERVER={server};DATABASE={database};{auth}"
        "TrustServerCertificate=yes;Encrypt=yes",
        autocommit=True,
        timeout=15,
    )


def literal(text: str) -> str:
    """An N'...' literal: CREATE LOGIN takes no parameters."""
    return "N'" + text.replace("'", "''") + "'"


def main() -> int:
    server = env("NEXTCAM_INSTALL_SQL_SERVER")
    database = env("NEXTCAM_INSTALL_DATABASE")
    login = env("NEXTCAM_INSTALL_SQL_USER")
    password = env("NEXTCAM_INSTALL_SQL_PASSWORD")
    admin = env("NEXTCAM_INSTALL_SQL_ADMIN_USER", required=False)
    admin_password = env("NEXTCAM_INSTALL_SQL_ADMIN_PASSWORD", required=False)
    for label, value in (("database name", database), ("login name", login)):
        if not NAME.match(value):
            print(f"invalid {label} {value!r}: letters, digits and _ only", file=sys.stderr)
            return 1

    try:
        c = connect(server, "master", admin, admin_password)
    except pyodbc.Error as e:
        how = f"login {admin!r}" if admin else "Windows authentication"
        print(f"cannot connect to SQL Server {server!r} with {how}: {e}", file=sys.stderr)
        return 1
    cur = c.cursor()
    if not cur.execute("SELECT IS_SRVROLEMEMBER('sysadmin')").fetchone()[0]:
        print("this SQL login is not sysadmin; use one that is (e.g. sa)", file=sys.stderr)
        return 1

    if cur.execute("SELECT 1 FROM sys.databases WHERE name = ?", database).fetchone():
        print(f"database {database} exists: kept")
    else:
        cur.execute(f"CREATE DATABASE [{database}]")
        print(f"database {database} created")
    cur.execute(
        f"ALTER DATABASE [{database}] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE"
    )

    if cur.execute("SELECT 1 FROM sys.server_principals WHERE name = ?", login).fetchone():
        print(f"login {login} exists: password left as it is")
    else:
        cur.execute(
            f"CREATE LOGIN [{login}] WITH PASSWORD = {literal(password)}, "
            f"CHECK_POLICY = ON, DEFAULT_DATABASE = [{database}]"
        )
        print(f"login {login} created")
    cur.execute(f"ALTER SERVER ROLE dbcreator ADD MEMBER [{login}]")
    for db, grant in (
        (database, f"ALTER ROLE db_owner ADD MEMBER [{login}]"),
        (
            "msdb",
            f"GRANT SELECT ON dbo.backupset TO [{login}]; "
            f"GRANT SELECT ON dbo.backupmediafamily TO [{login}]",
        ),
    ):
        cur.execute(
            f"USE [{db}]; IF USER_ID(?) IS NULL CREATE USER [{login}] FOR LOGIN [{login}]; {grant}",
            login,
        )
    c.close()

    try:
        connect(server, database, login, password).close()
    except pyodbc.Error as e:
        print(f"login {login} cannot open {database} with the given password: {e}", file=sys.stderr)
        return 1
    print("database ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
