import os
from datetime import datetime, timedelta

from sqlalchemy import Column, Index, MetaData, Table, create_engine, types
from sqlalchemy.sql import and_, func, select

from roundup import hyperdb, security
from roundup.backends import rdbms_common
from roundup.date import Date, Interval
from roundup.i18n import _
from roundup.password import Password
from .rdbms_common import FileClass, IssueClass
from .sqlalchemy_common import SqlAlchemyDatabase

def boolean_validator(name, value):
    try:
        # TODO: this is how rdbms_common checks for boolean, but I
        #   suspect it dates back to when python didn't have bools
        int(value)
        return value
    except (TypeError, ValueError):
        raise TypeError(
            "value for property '{0}' is not a boolean".format(name))


def number_validator(name, value):
    try:
        float(value)
        return value
    except (TypeError, ValueError):
        raise TypeError(
            "value for property '{0}' is not numeric".format(name))


def string_validator(name, value):
    if isinstance(value, (str, unicode)):
        return value

    raise TypeError("value for property '{0}' is not a string".format(name))


def password_validator(name, value):
    if isinstance(value, Password):
        return str(value)

    raise TypeError("value for property '{0}' is not a roundup password"
        .format(name))


def date_validator(name, value):
    if isinstance(value, Date):
        return datetime(
            value.year, value.month, value.day,
            value.hour, value.minute, int(value.second),
            int((value.second * 1000000) % 1000000))

    raise TypeError("value for property '{0}' is not a roundup date"
        .format(name))


def interval_validator(name, value):
    if isinstance(value, Interval):
        return timedelta(seconds=value.as_seconds())

    raise TypeError("value for property '{0}' is not a roundup interval"
        .format(name))


TYPE_MAP = {
    hyperdb.String: types.String,
    hyperdb.Date: types.DateTime,
    hyperdb.Link: types.Integer,
    hyperdb.Interval: types.Interval,
    hyperdb.Password: types.String,
    hyperdb.Boolean: types.Boolean,
    hyperdb.Number: types.Float,
}


