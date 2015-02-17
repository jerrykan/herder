import time
from datetime import datetime, timedelta
from os import path

try:
    from unittest2 import TestCase
except ImportError:
    from unittest import TestCase

from mock import Mock, patch
from sqlalchemy import MetaData
from sqlalchemy.sql import select

from roundup import hyperdb
from roundup.backends.back_sqlite3 import Database, _temporary_db, types
from roundup.backends.back_sqlite3 import Class
from roundup.date import Date, Interval
from roundup.password import Password


class TemporaryDbTest(TestCase):
    def test_temporary_db(self):
        self.assertTrue(_temporary_db(''))

    def test_inmemory_db_name(self):
        self.assertTrue(_temporary_db(':memory:'))

    def test_filename_db(self):
        self.assertFalse(_temporary_db('roundup.db'))


@patch('roundup.backends.back_sqlite3.os.makedirs')
class InitDatabaseTest(TestCase):
    def setUp(self):
        self.config = Mock()
        self.config.DATABASE = 'db'
        self.config.RDBMS_NAME = ':memory:'

    def test_inmemory_db(self, m_makedirs):
        db = Database(self.config)

        self.assertEqual(m_makedirs.call_count, 0)

    def test_temporary_db(self, m_makedirs):
        self.config.RDBMS_NAME = ''
        db = Database(self.config)

        self.assertEqual(m_makedirs.call_count, 0)

    def test_filename_db(self, m_makedirs):
        self.config.RDBMS_NAME = 'roundup.db'

        p_isdir = patch('roundup.backends.back_sqlite3.os.path.isdir',
                        return_value=False)
        p_create_engine = patch('roundup.backends.back_sqlite3.create_engine')

        with p_isdir:
            with p_create_engine as m_create_engine:
                Database(self.config)

                self.assertEqual(
                    m_create_engine.call_args[0],
                    ('sqlite:///{0}'.format(path.join('db', 'roundup.db')),)
                )
                self.assertEqual(m_create_engine.call_args[1], {})

        self.assertEqual(m_makedirs.call_args, (('db',), {}))


