import logging
import os
import sqlite3

from . import rdbms_common
from .blobfiles import FileStorage


class SqliteFileStorage(FileStorage):
    def __init__(self):
        pass

    def subdirFilename(self, classname, nodeid, property=None):
        pass

    def _tempfile(self, filename):
        pass

    def _editInProgress(self, classname, nodeid, property):
        pass

    def filename(self, classname, nodeid, property=None, create=0):
        pass

    def filesize(self, classname, nodeid, property=None, create=0):
        pass

    def storefile(self, classname, nodeid, property, content):
        pass

    def getfile(self, classname, nodeid, property):
        pass

    def numfiles(self):
        pass

    def numfiles(self):
        pass

    def rollbackStoreFile(self, classname, nodeid, property, **databases):
        pass

    def isStoreFile(self, classname, nodeid):
        pass

    def destroy(self, classname, nodeid):
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
    # TODO: some of this stuff should probably move back into rdbms_common
    def __init__(self, config, journaltag=None):
        self.logger = logging.getLogger('roundup.hyperdb')
        self.init_backend_config(config)
        super(Database, self).__init__(config, journaltag=journaltag)

    # TODO: implement in rdbmd_common
    def init_backend_config(self, config):
        self.sqlite_timeout = config.RDBMS_SQLITE_TIMEOUT

    def open_connection(self):
        """ Open a connection to the database, creating it if necessary.

            Must call self.load_dbschema()
        """
        # TODO: temporary DBs may not work because roundup frequently calls
        #   open/close
        db_name = self.config.RDBMS_NAME

        if not _temporary_db(db_name):
            db_name = os.path.join(self.config.DATABASE,
                                   self.config.RDBMS_NAME)

            # ensure the database directory exist
            if not os.path.isdir(os.path.dirname(db_name)):
                os.makedirs(os.path.dirname(db_name))

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

        self.load_dbschema()

#        return (conn, cursor)


    # hyperdb
    # roundupdb
