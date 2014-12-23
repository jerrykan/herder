from roundup.hyperdb import Database

class SQLAlchemyDatabase(Database, object):
    def __init__(self, config, journaltag=None):
        """Open a hyperdatabase given a specifier to some storage.

        The 'storagelocator' is obtained from config.DATABASE.
        The meaning of 'storagelocator' depends on the particular
        implementation of the hyperdatabase.  It could be a file name,
        a directory path, a socket descriptor for a connection to a
        database over the network, etc.

        The 'journaltag' is a token that will be attached to the journal
        entries for any edits done on the database.  If 'journaltag' is
        None, the database is opened in read-only mode: the Class.create(),
        Class.set(), and Class.retire() methods are disabled.
        """
        raise NotImplementedError

    def post_init(self):
        """Called once the schema initialisation has finished.
           If 'refresh' is true, we want to rebuild the backend
           structures.
        """
        raise NotImplementedError

    def __getattr__(self, classname):
        """A convenient way of calling self.getclass(classname)."""
        raise NotImplementedError

    def addclass(self, cl):
        """Add a Class to the hyperdatabase.
        """
        raise NotImplementedError

    def getclasses(self):
        """Return a list of the names of all existing classes."""
        raise NotImplementedError

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        raise NotImplementedError

    def addnode(self, classname, nodeid, node):
        """Add the specified node to its class's db.
        """
        raise NotImplementedError

    def getnode(self, classname, nodeid):
        """Get a node from the database.

        'cache' exists for backwards compatibility, and is not used.
        """
        raise NotImplementedError

    def hasnode(self, classname, nodeid):
        """Determine if the database has a given node.
        """
        raise NotImplementedError

    def pack(self, pack_before):
        """ pack the database
        """
        raise NotImplementedError

    def commit(self):
        """ Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().

        fail_ok indicates that the commit is allowed to fail. This is used
        in the web interface when committing cleaning of the session
        database. We don't care if there's a concurrency issue there.

        The only backend this seems to affect is postgres.
        """
        raise NotImplementedError

    def rollback(self):
        """ Reverse all actions from the current transaction.

        Undo all the changes made since the database was opened or the last
        commit() or rollback() was performed.
        """
        raise NotImplementedError

    def close(self):
        """Close the database.

        This method must be called at the end of processing.

        """
        raise NotImplementedError

    ### RDBMS_COMMON
    def getSessionManager(self):
        raise NotImplementedError

    def getOTKManager(self):
        raise NotImplementedError

    def reindex(self, classname=None, show_progress=False):
        raise NotImplementedError

    ### DRIVERS
    def setid(self, classname, setid):
        """ Set the id counter: used during import of database

        We add one to make it behave like the sequences in postgres.
        """
        # if we use auto-counters we won't need this... hopefully
        raise NotImplementedError

