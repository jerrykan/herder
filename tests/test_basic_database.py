import json
from unittest import TestCase

from mock import Mock, patch
from sqlalchemy import MetaData, Table, Column, create_engine, select, types

from roundup.backends.back_sqlite3 import VolatileData


@patch('roundup.backends.back_sqlite3.time.time', Mock(return_value=12345678))
class VolatileDataTest(TestCase):
    def setUp(self):
        engine = create_engine('sqlite:///:memory:')
        schema = MetaData(bind=engine)
        self.table = Table('miscs', schema,
            Column('misc_key', types.String, index=True),
            Column('misc_value', types.String),
            Column('misc_time', types.Integer),
        )

        schema.create_all(engine)
        self.table.insert().values(**{
            'misc_key': 'key0',
            'misc_value': 'value0',
            'misc_time': 23456789,
        }).execute()
        self.table.insert().values(**{
            'misc_key': 'key2',
            'misc_value': 'value2',
            'misc_time': 34567890,
        }).execute()

    def test_set_new_data(self):
        misc = VolatileData(self.table)
        misc.set('key1', first='one', second='two')

        rows = self.table.select().order_by('misc_key').execute().fetchall()
        row = rows.pop(1)

        self.assertEqual(row.misc_key, 'key1')
        self.assertEqual(json.loads(row.misc_value), {
            'first': 'one',
            'second': 'two',
        })
        self.assertEqual(row.misc_time, 12345678)

        self.assertEqual(rows, [
            (u'key0', u'value0', 23456789),
            (u'key2', u'value2', 34567890),
        ])

    def test_set_update_existing_data(self):
        self.table.insert().values(**{
            'misc_key': 'key1',
            'misc_value': json.dumps({
                'first': 'one',
                'second': 'too',
            }),
            'misc_time': 12345670,
        }).execute()
        misc = VolatileData(self.table)
        misc.set('key1', second='two', third='three')

        rows = self.table.select().order_by('misc_key').execute().fetchall()
        row = rows.pop(1)

        self.assertEqual(row.misc_key, 'key1')
        self.assertEqual(json.loads(row.misc_value), {
            'first': 'one',
            'second': 'two',
            'third': 'three',
        })
        self.assertEqual(row.misc_time, 12345670)

        self.assertEqual(rows, [
            (u'key0', u'value0', 23456789),
            (u'key2', u'value2', 34567890),
        ])

# FIX: otks table has columns otk_
# FIX: sessions table has columns session_