#class Class(rdbms_common.Class):
class Class(hyperdb.Class):
    def create(self, **propvalues):
        """ Create a new node of this class and return its id.

        The keyword arguments in 'propvalues' map property names to values.

        The values of arguments must be acceptable for the types of their
        corresponding properties or a TypeError is raised.

        If this class has a key property, it must be present and its value
        must not collide with other key strings or a ValueError is raised.

        Any other properties on this class that are missing from the
        'propvalues' dictionary are set to None.

        If an id in a link or multilink property does not refer to a valid
        node, an IndexError is raised.
        """

        # TODO: fire auditor

        if self.db.journaltag is None:
            raise hyperdb.DatabaseError(_('Database open read-only'))

        if 'id' in propvalues:
            raise KeyError("'id' is a reserved class property")

        if set(['activity', 'actor', 'creation', 'creator']) & set(propvalues):
            raise KeyError("'activity', 'actor', 'creation', and 'creator' " +
                           "are reserved class properties")

        error_msg = "value for new property '{0}' is not {1}"
        for prop_name, value in propvalues.items():
            try:
                prop = self.properties[prop_name]
            except KeyError:
                raise KeyError("'{0}' class has no '{1}' property".format(
                    self.classname, prop_name))

            if value is None:
                continue

            if isinstance(prop, hyperdb.Boolean):
                try:
                    # TODO: this is how rdbms_common checks for boolean, but I
                    #   suspect it dates back to when python didn't have bools
                    int(value)
                except (TypeError, ValueError):
                    raise TypeError(
                        error_msg.format(prop_name, 'a boolean'))
            elif isinstance(prop, hyperdb.Number):
                try:
                    float(value)
                except (TypeError, ValueError):
                    raise TypeError(
                        error_msg.format(prop_name, 'numeric'))
            elif isinstance(prop, hyperdb.String):
                if not isinstance(value, (str, unicode)):
                    raise TypeError(
                        error_msg.format(prop_name, 'a string'))
                # TODO: indexing of the string
            elif isinstance(prop, hyperdb.Password):
                if not isinstance(value, Password):
                    raise TypeError(
                        error_msg.format(prop_name, 'a roundup password'))

                propvalues[prop_name] = str(value)
            elif isinstance(prop, hyperdb.Date):
                if not isinstance(value, Date):
                    raise TypeError(
                        error_msg.format(prop_name, 'a roundup date'))

                propvalues[prop_name] = datetime(
                    value.year, value.month, value.day,
                    value.hour, value.minute, int(value.second),
                    int((value.second * 1000000) % 1000000))
            elif isinstance(prop, hyperdb.Interval):
                if not isinstance(value, Interval):
                    raise TypeError(
                        error_msg.format(prop_name, 'a roundup interval'))

                propvalues[prop_name] = timedelta(seconds=value.as_seconds())
            elif isinstance(prop, hyperdb.Link):
                link_classname = self.properties[prop_name].classname
                try:
                    # TODO: ints not valid with legacy backends - not sure why
                    nodeid = int(value)
                    if not self.db.getclass(link_classname).hasnode(nodeid):
                        raise IndexError(
                            "class '{0}' has no node with id '{1}'".format(
                                link_classname, nodeid))
                except ValueError:
                    try:
                        nodeid = self.db.getclass(link_classname).lookup(value)
                    except KeyError:
                        raise IndexError(
                            "class '{0}' has no node with key value '{1}'".format(
                                link_classname, value))
                propvalues[prop_name] = nodeid
                # do some journaling
            elif isinstance(prop, hyperdb.Multilink):
                try:
                    if isinstance(value, (str, unicode)):
                        raise TypeError
                    values = set(value)
                except TypeError:
                    raise TypeError(
                        error_msg.format(prop_name, 'an iterable of node ids'))

                link_classname = self.properties[prop_name].classname
                propvalues[prop_name] = []
                links = set()
                for val in values:
                    try:
                        # TODO: ints not valid with legacy backends
                        nodeid = int(val)
                        if not self.db.getclass(link_classname).hasnode(nodeid):
                            raise IndexError(
                                "class '{0}' has no node with id '{1}'".format(
                                    link_classname, nodeid))
                    except ValueError:
                        try:
                            nodeid = self.db.getclass(link_classname).lookup(val)
                        except KeyError:
                            raise IndexError(
                                "class '{0}' has no node with key value '{1}'".format(
                                    link_classname, val))
                    links.add(nodeid)

                # TODO: multilink supports lists or sets
                propvalues[prop_name] = list(links)
                # do some journaling

        if self.key:
            try:
                key_value = propvalues[self.key]
            except KeyError:
                raise ValueError(
                    "class '{0}' requires a value for key property '{1}'".format(
                        self.classname, self.key))

            try:
                self.lookup(key_value)
            except KeyError:
                pass
            else:
                raise ValueError(
                    "node for class '{0}' already exists with key ({1}) value '{2}'".format(
                        self.classname, self.key, key_value))

        nodeid = self.db.addnode(self.classname, None, propvalues)
        # do journaling if required
        return nodeid

    def lookup(self, keyvalue):
        """Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        'keyvalue' matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        """
        if not self.key:
            raise TypeError("No key property set for class '{0}'".format(
                self.classname))

        table = self.db.schema.tables['_{0}'.format(self.classname)]
        query = (
            select([table.columns['id']])
            .where(and_(
                table.columns['_{0}'.format(self.key)] == keyvalue,
                table.columns['__retired__'] == False
            ))
        )
        result = self.db.conn.execute(query).fetchone()

        if result is None:
            raise KeyError(
                "'{0}' class has no key ({1}) with value '{2}'".format(
                    self.classname, self.key, keyvalue))

        # TODO: we are not returning a string
        return result[0]

    ##
    ## NOT TESTED BEYOND HERE
    ##

    # TODO: ripped from rdbms_common.Class
    def hasnode(self, nodeid):
        """Determine if the given nodeid actually exists
        """
        return self.db.hasnode(self.classname, nodeid)

    # TODO: ripped from rdbms_common.Class
    def setkey(self, propname):
        """Select a String property of this class to be the key property.

        'propname' must be the name of a String property of this class or
        None, or a TypeError is raised.  The values of the key property on
        all existing nodes must be unique or a ValueError is raised.
        """
        prop = self.getprops()[propname]
        if not isinstance(prop, hyperdb.String):
            raise TypeError('key properties must be String')
        self.key = propname

    # TODO: ripped from rdbms_common.Class
    # Manipulating properties:
    def getprops(self, protected=1):
        """Return a dictionary mapping property names to property objects.
           If the "protected" flag is true, we include protected properties -
           those which may not be modified.
        """
        d = self.properties.copy()
        if protected:
            d['id'] = hyperdb.String()
            d['creation'] = hyperdb.Date()
            d['activity'] = hyperdb.Date()
            d['creator'] = hyperdb.Link('user')
            d['actor'] = hyperdb.Link('user')
        return d

    def getnode(self, nodeid):
        raise NotImplementedError
        print "Class.getnode"
        return super(Class, self).getnode(nodeid)

    def history(self, nodeid):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def setlabelprop(self, labelprop):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def setorderprop(self, orderprop):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def labelprop(self, default_to_id=0):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def orderprop(self):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def _proptree(self, filterspec, sortattr=[], retr=False):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def get_transitive_prop(self, propname_path, default = None):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def _sortattr(self, sort=[], group=[]):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def filter(self, search_matches, filterspec, sort=[], group=[]):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def get_required_props(self, propnames = []):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

#    def audit(self, event, detector, priority = 100):

    def fireAuditors(self, event, nodeid, newvalues):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def react(self, event, detector, priority = 100):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def fireReactors(self, event, nodeid, oldvalues):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def export_propnames(self):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def import_journals(self, entries):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def get_roles(self, nodeid):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)

    def has_role(self, nodeid, *roles):
        raise NotImplementedError
        print "Class.history"
        return super(Class, self).history(nodeid)


