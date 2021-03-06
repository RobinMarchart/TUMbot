import os
import re
import sqlite3
from pathlib import Path


class DatabaseManager:
    def __init__(self, dbpath):
        self._db_handles = {}
        self._dbpath = dbpath
        self._sqlpaths = []

    def get(self, dbid):
        dbid = str(dbid)

        if dbid not in self._db_handles:
            # Create the database directory if it doesn't exist
            if not os.path.isdir(self._dbpath):
                os.mkdir(self._dbpath)

            # Create a new connection
            self._db_handles[dbid] = sqlite3.connect(f"{self._dbpath}/{dbid}.db", check_same_thread=False)
            self._db_handles[dbid].row_factory = sqlite3.Row

            # Update database structure for internal usage
            self._upgrade_db_internal(self._db_handles[dbid])

            # Update database structure from external sources
            self._upgrade_db_external(self._db_handles[dbid])

        return self._db_handles[dbid]

    def add_sql_path(self, path):
        self._sqlpaths.append(path)

    @classmethod
    def _get_user_version(cls, conn):
        return conn.execute("PRAGMA user_version").fetchone()[0]

    @classmethod
    def _set_user_version(cls, conn, version):
        with conn as c:
            return c.execute(f"PRAGMA user_version = {int(version)}")

    @classmethod
    def _init_schema_version(cls, conn, schema):
        with conn as c:
            c.execute("INSERT OR IGNORE INTO version (name, version) VALUES (?, 0)", (schema,))

    @classmethod
    def _get_schema_version(cls, conn, schema):
        return conn.execute("SELECT version FROM version WHERE name = ?", (schema,)).fetchone()[0]

    @classmethod
    def _set_schema_version(cls, conn, schema, version):
        with conn as c:
            return c.execute("UPDATE version SET version = ? WHERE name = ?", (version, schema))

    @classmethod
    def _upgrade_db_internal(cls, conn):
        while True:
            user_version = cls._get_user_version(conn)
            path = f"basedbot/sql/internal_{user_version + 1}.sql"

            if not os.path.isfile(path):
                break

            with open(path) as file:
                conn.executescript(file.read())

    def _upgrade_db_external(self, conn):
        schemas = self._find_schemas()

        for schema, directory in schemas.items():
            # Insert a default starting version if it doesn't exist
            self._init_schema_version(conn, schema)

            # Backup old user_version and overwrite with schema version.
            # (I'm aware that this is a terribly bad idea. But it works.)
            user_ver = self._get_user_version(conn)
            self._set_user_version(conn, self._get_schema_version(conn, schema))

            try:
                while True:
                    version = self._get_user_version(conn)
                    path = f"{directory}/{schema}_{version + 1}.sql"

                    if not os.path.isfile(path):
                        break

                    with open(path) as file:
                        conn.executescript(file.read())
            finally:
                # Write back the current schema version and restore the old one
                self._set_schema_version(conn, schema, self._get_user_version(conn))
                self._set_user_version(conn, user_ver)

    def _find_schemas(self):
        schemas = {}

        for sqldir in self._sqlpaths:
            for filepath in Path(sqldir).glob('*_*.sql'):
                name = re.match(r'(\S+)_\d+', filepath.stem).group(1)

                if name in schemas and schemas[name] is not sqldir:
                    raise ValueError(f"Duplicate schema `{name}` found at `{sqldir}`,"
                                     f" but already present at `{schemas[name]}`")

                schemas[name] = sqldir

        return schemas

    def close(self):
        for dbid in self._db_handles:
            self._db_handles[dbid].close()

        self._db_handles.clear()
