from unittest import TestCase
from os import path

from mock import Mock, patch

from roundup import hyperdb
from roundup.backends.back_sqlite3 import Database, _temporary_db
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
        self.db = Database(config)

    def test_empty_schema(self):
        pass

    def test_simple_table(self):
        person = Class(self.db, 'person',
            name=hyperdb.String(),
            age=hyperdb.Number(),
            birthday=hyperdb.Date()
        )
        self.db.post_init()

        self.assertIn('_person', self.db.schema.tables)
        import pdb; pdb.set_trace()
        
#    def test_it(self):
#        person = Class(self.db, 'person',
#            name=hyperdb.String(),
#            age=hyperdb.Number(),
#            birthday=hyperdb.Date(),
#            gender=hyperdb.Link('gender'),
##            jobs=hyperdb.Multilink('job')
#        )
#
#        
#
#        gender = Class(self.db, 'gender',
#            name=hyperdb.String()
#        )
#        job = Class(self.db, 'job',
#            name=hyperdb.String(),
#        )
#
#        self.db.post_init()
#        import pdb; pdb.set_trace()



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