class PostInitDatabaseTest(TestCase):
    def setUp(self):
        config = Mock()
        config.DATABASE = ''
        config.RDBMS_NAME = ''

        self.closed_db = Database(config)
        self.db = Database(config)
        self.db.engine = self.closed_db.engine
        self.db.schema.bind = self.db.engine

        self.default_tables = ['otks', 'sessions', '__textids', '__words']
        self.default_columns = ['_activity', '_actor', '_creation', '_creator',
                                'id', '__retired__']

    def test_empty_schema(self):
        self.db.post_init()

        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(self.default_tables)
        )

    def test_simple_class(self):
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        self.db.post_init()

        # check class table is correctly defined
        self.assertIn('_person', self.db.schema.tables)
        table = self.db.schema.tables['_person']
        table_columns = (
            ('_actor', types.Integer),
            ('_activity', types.DateTime),
            ('_creator', types.Integer),
            ('_creation', types.DateTime),
            ('_name', types.String),
            ('_age', types.Float),
            ('_birthday', types.DateTime),
            ('id', types.Integer),
            ('__retired__', types.Boolean),
        )

        self.assertEqual(
            set(table.columns.keys()),
            set([c[0] for c in table_columns])
        )
        for column, type_ in table_columns:
            self.assertTrue(isinstance(table.columns[column].type, type_))

        self.assertTrue(table.columns['id'].primary_key)
        self.assertEqual(len(table.indexes), 1)
        self.assertEqual(
            list(table.indexes)[0].columns.keys(), ['__retired__'])

        # check journal table is correctly defined
        self.assertIn('person__journal', self.db.schema.tables)
        journal = self.db.schema.tables['person__journal']
        journal_columns = (
            ('nodeid', types.Integer),
            ('date', types.DateTime),
            ('tag', types.String),
            ('action', types.String),
            ('params', types.String),
        )

        self.assertEqual(
            set(journal.columns.keys()),
            set([c[0] for c in journal_columns])
        )
        for column, type_ in journal_columns:
            self.assertTrue(isinstance(journal.columns[column].type, type_))

        self.assertEqual(len(journal.indexes), 1)
        self.assertEqual(
            list(journal.indexes)[0].columns.keys(), ['nodeid'])

        # check tables created in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(['_person', 'person__journal'] + self.default_tables)
        )

    def test_class_with_key(self):
        person = Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        person.setkey('name')
        self.db.post_init()

        self.assertIn('_person', self.db.schema.tables)
        table = self.db.schema.tables['_person']

        self.assertEqual(len(table.indexes), 3)
        indexes = dict((i.name, i) for i in table.indexes)
        self.assertEqual(
            indexes['ix__person___retired__'].columns.keys(),
            ['__retired__']
        )
        self.assertEqual(
            indexes['_person_key_retired_idx'].columns.keys(),
            ['__retired__', '_name']
        )
        self.assertEqual(
            indexes['_person_name_idx'].columns.keys(),
            ['_name']
        )

    def test_class_with_multilink(self):
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        task = Class(self.db, 'task',
            name=hyperdb.String()
        )
        self.db.post_init()

        self.assertIn('_person', self.db.schema.tables)
        self.assertIn('_task', self.db.schema.tables)
        self.assertIn('person_tasks', self.db.schema.tables)
        table = self.db.schema.tables['person_tasks']

        self.assertEqual(len(table.indexes), 2)
        indexes = dict((i.name, i) for i in table.indexes)
        self.assertEqual(
            indexes['ix_person_tasks_linkid'].columns.keys(),
            ['linkid']
        )
        self.assertEqual(
            indexes['ix_person_tasks_nodeid'].columns.keys(),
            ['nodeid']
        )

        # check tables created in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(['_person', 'person__journal', 'person_tasks', '_task',
                 'task__journal'] + self.default_tables)
        )

    def test_schema_add_class(self):
        # define "old" schema
        self.closed_db.post_init()

        # check "old" schema tables exist in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(self.default_tables)
        )

        # define "new" schema
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        self.db.post_init()

        # check tables have been created
        db.clear()
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(['_person', 'person__journal'] + self.default_tables)
        )

    def test_schema_drop_class(self):
        # define "old" schema
        Class(self.closed_db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        self.closed_db.post_init()

        # check "old" schema tables exist in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(['_person', 'person__journal'] + self.default_tables)
        )

        # define "new" schema
        self.db.post_init()

        # check tables have been dropped
        db.clear()
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(self.default_tables)
        )

    def test_schema_add_prop(self):
        # define "old" schema
        Class(self.closed_db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
        )
        self.closed_db.post_init()

        # check "old" schema columns exist in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables['_person'].columns.keys()),
            set(['_name', '_age'] + self.default_columns)
        )

        # define "new" schema
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        self.db.post_init()

        # check table column has been created
        db.clear()
        db.reflect()
        self.assertEqual(
            set(db.tables['_person'].columns.keys()),
            set(['_name', '_age', '_birthday'] + self.default_columns)
        )

    def test_schema_drop_prop(self):
        # define "old" schema
        Class(self.closed_db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        self.closed_db.post_init()

        # sqlite requires rebuilding the table, so lets insert some test data
        # so we can check that it gets migrated correctly
        person = self.closed_db.schema.tables['_person']
        people = []
        for i in range(1, 4):
            people.append({
                '_activity': datetime.now(),
                '_actor': 1,
                '_creation': datetime.now(),
                '_creator': 2,
                '_name': 'Person {0}'.format(i),
                '_age': (i+18),
                '_birthday': datetime.now(),
                'id': i,
                '__retired__': bool(i % 2),
            })
            query = person.insert().values(**people[-1])
            self.closed_db.engine.execute(query)

        # check "old" schema columns exist in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables['_person'].columns.keys()),
            set(['_name', '_age', '_birthday'] + self.default_columns)
        )

        # define "new" schema
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
        )
        self.db.post_init()

        # check table column has been created
        db.clear()
        db.reflect()
        self.assertEqual(
            set(db.tables['_person'].columns.keys()),
            set(['_name', '_age'] + self.default_columns)
        )

        query = select([db.tables['_person']])
        rows = self.db.engine.execute(query).fetchall()
        self.assertEqual(len(rows), 3)

        for i, row in enumerate(rows):
            for column in (['_name', '_age'] + self.default_columns):
                self.assertEqual(people[i][column], row[column])

    def test_schema_change_prop(self):
        # define "old" schema
        Class(self.closed_db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
        )
        self.closed_db.post_init()

        # check "old" schema columns exist in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables['_person'].columns.keys()),
            set(['_name', '_age'] + self.default_columns)
        )

        # define "new" schema
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.String(),
        )

        self.assertRaises(NotImplementedError, self.db.post_init)

    def test_schema_add_multilink(self):
        # define "old" schema
        Class(self.closed_db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        self.closed_db.post_init()

        # check "old" schema tables exist in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(['_person', 'person__journal'] + self.default_tables)
        )

        # define "new" schema
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        Class(self.db, 'task',
            name=hyperdb.String()
        )
        self.db.post_init()

        # check tables have been created
        db.clear()
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(['_person', 'person__journal', '_task', 'task__journal',
                 'person_tasks'] + self.default_tables)
        )

    def test_schema_drop_multilink(self):
        # define "old" schema
        Class(self.closed_db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        Class(self.closed_db, 'task',
            name=hyperdb.String(),
        )
        self.closed_db.post_init()

        # check "old" schema tables exist in DB
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(['_person', 'person__journal', '_task', 'task__journal',
                 'person_tasks'] + self.default_tables)
        )

        # define "new" schema
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        self.db.post_init()

        # check tables have been dropped
        db.clear()
        db.reflect()
        self.assertEqual(
            set(db.tables.keys()),
            set(['_person', 'person__journal'] + self.default_tables)
        )

    # TODO: change multilink?

    def test_schema_add_key_index(self):
        # define "old" schema
        Class(self.closed_db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        self.closed_db.post_init()

        # check "old" schema indexes
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(len(db.tables['_person'].indexes), 1)
        self.assertEqual(
            [c.name for c in list(db.tables['_person'].indexes)[0].columns],
            ['__retired__']
        )

        # define "new" schema
        person = Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        person.setkey('name')
        self.db.post_init()

        # check "new" schema indexes
        db.clear()
        db.reflect()
        self.assertEqual(len(db.tables['_person'].indexes), 3)
        indexes = dict((i.name, i) for i in db.tables['_person'].indexes)
        self.assertEqual(
            indexes['ix__person___retired__'].columns.keys(),
            ['__retired__']
        )
        self.assertEqual(
            indexes['_person_key_retired_idx'].columns.keys(),
            ['__retired__', '_name']
        )
        self.assertEqual(
            indexes['_person_name_idx'].columns.keys(),
            ['_name']
        )

    def test_schema_drop_key_index(self):
        # define "old" schema
        person = Class(self.closed_db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        person.setkey('name')
        self.closed_db.post_init()

        # check "old" schema indexes
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(len(db.tables['_person'].indexes), 3)
        indexes = dict((i.name, i) for i in db.tables['_person'].indexes)
        self.assertEqual(
            indexes['ix__person___retired__'].columns.keys(),
            ['__retired__']
        )
        self.assertEqual(
            indexes['_person_key_retired_idx'].columns.keys(),
            ['__retired__', '_name']
        )
        self.assertEqual(
            indexes['_person_name_idx'].columns.keys(),
            ['_name']
        )

        # define "new" schema
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        self.db.post_init()

        # check "new" schema indexes
        db.clear()
        db.reflect()
        self.assertEqual(len(db.tables['_person'].indexes), 1)
        self.assertEqual(
            [c.name for c in list(db.tables['_person'].indexes)[0].columns],
            ['__retired__']
        )

    def test_schema_change_key_index(self):
        # define "old" schema
        person = Class(self.closed_db, 'person',
            name=hyperdb.String(),
            alias=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        person.setkey('name')
        self.closed_db.post_init()

        # check "old" schema indexes
        db = MetaData(bind=self.db.engine)
        db.reflect()
        self.assertEqual(len(db.tables['_person'].indexes), 3)
        indexes = dict((i.name, i) for i in db.tables['_person'].indexes)
        self.assertEqual(
            indexes['ix__person___retired__'].columns.keys(),
            ['__retired__']
        )
        self.assertEqual(
            indexes['_person_key_retired_idx'].columns.keys(),
            ['__retired__', '_name']
        )
        self.assertEqual(
            indexes['_person_name_idx'].columns.keys(),
            ['_name']
        )

        # define "new" schema
        person = Class(self.db, 'person',
            name=hyperdb.String(),
            alias=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date(),
            tasks=hyperdb.Multilink('task')
        )
        person.setkey('alias')
        self.db.post_init()

        # check "new" schema indexes
        db.clear()
        db.reflect()
        self.assertEqual(len(db.tables['_person'].indexes), 3)
        indexes = dict((i.name, i) for i in db.tables['_person'].indexes)
        self.assertEqual(
            indexes['ix__person___retired__'].columns.keys(),
            ['__retired__']
        )
        self.assertEqual(
            indexes['_person_key_retired_idx'].columns.keys(),
            ['__retired__', '_alias']
        )
        self.assertEqual(
            indexes['_person_alias_idx'].columns.keys(),
            ['_alias']
        )


@patch('roundup.backends.back_sqlite3.Database.getuid', Mock(return_value=1))
class AddNodeDatabaseTest(TestCase):
    def setUp(self):
        config = Mock()
        config.DATABASE = ''
        config.RDBMS_NAME = ''

        self.db = Database(config, journaltag=1)
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            tasks=hyperdb.Multilink('task'),
        )
        Class(self.db, 'task',
            name=hyperdb.String(),
        )
        self.db.post_init()

    def test_props_not_changed(self):
        props = {
            'name': 'Person One',
            'age': 22,
        }
        before_props = props.copy()

        self.db.addnode('person', None, props)

        self.assertEqual(before_props, props)

    def test_invalid_property(self):
        props = {
            'name': 'Person One',
            'invalid': 'invalid prop',
            'tasks': [3, 4]
        }

        self.assertRaisesRegexp(
            KeyError, "'person' has no 'invalid' property",
            self.db.addnode, 'person', None, props)

    def test_simple(self):
        props = {
            'name': 'Person One',
            'age': 22,
        }

        before = datetime.now()
        nodeid = self.db.addnode('person', None, props)
        after = datetime.now()

        self.assertEqual(nodeid, 1)

        query = select([self.db.schema.tables['_person']])
        row = self.db.engine.execute(query).fetchone()

        self.assertTrue(before <= row['_activity'] <= after)
        self.assertEqual(row['_actor'], 1)
        self.assertTrue(before <= row['_creation'] <= after)
        self.assertEqual(row['_creator'], 1)
        self.assertEqual(row['_age'], 22)
        self.assertEqual(row['_name'], 'Person One')
        self.assertEqual(row['id'], 1)
        self.assertEqual(row['__retired__'], False)

        query = select([self.db.schema.tables['_person']])
        row = self.db.engine.execute(query).fetchone()

    def test_protected_properties(self):
        now = datetime.now()
        props = {
            'name': 'Person One',
            'activity': now,
        }

        nodeid = self.db.addnode('person', None, props)

        self.assertEqual(nodeid, 1)

        query = select([self.db.schema.tables['_person']])
        row = self.db.engine.execute(query).fetchone()

        self.assertEqual(row['_activity'], now)
        self.assertEqual(row['_age'], None)
        self.assertEqual(row['_name'], 'Person One')
        self.assertEqual(row['id'], 1)
        self.assertEqual(row['__retired__'], False)

        query = select([self.db.schema.tables['_person']])
        row = self.db.engine.execute(query).fetchone()

    def test_multilink(self):
        props = {
            'name': 'Person One',
            'tasks': [3, 4],
        }

        before = datetime.now()
        nodeid = self.db.addnode('person', None, props)
        after = datetime.now()

        self.assertEqual(nodeid, 1)

        query = select([self.db.schema.tables['_person']])
        row = self.db.engine.execute(query).fetchone()

        self.assertEqual(row['_name'], 'Person One')
        self.assertEqual(row['id'], 1)

        query = select([self.db.schema.tables['person_tasks']])
        rows = self.db.engine.execute(query).fetchall()

        self.assertEqual(len(rows), 2)

        for i, linkid in enumerate([3, 4]):
            self.assertEqual(rows[i]['nodeid'], 1)
            self.assertEqual(rows[i]['linkid'], linkid)

    def test_multilink_is_list(self):
        props = {
            'name': 'Person One',
            'tasks': '3',
        }

        self.assertRaisesRegexp(
            ValueError, "multilink property 'tasks' must be a list",
            self.db.addnode, 'person', None, props)


class HasNodeDatabaseTest(TestCase):
    def setUp(self):
        config = Mock()
        config.DATABASE = ''
        config.RDBMS_NAME = ''

        self.db = Database(config, journaltag=1)
        Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
        )
        self.db.post_init()

        for i in range(1, 3):
            person = self.db.schema.tables['_person']
            query = person.insert().values(**{
                '_name': 'Person {0}'.format(i),
                '_age': 20 + i,
            })
            self.db.engine.execute(query)

    def test_invalid_class(self):
        self.assertRaises(KeyError, self.db.hasnode, 'unknown', 1)

    def test_hasnode_exists(self):
        self.assertTrue(self.db.hasnode('person', 2))

    def test_hasnode_not_exist(self):
        self.assertFalse(self.db.hasnode('person', 5))


class CreateClassTest(TestCase):
    def setUp(self):
        config = Mock()
        config.DATABASE = ''
        config.RDBMS_NAME = ''

        self.db = Database(config, journaltag=1)
        self.stuff = Class(self.db, 'stuff',
            boolean=hyperdb.Boolean(),
            number=hyperdb.Number(),
            string=hyperdb.String(),
            password=hyperdb.Password(),
            date=hyperdb.Date(),
            interval=hyperdb.Interval(),
            link=hyperdb.Link('other'),
            multilink=hyperdb.Multilink('other'),
        )
        other = Class(self.db, 'other',
            name=hyperdb.String(),
        )
        other.setkey('name')

        self.db.post_init()

        for i in range(0, 3):
            table = self.db.schema.tables['_other']
            query = table.insert().values(**{
                '_name': 'Item {0}'.format(i),
            })
            self.db.engine.execute(query)

    def test_db_readonly(self):
        self.db.journaltag = None
        props = {
            'string': 'Some String',
            'number': 33,
        }

        self.assertRaises(
            hyperdb.DatabaseError, self.db.stuff.create, **props)

    def test_invalid_prop_id(self):
        props = {
            'id': 22,
            'string': 'Some String',
            'number': 33,
        }

        self.assertRaisesRegexp(
            KeyError, "'id' is a reserved class property",
            self.db.stuff.create, **props)

    def test_invalid_prop_reserved(self):
        msg = ("'activity', 'actor', 'creation', and 'creator' are reserved " +
               "class properties")
        props = {
            'string': 'Some String',
            'number': 33,
        }

        for prop in ('activity', 'actor', 'creation', 'creator'):
            this_props = props.copy()
            this_props[prop] = 'mock value'
            try:
                self.assertRaisesRegexp(
                    KeyError, msg, self.db.stuff.create, **this_props)
            except AssertionError as e:
                raise AssertionError(
                    "{0} for property '{1}'".format(str(e), prop))

    def test_invalid_prop_nonexistant(self):
        props = {
            'string': 'Some String',
            'number': 33,
            'unknown': 'Token Person',
        }

        self.assertRaisesRegexp(
            KeyError, "'stuff' class has no 'unknown' property",
            self.db.stuff.create, **props)

    def test_invalid_prop_boolean(self):
        props = {
            'string': 'Some String',
            'number': 33,
            'boolean': 'Token Person',
        }

        self.assertRaisesRegexp(
            TypeError, "value for new property 'boolean' is not a boolean",
            self.db.stuff.create, **props)

    def test_invalid_prop_number(self):
        props = {
            'string': 'Some String',
            'number': 'not a number',
        }

        self.assertRaisesRegexp(
            TypeError, "value for new property 'number' is not numeric",
            self.db.stuff.create, **props)

    def test_invalid_prop_string(self):
        props = {
            'string': 11,
            'number': 22,
        }

        self.assertRaisesRegexp(
            TypeError, "value for new property 'string' is not a string",
            self.db.stuff.create, **props)

    def test_invalid_prop_password(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'password': 'not a password',
        }

        self.assertRaisesRegexp(
            TypeError,
            "value for new property 'password' is not a roundup password",
            self.db.stuff.create, **props)

    def test_invalid_prop_date(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'date': 'not a date',
        }

        self.assertRaisesRegexp(
            TypeError, "value for new property 'date' is not a roundup date",
            self.db.stuff.create, **props)

    def test_invalid_prop_interval(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'interval': 'not an interval',
        }

        self.assertRaisesRegexp(
            TypeError,
            "value for new property 'interval' is not a roundup interval",
            self.db.stuff.create, **props)

    def test_invalid_prop_link_id(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'link': 5,
        }
        self.assertRaisesRegexp(
            IndexError, "class 'other' has no node with id '5'",
            self.db.stuff.create, **props)

    def test_invalid_prop_link_lookup(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'link': 'unknown',
        }
        self.assertRaisesRegexp(
            IndexError, "class 'other' has no node with key value 'unknown'",
            self.db.stuff.create, **props)

    def test_invalid_prop_multilink_not_iterable(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'multilink': 11,
        }
        self.assertRaisesRegexp(
            TypeError,
            "value for new property 'multilink' is not an iterable of node ids",
            self.db.stuff.create, **props)

    def test_invalid_prop_multilink_string(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'multilink': 'not node ids',
        }
        self.assertRaisesRegexp(
            TypeError,
            "value for new property 'multilink' is not an iterable of node ids",
            self.db.stuff.create, **props)

    def test_invalid_prop_multilink_id(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'multilink': [5],
        }
        self.assertRaisesRegexp(
            IndexError, "class 'other' has no node with id '5'",
            self.db.stuff.create, **props)

    def test_invalid_prop_multilink_lookup(self):
        props = {
            'string': 'Some string',
            'number': 22,
            'multilink': ['unknown'],
        }
        self.assertRaisesRegexp(
            IndexError, "class 'other' has no node with key value 'unknown'",
            self.db.stuff.create, **props)

    def test_key_value_missing(self):
        self.stuff.setkey('string')
        props = {
            'boolean': True,
            'number': 22,
        }
        self.assertRaisesRegexp(
            ValueError, "class 'stuff' requires a value for key property 'string'",
            self.db.stuff.create, **props)

    def test_key_value_exists(self):
        props = {
            'name': 'Item 1',
        }
        self.assertRaisesRegexp(
            ValueError, "node for class 'other' already exists with key \(name\) value 'Item 1'",
            self.db.other.create, **props)

    @patch('roundup.backends.back_sqlite3.Database.getuid',
           Mock(return_value=1))
    def test_create_simple(self):
        password = Password('some password')
        # date picked includes potential rounding error on microseconds
        date = datetime(2015, 2, 6, 17, 43, 47, 393420)
        rdate = Date(date)
        interval = Interval('-1d 12:14')
        props = {
            'boolean': False,
            'number': 11,
            'string': 'some string',
            'password': password,
            'date': rdate,
            'interval': interval,
        }

        nodeid = self.db.stuff.create(**props)

        db = MetaData(bind=self.db.engine)
        db.reflect()
        table = db.tables['_stuff']
        query = table.select().where(table.columns['id'] == nodeid)
        rows = self.db.engine.execute(query).fetchone()

        self.assertEqual(rows['_boolean'], False)
        self.assertEqual(rows['_number'], 11)
        self.assertEqual(rows['_string'], 'some string')
        self.assertEqual(rows['_password'], str(password))
        self.assertEqual(rows['_date'], date)
        # sqlalchemy stores timedeltas as epoch + timedelta()
        self.assertEqual(
            rows['_interval'],
            datetime.utcfromtimestamp(-86400 - (12 * 3600) - (14 * 60)))

    # TODO: ints not supported with legacy backends
    @patch('roundup.backends.back_sqlite3.Database.getuid',
           Mock(return_value=1))
    def test_create_link_int(self):
        props = {
            'link': 1,
        }
        nodeid = self.db.stuff.create(**props)
        db = MetaData(bind=self.db.engine)
        db.reflect()
        table = db.tables['_stuff']
        query = table.select().where(table.columns['id'] == nodeid)
        rows = self.db.engine.execute(query).fetchone()

        self.assertEqual(rows['_link'], 1)

    @patch('roundup.backends.back_sqlite3.Database.getuid',
           Mock(return_value=1))
    def test_create_link_string_int(self):
        props = {
            'link': '1',
        }
        nodeid = self.db.stuff.create(**props)
        db = MetaData(bind=self.db.engine)
        db.reflect()
        table = db.tables['_stuff']
        query = table.select().where(table.columns['id'] == nodeid)
        rows = self.db.engine.execute(query).fetchone()

        self.assertEqual(rows['_link'], 1)

    @patch('roundup.backends.back_sqlite3.Database.getuid',
           Mock(return_value=1))
    def test_create_link_string_key(self):
        props = {
            'link': 'Item 1',
        }
        nodeid = self.db.stuff.create(**props)
        db = MetaData(bind=self.db.engine)
        db.reflect()
        table = db.tables['_stuff']
        query = table.select().where(table.columns['id'] == nodeid)
        rows = self.db.engine.execute(query).fetchone()

        self.assertEqual(rows['_link'], 2)

    # TODO: ints not supported with legacy backends
    @patch('roundup.backends.back_sqlite3.Database.getuid',
           Mock(return_value=1))
    def test_create_multilink_int(self):
        props = {
            'multilink': [1, 2],
        }
        nodeid = self.db.stuff.create(**props)
        db = MetaData(bind=self.db.engine)
        db.reflect()
        table = db.tables['stuff_multilink']
        query = table.select().where(table.columns['nodeid'] == nodeid)\
            .order_by(table.columns['linkid'])
        rows = self.db.engine.execute(query).fetchall()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['linkid'], 1)
        self.assertEqual(rows[1]['linkid'], 2)

    # TODO: test multilink as int string
    @patch('roundup.backends.back_sqlite3.Database.getuid',
           Mock(return_value=1))
    def test_create_multilink_string_int(self):
        props = {
            'multilink': [1, 2],
        }
        nodeid = self.db.stuff.create(**props)
        db = MetaData(bind=self.db.engine)
        db.reflect()
        table = db.tables['stuff_multilink']
        query = table.select().where(table.columns['nodeid'] == nodeid)\
            .order_by(table.columns['linkid'])
        rows = self.db.engine.execute(query).fetchall()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['linkid'], 1)
        self.assertEqual(rows[1]['linkid'], 2)

    @patch('roundup.backends.back_sqlite3.Database.getuid',
           Mock(return_value=1))
    def test_create_multilink_string_key(self):
        props = {
            'multilink': ['Item 1', 'Item 2'],
        }
        nodeid = self.db.stuff.create(**props)
        db = MetaData(bind=self.db.engine)
        db.reflect()
        table = db.tables['stuff_multilink']
        query = table.select().where(table.columns['nodeid'] == nodeid)\
            .order_by(table.columns['linkid'])
        rows = self.db.engine.execute(query).fetchall()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['linkid'], 2)
        self.assertEqual(rows[1]['linkid'], 3)

    # TODO: test multilink specified multiple times
    #   what is the correct behaviour?

    # TODO: test key value does not already exist
    # TODO: test firing of auditors


