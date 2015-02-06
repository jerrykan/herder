import sqlite3
from os import path
from unittest import TestCase

from mock import patch

from roundup.configuration import CoreConfig
from roundup.backends.back_sqlite3 import Database, MissingSchema, _temporary_db


class TemporaryDbTest(TestCase):
    def test_temporary_db(self):
        self.assertTrue(_temporary_db(''))

    def test_inmemory_db_name(self):
        self.assertTrue(_temporary_db(':memory:'))

    def test_inmemory_db_file_name(self):
        self.assertTrue(_temporary_db('file::memory:'))

    def test_inmemory_db_query_param(self):
        self.assertTrue(_temporary_db(
            'file:memdb1?cached=shared&mode=memory'))

    def test_not_inmemory_db_query_param(self):
        self.assertFalse(_temporary_db(
            'file:memdb1?cached=shared'))


class OpenConnectionTest(TestCase):
    @patch('roundup.backends.back_sqlite3.sqlite3.connect')
    @patch('roundup.backends.back_sqlite3.os.makedirs')
    def test_temporary_db(self, m_makedirs, m_connect):
        config = CoreConfig()
        config.RDBMS_NAME = ':memory:'

        with patch.object(Database, 'load_dbschema') as m_load_dbschema:
            db = Database(config)

        self.assertEqual(m_makedirs.call_count, 0)
        self.assertEqual(m_connect.call_args, ((':memory:',), {
            'timeout': config.RDBMS_SQLITE_TIMEOUT,
        }))

    @patch('roundup.backends.back_sqlite3.sqlite3.connect')
    @patch('roundup.backends.back_sqlite3.os.makedirs')
    def test_file_db(self, m_makedirs, m_connect):
        config = CoreConfig()
        config.DATABASE = 'zzaaxx/db'
        config.RDBMS_NAME = 'roundup.db'

        with patch.object(Database, 'load_dbschema') as m_load_dbschema:
            db = Database(config)

        self.assertEqual(m_makedirs.call_count, 1)
        self.assertEqual(m_connect.call_args, (
            (path.join('.', 'zzaaxx', 'db', 'roundup.db'),),
            {'timeout': config.RDBMS_SQLITE_TIMEOUT}
        ))

    @patch('roundup.backends.back_sqlite3.sqlite3.connect')
    @patch('roundup.backends.back_sqlite3.os.makedirs')
    def test_schema_error(self, m_makedirs, m_connect):
        config = CoreConfig()
        config.DATABASE = 'zzaaxx/db'
        config.RDBMS_NAME = 'roundup.db'

        with (patch.object(Database, 'load_dbschema') as m_load_dbschema,
              patch.object(Database, 'sql') as m_sql):
#            m_load_dbschema.side_effect = sqlite3.OperationalError
            m_load_dbschema.side_effect = MissingSchema
            db = Database(config)