# placeholder: not tested
def db_nuke(config):
    import shutil
    db_path = config.DATABASE
    db_name = config.RDBMS_NAME
    shutil.rmtree(db_path)


def _temporary_db(db_name):
    if db_name == '':
        return True

    if db_name.lower().startswith(':memory:'):
        return True

    return False


def db_exists(config):
    db_path = config.DATABASE
    db_name = config.RDBMS_NAME

    if _temporary_db(db_name):
        return False

    return os.path.isfile(os.path.join(db_path, db_name))


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

        # TODO: opening the connection probably should be its own method
        self.open()

    def open(self):
        self.conn = self.engine.connect()
        self.transaction = self.conn.begin()

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

            # TODO: don't create journal table if disabled in schema
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
                table.create(self.conn)

                for index in table.indexes:
                    index.drop(self.conn)

                # TODO: FIX: safer to use sqlalchemy instead of raw SQL?
                # copy entries from the old to the new table
                columns = ', '.join(
                    [c for c in (db_columns & schema_columns)])

                sql = 'INSERT INTO {0} ({2}) SELECT {2} FROM {1}'.format(
                    tmp_name, table_name, columns)
                self.conn.execute(sql)

                # drop the old table
                db.tables[table_name].drop()

                # rename the new table
                sql = 'ALTER TABLE {0} RENAME TO {1}'.format(
                    tmp_name, table_name)
                self.conn.execute(sql)
            else:
                for column in alter['add']:
                    sql = 'ALTER TABLE {0} ADD COLUMN {1} {2}'.format(
                        column.table, column.name, column.type.compile())
                    self.conn.execute(sql)

        # modify indexes
        for index in (set(db_indexes) & set(schema_indexes)):
            if (db_indexes[index].columns.keys() !=
                    schema_indexes[index].columns.keys()):
                db_indexes[index].drop()
                schema_indexes[index].create(self.conn)

        # create tables
        create_tables = schema_tables - db_tables
        for table in create_tables:
            self.schema.tables[table].create(self.conn)

        # create indexes
        for index in (set(schema_indexes) - set(db_indexes)):
            if schema_indexes[index].table.name not in create_tables:
                schema_indexes[index].create(self.conn)

        # TODO: (re)indexing

    def addnode(self, classname, nodeid, node):
        """Add the specified node to its class's db.

            Note: 'nodeid' is defined by hyperdb.Database.addnode() but is not
                used because we rely on the DBs inbuild autoincrement

            Note: this method returns a nodeid where as the method defined as
                hyperdb.Database.addnode() does not assume this is the case

            Note: there is no checking of multilink linkids, it is assumed that
                this contraint is check before invoking this method.
        """
        # TODO: log the add node action
        # TODO: clear node from cache ??
        class_ = self.classes[classname]
        props = class_.getprops()

        invalid_props = set(node) - set(props)
        if invalid_props:
            raise KeyError("'{0}' has no '{1}' property".format(
                    classname, list(invalid_props)[0]))

        values = node.copy()

        for prop in ('activity', 'creation'):
            if prop not in values:
                values[prop] = datetime.now()

        for prop in ('actor', 'creator'):
            if prop not in values:
                # TODO: the location of of getuid() is not obvious, the method
                #   is inherited from roundupdb.Database.getuid()
                values[prop] = self.getuid()

        multilink = {}
        for prop, type_ in props.items():
            if isinstance(type_, hyperdb.Multilink):
                try:
                    value = values[prop]
                except KeyError:
                    continue

                # TODO: multilink supports lists or sets
                if not isinstance(value, list):
                    raise ValueError(
                        "multilink property '{0}' must be a list".format(prop))

                if value:
                    multilink[prop] = value

                del values[prop]

        table = self.schema.tables['_{0}'.format(classname)]
        query = table.insert().values(**dict([
            ('_{0}'.format(k), v) for (k, v) in values.items()
            if v is not None
        ]))
        result = self.conn.execute(query)
        nodeid = result.inserted_primary_key[0]

        for name, links in multilink.items():
            table = self.schema.tables['{0}_{1}'.format(classname, name)]
            for link in links:
                query = table.insert().values(nodeid=nodeid, linkid=link)
                self.conn.execute(query)

        return nodeid

    def hasnode(self, classname, nodeid):
        """Determine if the database has a given node.
        """
        # TODO: does this need to exist? maybe only on Class class
        try:
            table = self.schema.tables['_{0}'.format(classname)]
        except KeyError:
            raise KeyError("class '{0}' does not exist".format(classname))

        query = (
            select([func.count()])
            .select_from(table)
            .where(table.columns['id'] == nodeid)
        )

        return bool(self.conn.execute(query).fetchone()[0])

    def commit(self):
        self.transaction.commit()

    def close(self):
        self.conn.close()

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