class AddClassDatabaseTest(TestCase):
    def setUp(self):
        config = Mock()
        config.DATABASE = ''
        config.RDBMS_NAME = ''
        self.db = Database(config)

    def test_add_class(self):
        c = Class(self.db, 'test')
        self.assertEqual(self.db.classes, {'test': c})
        # TODO check permissions once getclass is implemented

    def test_redefined_class(self):
        Class(self.db, 'test')
        self.assertRaises(ValueError, Class, self.db, 'test')


class LookupClassTest(TestCase):
    def setUp(self):
        config = Mock()
        config.DATABASE = ''
        config.RDBMS_NAME = ''

        self.db = Database(config, journaltag=1)
        self.person = Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
        )
        self.db.post_init()

        for i in range(1, 3):
            person = self.db.schema.tables['_person']
            query = person.insert().values(**{
                '_name': 'Person {0}'.format(i),
                '_age': 20 + i,
            })
            self.db.engine.execute(query)

    def test_class_has_key(self):
        self.assertRaises(TypeError, self.person.lookup, 'nokeyset')

    def test_class_lookup_exists(self):
        self.person.setkey('name')
        self.assertEqual(2, self.person.lookup('Person 2'))

    def test_class_lookup_not_exist(self):
        self.person.setkey('name')
        self.assertRaises(KeyError, self.person.lookup, 'unknown')
