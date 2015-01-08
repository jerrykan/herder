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
                # create pivot table for Multilink
                if isinstance(prop, hyperdb.Multilink):
                    Table('{0}_{1}'.format(classname, name), self.schema,
                        Column('linkid', types.Integer, index=True),
                        Column('nodeid', types.Integer, index=True),
                    )
                    continue

                columns.append(
                    Column('_{0}'.format(name), TYPE_MAP[type(prop)]))

            columns.sort(key=lambda x: x.name)
            columns += [
               Column('id', types.Integer, primary_key=True),
               Column('__retired__', types.Boolean, default=False, index=True),
            ]

            table = Table('_{0}'.format(classname), self.schema, *columns)

            # key property indexes
            if spec.key:
                Index('_{0}_{1}_idx'.format(classname, spec.key),
                    table.columns['_{0}'.format(spec.key)],
                )
                # TODO: check for changing key and alter index accordingly
                Index('_{0}_key_retired_idx'.format(classname),
                    table.columns.__retired__,
                    table.columns['_{0}'.format(spec.key)],
                    unique=True
                )

            # journal table
            Table('{0}__journal'.format(classname), self.schema,
                Column('nodeid', types.Integer, index=True),
                Column('date', TYPE_MAP[hyperdb.Date]),
                Column('tag', types.String),
                Column('action', types.String),
                Column('params', types.String),
            )

        # determine differences between the schema.py spec and the DB
        db = MetaData(bind=self.engine)
        db.reflect()
        db_tables = set(db.tables.keys())
        schema_tables = set(self.schema.tables.keys())

        db_indexes = {}
        for table in db.tables.values():
            for index in table.indexes:
                db_indexes[index.name] = index

        schema_indexes = {}
        for table in self.schema.tables.values():
            for index in table.indexes:
                schema_indexes[index.name] = index

        # drop tables
        drop_tables = db_tables - schema_tables
        for table in drop_tables:
            db.tables[table].drop()

        # drop indexes
        for index_name in (set(db_indexes) - set(schema_indexes)):
            if db_indexes[index_name].table.name not in drop_tables:
                db_indexes[index_name].drop()

        # modify tables
        for table_name in (db_tables & schema_tables):
            db_columns = set([c.name for c in db.tables[table_name].columns])
            schema_columns = set([c.name for c in self.schema.tables[table_name].columns])
            alter = {
                'add': [
                    self.schema.tables[table_name].columns[c]
                    for c in (schema_columns - db_columns)
                ],
                'drop': [
                    db.tables[table_name].columns[c]
                    for c in (db_columns - schema_columns)
                ],
                'change': [],
            }

            for column in (db_columns & schema_columns):
                db_type = db.tables[table_name].columns[column].type
                schema_type = self.schema.tables[table_name].columns[column].type

                if not isinstance(db_type, type(schema_type)):
                    alter['change'].append(
                        self.schema.tables[table_name].columns[column])

            if len(alter['change']) > 0:
                column = alter['change'][0]
                raise NotImplementedError(
                    'modifying schema class property types is not supported ' +
                    "'{0}.{1}'".format(column.table.name[1:], column.name[1:]))
            elif len(alter['drop']) > 0:
                # create new table without indexes
                tmp_name = '_tmp_{0}'.format(table_name)
                table = Table(tmp_name, db,
                    *[c.copy() for c in self.schema.tables[table_name].columns])
                table.create()

                for index in table.indexes:
                    index.drop()

                # TODO: FIX: safer to use sqlalchemy instead of raw SQL?
                # copy entries from the old to the new table
                columns = ', '.join(
                    [c for c in (db_columns & schema_columns)])

                sql = 'INSERT INTO {0} ({2}) SELECT {2} FROM {1}'.format(
                    tmp_name, table_name, columns)
                self.engine.execute(sql)

                # drop the old table
                db.tables[table_name].drop()

                # rename the new table
                sql = 'ALTER TABLE {0} RENAME TO {1}'.format(
                    tmp_name, table_name)
                self.engine.execute(sql)
            else:
                for column in alter['add']:
                    sql = 'ALTER TABLE {0} ADD COLUMN {1} {2}'.format(
                        column.table, column.name, column.type.compile())
                    self.engine.execute(sql)

        # modify indexes
        for index in (set(db_indexes) & set(schema_indexes)):
            if (db_indexes[index].columns.keys() !=
                    schema_indexes[index].columns.keys()):
                db_indexes[index].drop()
                schema_indexes[index].create()

        # create tables
        create_tables = schema_tables - db_tables
        for table in create_tables:
            self.schema.tables[table].create(self.engine)

        # create indexes
        for index in (set(schema_indexes) - set(db_indexes)):
            if schema_indexes[index].table.name not in create_tables:
                schema_indexes[index].create()

        # TODO: (re)indexing


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
