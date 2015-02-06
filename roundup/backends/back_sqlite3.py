import logging
import os
import sqlite3

from . import rdbms_common
from .blobfiles import FileStorage


class MissingSchema(sqlite3.OperationalError):
    pass


def _temporary_db(db_name):
    if db_name == '':
        return True

    if db_name.lower().startswith(':memory:'):
        return True

    if db_name.lower().startswith('file::memory:'):
        return True

    try:
        params = db_name.split('?', 1)[1].split('&')
        if 'mode=memory' in params:
            return True
    except IndexError:
        pass

    return False


#class Database(SqliteFileStorage, rdbms_common.Database):
class Database(rdbms_common.Database, object):
    arg = '?'

    # TODO: some of this stuff should probably move back into rdbms_common
    def __init__(self, config, journaltag=None):
        self.logger = logging.getLogger('roundup.hyperdb')

        self.db_name = config.RDBMS_NAME
        self.db_path = config.DATABASE
        self.init_backend_config(config)

        super(Database, self).__init__(config, journaltag=journaltag)

    # TODO: implement in rdbmd_common
    def init_backend_config(self, config):
        self.sqlite_timeout = config.RDBMS_SQLITE_TIMEOUT

    # TODO: overriden rdbms_common
    def load_dbschema(self):
        """ Load the schema definition that the database currently implements
        """
        try:
            self.cursor.execute('select schema from schema')
        except sqlite3.OperationalError as err:
            raise MissingSchema(str(err))

        schema = self.cursor.fetchone()
        if schema:
            self.database_schema = eval(schema[0])
        else:
            self.database_schema = {}

    def open_connection(self):
        """ Open a connection to the database, creating it if necessary.

            Must call self.load_dbschema()
        """
        #
        # TODO: temporary DBs may not work because roundup frequently calls
        #   open/close
        if not _temporary_db(self.db_name):
            db_name = os.path.join(self.db_path, self.db_name)

            # ensure the database directory exist
            if not os.path.isdir(os.path.dirname(db_name)):
                os.makedirs(os.path.dirname(db_name))
        else:
            db_name = self.db_name

        self.logger.info('open database %s', db_name)
        self.conn = sqlite3.connect(db_name, timeout=self.sqlite_timeout)
        self.conn.row_factory = sqlite3.Row

        # sqlite3 want us to store Unicode in the db but that's not what's been
        # done historically and it's definitely not what the other backends do,
        # so we'll stick with UTF-8
        # TODO PYTHON3: this will need to be looked at when str defaults to
        #   unicode
        self.conn.text_factory = str

        self.cursor = self.conn.cursor()

        try:
            self.load_dbschema()
            return
        except MissingSchema:
            pass

        self.init_dbschema()

        # TODO SQLALCHEMY: handle database create/migrate stuff
        # create schema table
        self.sql('CREATE TABLE schema (schema TEXT)')
        # create ids table
        self.sql('CREATE TABLE ids (name TEXT, num INTEGER)')
        self.sql('CREATE INDEX ids_name_idx ON ids (name)')
        # create otks table
        self.sql(
            'CREATE TABLE otks ' +
            '(otk_key TEXT, otk_value TEXT, otk_time INTEGER)')
        self.sql('CREATE INDEX otks_key_idx ON otks (otk_key)')
        # create sessions table
        self.sql(
            'CREATE TABLE sessions ' +
            '(session_key TEXT, session_time INTEGER, session_value TEXT)')
        self.sql('CREATE INDEX sessions_key_idx ON sessions (session_key)')

        # full-text indexing store
        self.sql('CREATE TABLE __textids ' +
            '(_class varchar, _itemid TEXT, _prop TEXT, ' +
            '_textid INTEGER PRIMARY KEY)')
        self.sql(
            'CREATE UNIQUE INDEX __textids_by_props ' +
            'ON __textids (_class, _itemid, _prop)')

        self.sql('CREATE TABLE __words (_word TEXT, _textid INTEGER)')
        self.sql('CREATE INDEX words_word_ids ON __words(_word)')
        self.sql('CREATE INDEX words_by_id ON __words(_textid)')

        self.sql('INSERT INTO ids (name, num) VALUES (?, ?)', ('__textids', 1))


    # hyperdb
    # roundupdb


class Class(rdbms_common.Class):
    pass


class FileClass(rdbms_common.FileClass):
    pass


class IssueClass(rdbms_common.IssueClass):
    pass
