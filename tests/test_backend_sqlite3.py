from datetime import datetime
from unittest import TestCase
from os import path

from mock import Mock, patch
from sqlalchemy import MetaData
from sqlalchemy.sql import select

from roundup import hyperdb
from roundup.backends.back_sqlite3 import Database, _temporary_db, types
from roundup.backends.back_sqlite3 import Class


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

        with p_isdir, p_create_engine as m_create_engine:
            db = Database(self.config)

            self.assertEqual(
                m_create_engine.call_args[0],
                ('sqlite:///{0}'.format(path.join('db', 'roundup.db')),)
            )
            self.assertEqual(m_create_engine.call_args[1], {})

        self.assertEqual(m_makedirs.call_args, (('db',), {}))


class PostInitDatabase(TestCase):
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

    def test_schema_create_class(self):
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
        # so we can check that it get migrated properly
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

    def test_schema_create_multilink(self):
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

    def test_schema_create_key_index(self):
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
