import os

from sqlalchemy import Column, Index, MetaData, Table, create_engine, types

from roundup import hyperdb, security
from roundup.backends import rdbms_common
from .rdbms_common import FileClass, IssueClass
from .sqlalchemy_common import SqlAlchemyDatabase

TYPE_MAP = {
    hyperdb.String: types.String,
    hyperdb.Date: types.DateTime,
    hyperdb.Link: types.Integer,
    hyperdb.Interval: types.Interval,
    hyperdb.Password: types.String,
    hyperdb.Boolean: types.Boolean,
    hyperdb.Number: types.Float,
}


class Class(rdbms_common.Class):
    pass


# TODO: placeholder
def db_exists(*args, **kwargs):
    return False


def _temporary_db(db_name):
    if db_name == '':
        return True

    if db_name.lower().startswith(':memory:'):
        return True

    return False


class Database(SqlAlchemyDatabase):
    def __init__(self, config, journaltag=None):
        ### TODO: ripped from rdbms_common
        self.classes = {}
        self.security = security.Security(self)
        ###

        # TODO: open logger
        self.journaltag = journaltag

        db_path = config.DATABASE
        db_name = config.RDBMS_NAME

        if not _temporary_db(db_name):
            if not os.path.isdir(db_path):
                os.makedirs(db_path)
            
            self.engine = create_engine('sqlite:///{0}'.format(
                os.path.join(db_path, db_name)))
        else:
            self.engine = create_engine('sqlite:///{0}'.format(db_name))

        self.conn = self.engine.connect()
        self.schema = MetaData(bind=self.engine)
        Table('otks', self.schema,
            Column('otk_key', types.String, index=True),
            Column('otk_value', types.String),
            Column('otk_time', types.Integer),
        )
        Table('sessions', self.schema,
            Column('session_key', types.String, index=True),
            Column('session_time', types.Integer),
            Column('session_value', types.String),
        )
        Table('__textids', self.schema,
            Column('_class', types.String),
            Column('_itemid', types.String),
            Column('_prop', types.String),
            Column('_textid', types.Integer, primary_key=True),
        )
        Table('__words', self.schema,
            Column('_word', types.String, index=True),
            Column('_textid', types.Integer, index=True),
        )
        Index('__textids_by_props',
            self.schema.tables['__textids'].columns._class,
            self.schema.tables['__textids'].columns._itemid,
            self.schema.tables['__textids'].columns._prop,
            unique=True,
        )
        # NOTE: we don't store the schema dump in db, it is checked in post_init

    def post_init(self):
        """ Called once the schema initialisation has finished.

            We should now confirm that the schema defined by our "classes"
            attribute actually matches the schema in the database.
        """
        # TODO: check if the database can be altered (config.RDBMS_ALLOW_ALTER)
        for classname, spec in self.classes.items():
            columns = [
               Column('_actor', TYPE_MAP[hyperdb.Link]),
               Column('_activity', TYPE_MAP[hyperdb.Date]),
               Column('_creator', TYPE_MAP[hyperdb.Link]),
               Column('_creation', TYPE_MAP[hyperdb.Date]),
            ]

            for name, prop in spec.properties.items():
                columns.append(
                    Column('_{0}'.format(name), TYPE_MAP[type(prop)]))

            columns.sort(key=lambda x: x.name)
            columns += [
               Column('id', types.Integer, primary_key=True),
               Column('__retired__', types.Boolean, default=False, index=True),
            ]

            Table('_{0}'.format(classname), self.schema, *columns)
    ##
    ## NOT TESTED BEYOND HERE
    ##

    # TODO: ripped from rdbms_common
    #   used by detectors
    def __getattr__(self, classname):
        """ A convenient way of calling self.getclass(classname).
        """
        if classname in self.classes:
            return self.classes[classname]
        raise AttributeError(classname)

    # TODO: taken from rdbms_common
    def addclass(self, class_):
        classname = class_.classname
        if classname in self.classes:
            raise ValueError(
                "'{0}' class has already be defined.".format(classname))

        self.classes[classname] = class_

        # TODO: not tested
        desc = 'User is allowed to {{0}} {0}'.format(classname)
        for perm in ('Create', 'Edit', 'View', 'Retire'):
            self.security.addPermission(
                name=perm, klass=classname,
                description=desc.format(perm.lower()))

    # TODO: ripped from rdbms_common
    #   used by instance.open()
    def getclasses(self):
        """ Return a list of the names of all existing classes.
        """
        return sorted(self.classes)

    # TODO: ripped from rdbms_common
    #   used by security.addPermissionToRole() in schema.py
    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError('There is no class called "%s"'%classname)
