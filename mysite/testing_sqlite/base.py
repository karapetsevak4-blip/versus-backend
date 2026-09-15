from django.db.backends.sqlite3.base import DatabaseWrapper as SQLiteWrapper
from .operations import DatabaseOperations


class DatabaseWrapper(SQLiteWrapper):
    ops_class = DatabaseOperations
    # Django 5.1 emits varchar(None) for PostgreSQL's unlimited CharFields.
    # SQLite has no varchar length enforcement either; use TEXT in tests only.
    # This does NOT emulate PostgreSQL locking, precision or concurrency.
    data_types = {**SQLiteWrapper.data_types, 'CharField': 'text'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.features.supports_unlimited_charfield = True
