#
# Copyright (c) 2003 Richard Jones, rjones@ekit-inc.com
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

import unittest, os, shutil, errno, sys, difflib, cgi, re, StringIO

from roundup.cgi import client, actions, exceptions
from roundup.cgi.exceptions import FormError
from roundup.cgi.templating import HTMLItem, HTMLRequest, NoTemplate
from roundup.cgi.templating import HTMLProperty, _HTMLItem
from roundup.cgi.form_parser import FormParser
from roundup import init, instance, password, hyperdb, date

# For testing very simple rendering
from roundup.cgi.engine_zopetal import RoundupPageTemplate

from .mocknull import MockNull

from . import db_test_base

class FileUpload:
    def __init__(self, content, filename):
        self.content = content
        self.filename = filename

class FileList:
    def __init__(self, name, *files):
        self.name  = name
        self.files = files
    def items (self):
        for f in self.files:
            yield (self.name, f)

def makeForm(args):
    form = cgi.FieldStorage()
    for k,v in args.items():
        if isinstance(v, list):
            [form.list.append(cgi.MiniFieldStorage(k, x)) for x in v]
        elif isinstance(v, FileUpload):
            x = cgi.MiniFieldStorage(k, v.content)
            x.filename = v.filename
            form.list.append(x)
        else:
            form.list.append(cgi.MiniFieldStorage(k, v))
    return form

cm = client.add_message
class MessageTestCase(unittest.TestCase):
    # Note: Escaping is now handled on a message-by-message basis at a
    # point where we still know what generates a message. In this way we
    # can decide when to escape and when not. We test the add_message
    # routine here.
    # Of course we won't catch errors in judgement when to escape here
    # -- but at the time of this change only one message is not escaped.
    def testAddMessageOK(self):
        self.assertEqual(cm([],'a\nb'), ['a<br />\nb'])
        self.assertEqual(cm([],'a\nb\nc\n'), ['a<br />\nb<br />\nc<br />\n'])

    def testAddMessageBAD(self):
        self.assertEqual(cm([],'<script>x</script>'),
            ['&lt;script&gt;x&lt;/script&gt;'])
        self.assertEqual(cm([],'<iframe>x</iframe>'),
            ['&lt;iframe&gt;x&lt;/iframe&gt;'])
        self.assertEqual(cm([],'<<script >>alert(42);5<</script >>'),
            ['&lt;&lt;script &gt;&gt;alert(42);5&lt;&lt;/script &gt;&gt;'])
        self.assertEqual(cm([],'<a href="y">x</a>'),
            ['&lt;a href="y"&gt;x&lt;/a&gt;'])
        self.assertEqual(cm([],'<A HREF="y">x</A>'),
            ['&lt;A HREF="y"&gt;x&lt;/A&gt;'])
        self.assertEqual(cm([],'<br>x<br />'), ['&lt;br&gt;x&lt;br /&gt;'])
        self.assertEqual(cm([],'<i>x</i>'), ['&lt;i&gt;x&lt;/i&gt;'])
        self.assertEqual(cm([],'<b>x</b>'), ['&lt;b&gt;x&lt;/b&gt;'])
        self.assertEqual(cm([],'<BR>x<BR />'), ['&lt;BR&gt;x&lt;BR /&gt;'])
        self.assertEqual(cm([],'<I>x</I>'), ['&lt;I&gt;x&lt;/I&gt;'])
        self.assertEqual(cm([],'<B>x</B>'), ['&lt;B&gt;x&lt;/B&gt;'])

    def testAddMessageNoEscape(self):
        self.assertEqual(cm([],'<i>x</i>',False), ['<i>x</i>'])
        self.assertEqual(cm([],'<i>x</i>\n<b>x</b>',False),
            ['<i>x</i><br />\n<b>x</b>'])

class FormTestCase(unittest.TestCase):
    def setUp(self):
        self.dirname = '_test_cgi_form'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname)

        # open the database
        self.db = self.instance.open('admin')
        self.db.tx_Source = "web"
        self.db.user.create(username='Chef', address='chef@bork.bork.bork',
            realname='Bork, Chef', roles='User')
        self.db.user.create(username='mary', address='mary@test.test',
            roles='User', realname='Contrary, Mary')

        self.db.issue.addprop(tx_Source=hyperdb.String())
        self.db.msg.addprop(tx_Source=hyperdb.String())

        self.db.post_init()

        vars = {}
        thisdir = os.path.dirname(__file__)
        exec(compile(
                open(os.path.join(thisdir, "tx_Source_detector.py")).read(),
                os.path.join(thisdir, "tx_Source_detector.py"),
                'exec'),
             vars)
        vars['init'](self.db)

        test = self.instance.backend.Class(self.db, "test",
            string=hyperdb.String(), number=hyperdb.Number(),
            intval=hyperdb.Integer(), boolean=hyperdb.Boolean(),
            link=hyperdb.Link('test'), multilink=hyperdb.Multilink('test'),
            date=hyperdb.Date(), messages=hyperdb.Multilink('msg'),
            interval=hyperdb.Interval())

        # compile the labels re
        classes = '|'.join(self.db.classes.keys())
        self.FV_SPECIAL = re.compile(FormParser.FV_LABELS%classes,
            re.VERBOSE)

    def setupClient(self, form, classname, nodeid=None, template='item'):
        cl = client.Client(self.instance, None, {'PATH_INFO':'/',
            'REQUEST_METHOD':'POST'}, makeForm(form))
        cl.classname = classname
        cl.nodeid = nodeid
        cl.language = ('en',)
        cl.userid = '1'
        cl.db = self.db
        cl.user = 'admin'
        cl.template = template
        return cl

    def parseForm(self, form, classname='test', nodeid=None):
        cl = self.setupClient(form, classname, nodeid)
        return cl.parsePropsFromForm(create=1)

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    #
    # form label extraction
    #
    def tl(self, s, c, i, a, p):
        m = self.FV_SPECIAL.match(s)
        self.assertNotEqual(m, None)
        d = m.groupdict()
        self.assertEqual(d['classname'], c)
        self.assertEqual(d['id'], i)
        for action in 'required add remove link note file'.split():
            if a == action:
                self.assertNotEqual(d[action], None)
            else:
                self.assertEqual(d[action], None)
        self.assertEqual(d['propname'], p)

    def testLabelMatching(self):
        self.tl('<propname>', None, None, None, '<propname>')
        self.tl(':required', None, None, 'required', None)
        self.tl(':confirm:<propname>', None, None, 'confirm', '<propname>')
        self.tl(':add:<propname>', None, None, 'add', '<propname>')
        self.tl(':remove:<propname>', None, None, 'remove', '<propname>')
        self.tl(':link:<propname>', None, None, 'link', '<propname>')
        self.tl('test1:<prop>', 'test', '1', None, '<prop>')
        self.tl('test1:required', 'test', '1', 'required', None)
        self.tl('test1:add:<prop>', 'test', '1', 'add', '<prop>')
        self.tl('test1:remove:<prop>', 'test', '1', 'remove', '<prop>')
        self.tl('test1:link:<prop>', 'test', '1', 'link', '<prop>')
        self.tl('test1:confirm:<prop>', 'test', '1', 'confirm', '<prop>')
        self.tl('test-1:<prop>', 'test', '-1', None, '<prop>')
        self.tl('test-1:required', 'test', '-1', 'required', None)
        self.tl('test-1:add:<prop>', 'test', '-1', 'add', '<prop>')
        self.tl('test-1:remove:<prop>', 'test', '-1', 'remove', '<prop>')
        self.tl('test-1:link:<prop>', 'test', '-1', 'link', '<prop>')
        self.tl('test-1:confirm:<prop>', 'test', '-1', 'confirm', '<prop>')
        self.tl(':note', None, None, 'note', None)
        self.tl(':file', None, None, 'file', None)

    #
    # Empty form
    #
    def testNothing(self):
        self.assertEqual(self.parseForm({}), ({('test', None): {}}, []))

    def testNothingWithRequired(self):
        self.assertRaises(FormError, self.parseForm, {':required': 'string'})
        self.assertRaises(FormError, self.parseForm,
            {':required': 'title,status', 'status':'1'}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': ['title','status'], 'status':'1'}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': 'status', 'status':''}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': 'nosy', 'nosy':''}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': 'msg-1@content', 'msg-1@content':''}, 'issue')
        self.assertRaises(FormError, self.parseForm,
            {':required': 'msg-1@content'}, 'issue')

    #
    # Nonexistant edit
    #
    def testEditNonexistant(self):
        self.assertRaises(FormError, self.parseForm, {'boolean': ''},
            'test', '1')

    #
    # String
    #
    def testEmptyString(self):
        self.assertEqual(self.parseForm({'string': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'string': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'string': ['', '']})

    def testSetString(self):
        self.assertEqual(self.parseForm({'string': 'foo'}),
            ({('test', None): {'string': 'foo'}}, []))
        self.assertEqual(self.parseForm({'string': 'a\r\nb\r\n'}),
            ({('test', None): {'string': 'a\nb'}}, []))
        nodeid = self.db.issue.create(title='foo')
        self.assertEqual(self.parseForm({'title': 'foo'}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

    def testEmptyStringSet(self):
        nodeid = self.db.issue.create(title='foo')
        self.assertEqual(self.parseForm({'title': ''}, 'issue', nodeid),
            ({('issue', nodeid): {'title': None}}, []))
        nodeid = self.db.issue.create(title='foo')
        self.assertEqual(self.parseForm({'title': ' '}, 'issue', nodeid),
            ({('issue', nodeid): {'title': None}}, []))

    def testStringLinkId(self):
        self.db.status.set('1', name='2')
        self.db.status.set('2', name='1')
        issue = self.db.issue.create(title='i1-status1', status='1')
        self.assertEqual(self.db.issue.get(issue,'status'),'1')
        self.assertEqual(self.db.status.lookup('1'),'2')
        self.assertEqual(self.db.status.lookup('2'),'1')
        self.assertEqual(self.db.issue.get('1','tx_Source'),'web')
        form = cgi.FieldStorage()
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'}, form)
        cl.classname = 'issue'
        cl.nodeid = issue
        cl.db = self.db
        cl.language = ('en',)
        item = HTMLItem(cl, 'issue', issue)
        self.assertEqual(item.status.id, '1')
        self.assertEqual(item.status.name, '2')

    def testStringMultilinkId(self):
        id = self.db.keyword.create(name='2')
        self.assertEqual(id,'1')
        id = self.db.keyword.create(name='1')
        self.assertEqual(id,'2')
        issue = self.db.issue.create(title='i1-status1', keyword=['1'])
        self.assertEqual(self.db.issue.get(issue,'keyword'),['1'])
        self.assertEqual(self.db.keyword.lookup('1'),'2')
        self.assertEqual(self.db.keyword.lookup('2'),'1')
        self.assertEqual(self.db.issue.get(issue,'tx_Source'),'web')
        form = cgi.FieldStorage()
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'}, form)
        cl.classname = 'issue'
        cl.nodeid = issue
        cl.db = self.db
        cl.language = ('en',)
        cl.userid = '1'
        item = HTMLItem(cl, 'issue', issue)
        for keyword in item.keyword:
            self.assertEqual(keyword.id, '1')
            self.assertEqual(keyword.name, '2')

    def testFileUpload(self):
        file = FileUpload('foo', 'foo.txt')
        self.assertEqual(self.parseForm({'content': file}, 'file'),
            ({('file', None): {'content': 'foo', 'name': 'foo.txt',
            'type': 'text/plain'}}, []))

    def testSingleFileUpload(self):
        file = FileUpload('foo', 'foo.txt')
        self.assertEqual(self.parseForm({'@file': file}, 'issue'),
            ({('file', '-1'): {'content': 'foo', 'name': 'foo.txt',
            'type': 'text/plain'},
              ('issue', None): {}},
             [('issue', None, 'files', [('file', '-1')])]))

    def testMultipleFileUpload(self):
        f1 = FileUpload('foo', 'foo.txt')
        f2 = FileUpload('bar', 'bar.txt')
        f3 = FileUpload('baz', 'baz.txt')
        files = FileList('@file', f1, f2, f3)

        self.assertEqual(self.parseForm(files, 'issue'),
            ({('file', '-1'): {'content': 'foo', 'name': 'foo.txt',
               'type': 'text/plain'},
              ('file', '-2'): {'content': 'bar', 'name': 'bar.txt',
               'type': 'text/plain'},
              ('file', '-3'): {'content': 'baz', 'name': 'baz.txt',
               'type': 'text/plain'},
              ('issue', None): {}},
             [ ('issue', None, 'files', [('file', '-1')])
             , ('issue', None, 'files', [('file', '-2')])
             , ('issue', None, 'files', [('file', '-3')])
             ]))

    def testEditFileClassAttributes(self):
        self.assertEqual(self.parseForm({'name': 'foo.txt',
                                         'type': 'application/octet-stream'},
                                        'file'),
                         ({('file', None): {'name': 'foo.txt',
                                            'type': 'application/octet-stream'}},[]))

    #
    # Link
    #
    def testEmptyLink(self):
        self.assertEqual(self.parseForm({'link': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'link': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'link': ['', '']})
        self.assertEqual(self.parseForm({'link': '-1'}),
            ({('test', None): {}}, []))

    def testSetLink(self):
        self.assertEqual(self.parseForm({'status': 'unread'}, 'issue'),
            ({('issue', None): {'status': '1'}}, []))
        self.assertEqual(self.parseForm({'status': '1'}, 'issue'),
            ({('issue', None): {'status': '1'}}, []))
        nodeid = self.db.issue.create(status='unread')
        self.assertEqual(self.parseForm({'status': 'unread'}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))
        self.assertEqual(self.db.issue.get(nodeid,'tx_Source'),'web')

    def testUnsetLink(self):
        nodeid = self.db.issue.create(status='unread')
        self.assertEqual(self.parseForm({'status': '-1'}, 'issue', nodeid),
            ({('issue', nodeid): {'status': None}}, []))
        self.assertEqual(self.db.issue.get(nodeid,'tx_Source'),'web')

    def testInvalidLinkValue(self):
# XXX This is not the current behaviour - should we enforce this?
#        self.assertRaises(IndexError, self.parseForm,
#            {'status': '4'}))
        self.assertRaises(FormError, self.parseForm, {'link': 'frozzle'})
        self.assertRaises(FormError, self.parseForm, {'status': 'frozzle'},
            'issue')

    #
    # Multilink
    #
    def testEmptyMultilink(self):
        self.assertEqual(self.parseForm({'nosy': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'nosy': ' '}),
            ({('test', None): {}}, []))

    def testSetMultilink(self):
        self.assertEqual(self.parseForm({'nosy': '1'}, 'issue'),
            ({('issue', None): {'nosy': ['1']}}, []))
        self.assertEqual(self.parseForm({'nosy': 'admin'}, 'issue'),
            ({('issue', None): {'nosy': ['1']}}, []))
        self.assertEqual(self.parseForm({'nosy': ['1','2']}, 'issue'),
            ({('issue', None): {'nosy': ['1','2']}}, []))
        self.assertEqual(self.parseForm({'nosy': '1,2'}, 'issue'),
            ({('issue', None): {'nosy': ['1','2']}}, []))
        self.assertEqual(self.parseForm({'nosy': 'admin,2'}, 'issue'),
            ({('issue', None): {'nosy': ['1','2']}}, []))

    def testMixedMultilink(self):
        form = cgi.FieldStorage()
        form.list.append(cgi.MiniFieldStorage('nosy', '1,2'))
        form.list.append(cgi.MiniFieldStorage('nosy', '3'))
        cl = client.Client(self.instance, None, {'PATH_INFO':'/'}, form)
        cl.classname = 'issue'
        cl.nodeid = None
        cl.db = self.db
        cl.language = ('en',)
        self.assertEqual(cl.parsePropsFromForm(create=1),
            ({('issue', None): {'nosy': ['1','2', '3']}}, []))

    def testEmptyMultilinkSet(self):
        nodeid = self.db.issue.create(nosy=['1','2'])
        self.assertEqual(self.parseForm({'nosy': ''}, 'issue', nodeid),
            ({('issue', nodeid): {'nosy': []}}, []))
        nodeid = self.db.issue.create(nosy=['1','2'])
        self.assertEqual(self.parseForm({'nosy': ' '}, 'issue', nodeid),
            ({('issue', nodeid): {'nosy': []}}, []))
        self.assertEqual(self.parseForm({'nosy': '1,2'}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

    def testInvalidMultilinkValue(self):
# XXX This is not the current behaviour - should we enforce this?
#        self.assertRaises(IndexError, self.parseForm,
#            {'nosy': '4'}))
        self.assertRaises(FormError, self.parseForm, {'nosy': 'frozzle'},
            'issue')
        self.assertRaises(FormError, self.parseForm, {'nosy': '1,frozzle'},
            'issue')
        self.assertRaises(FormError, self.parseForm, {'multilink': 'frozzle'})

    def testMultilinkAdd(self):
        nodeid = self.db.issue.create(nosy=['1'])
        # do nothing
        self.assertEqual(self.parseForm({':add:nosy': ''}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

        # do something ;)
        self.assertEqual(self.parseForm({':add:nosy': '2'}, 'issue', nodeid),
            ({('issue', nodeid): {'nosy': ['1','2']}}, []))
        self.assertEqual(self.parseForm({':add:nosy': '2,mary'}, 'issue',
            nodeid), ({('issue', nodeid): {'nosy': ['1','2','4']}}, []))
        self.assertEqual(self.parseForm({':add:nosy': ['2','3']}, 'issue',
            nodeid), ({('issue', nodeid): {'nosy': ['1','2','3']}}, []))

    def testMultilinkAddNew(self):
        self.assertEqual(self.parseForm({':add:nosy': ['2','3']}, 'issue'),
            ({('issue', None): {'nosy': ['2','3']}}, []))

    def testMultilinkRemove(self):
        nodeid = self.db.issue.create(nosy=['1','2'])
        # do nothing
        self.assertEqual(self.parseForm({':remove:nosy': ''}, 'issue', nodeid),
            ({('issue', nodeid): {}}, []))

        # do something ;)
        self.assertEqual(self.parseForm({':remove:nosy': '1'}, 'issue',
            nodeid), ({('issue', nodeid): {'nosy': ['2']}}, []))
        self.assertEqual(self.parseForm({':remove:nosy': 'admin,2'},
            'issue', nodeid), ({('issue', nodeid): {'nosy': []}}, []))
        self.assertEqual(self.parseForm({':remove:nosy': ['1','2']},
            'issue', nodeid), ({('issue', nodeid): {'nosy': []}}, []))

        # add and remove
        self.assertEqual(self.parseForm({':add:nosy': ['3'],
            ':remove:nosy': ['1','2']},
            'issue', nodeid), ({('issue', nodeid): {'nosy': ['3']}}, []))

        # remove one that doesn't exist?
        self.assertRaises(FormError, self.parseForm, {':remove:nosy': '4'},
            'issue', nodeid)

    def testMultilinkRetired(self):
        self.db.user.retire('2')
        self.assertEqual(self.parseForm({'nosy': ['2','3']}, 'issue'),
            ({('issue', None): {'nosy': ['2','3']}}, []))
        nodeid = self.db.issue.create(nosy=['1','2'])
        self.assertEqual(self.parseForm({':remove:nosy': '2'}, 'issue',
            nodeid), ({('issue', nodeid): {'nosy': ['1']}}, []))
        self.assertEqual(self.parseForm({':add:nosy': '3'}, 'issue', nodeid),
            ({('issue', nodeid): {'nosy': ['1','2','3']}}, []))

    def testAddRemoveNonexistant(self):
        self.assertRaises(FormError, self.parseForm, {':remove:foo': '2'},
            'issue')
        self.assertRaises(FormError, self.parseForm, {':add:foo': '2'},
            'issue')

    #
    # Password
    #
    def testEmptyPassword(self):
        self.assertEqual(self.parseForm({'password': ''}, 'user'),
            ({('user', None): {}}, []))
        self.assertEqual(self.parseForm({'password': ''}, 'user'),
            ({('user', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'password': ['', '']},
            'user')
        self.assertRaises(FormError, self.parseForm, {'password': 'foo',
            ':confirm:password': ['', '']}, 'user')

    def testSetPassword(self):
        self.assertEqual(self.parseForm({'password': 'foo',
            ':confirm:password': 'foo'}, 'user'),
            ({('user', None): {'password': 'foo'}}, []))

    def testSetPasswordConfirmBad(self):
        self.assertRaises(FormError, self.parseForm, {'password': 'foo'},
            'user')
        self.assertRaises(FormError, self.parseForm, {'password': 'foo',
            ':confirm:password': 'bar'}, 'user')

    def testEmptyPasswordNotSet(self):
        nodeid = self.db.user.create(username='1',
            password=password.Password('foo'))
        self.assertEqual(self.parseForm({'password': ''}, 'user', nodeid),
            ({('user', nodeid): {}}, []))
        nodeid = self.db.user.create(username='2',
            password=password.Password('foo'))
        self.assertEqual(self.parseForm({'password': '',
            ':confirm:password': ''}, 'user', nodeid),
            ({('user', nodeid): {}}, []))

    def testPasswordMigration(self):
        chef = self.db.user.lookup('Chef')
        form = dict(__login_name='Chef', __login_password='foo')
        cl = self._make_client(form)
        # assume that the "best" algorithm is the first one and doesn't
        # need migration, all others should be migrated.
        for scheme in password.Password.deprecated_schemes:
            if scheme == 'crypt' and os.name == 'nt':
                continue  # crypt is not available on Windows
            pw1 = password.Password('foo', scheme=scheme)
            self.assertEqual(pw1.needs_migration(), True)
            self.db.user.set(chef, password=pw1)
            self.db.commit()
            actions.LoginAction(cl).handle()
            pw = self.db.user.get(chef, 'password')
            self.assertEqual(pw, 'foo')
            self.assertEqual(pw.needs_migration(), False)
        pw1 = pw
        self.assertEqual(pw1.needs_migration(), False)
        scheme = password.Password.known_schemes[0]
        self.assertEqual(scheme, pw1.scheme)
        actions.LoginAction(cl).handle()
        pw = self.db.user.get(chef, 'password')
        self.assertEqual(pw, 'foo')
        self.assertEqual(pw, pw1)
        cl.db.close()

    def testPasswordConfigOption(self):
        chef = self.db.user.lookup('Chef')
        form = dict(__login_name='Chef', __login_password='foo')
        cl = self._make_client(form)
        self.db.config.PASSWORD_PBKDF2_DEFAULT_ROUNDS = 1000
        pw1 = password.Password('foo', scheme='MD5')
        self.assertEqual(pw1.needs_migration(), True)
        self.db.user.set(chef, password=pw1)
        self.db.commit()
        actions.LoginAction(cl).handle()
        pw = self.db.user.get(chef, 'password')
        self.assertEqual('PBKDF2', pw.scheme)
        self.assertEqual(1000, password.pbkdf2_unpack(pw.password)[0])
        cl.db.close()

    #
    # Boolean
    #
    def testEmptyBoolean(self):
        self.assertEqual(self.parseForm({'boolean': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'boolean': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'boolean': ['', '']})

    def testSetBoolean(self):
        self.assertEqual(self.parseForm({'boolean': 'yes'}),
            ({('test', None): {'boolean': 1}}, []))
        self.assertEqual(self.parseForm({'boolean': 'a\r\nb\r\n'}),
            ({('test', None): {'boolean': 0}}, []))
        nodeid = self.db.test.create(boolean=1)
        self.assertEqual(self.parseForm({'boolean': 'yes'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))
        nodeid = self.db.test.create(boolean=0)
        self.assertEqual(self.parseForm({'boolean': 'no'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))

    def testEmptyBooleanSet(self):
        nodeid = self.db.test.create(boolean=0)
        self.assertEqual(self.parseForm({'boolean': ''}, 'test', nodeid),
            ({('test', nodeid): {'boolean': None}}, []))
        nodeid = self.db.test.create(boolean=1)
        self.assertEqual(self.parseForm({'boolean': ' '}, 'test', nodeid),
            ({('test', nodeid): {'boolean': None}}, []))

    def testRequiredBoolean(self):
        self.assertRaises(FormError, self.parseForm, {'boolean': '',
            ':required': 'boolean'})
        try:
            self.parseForm({'boolean': 'no', ':required': 'boolean'})
        except FormError:
            self.fail('boolean "no" raised "required missing"')

    #
    # Number
    #
    def testEmptyNumber(self):
        self.assertEqual(self.parseForm({'number': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'number': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'number': ['', '']})

    def testInvalidNumber(self):
        self.assertRaises(FormError, self.parseForm, {'number': 'hi, mum!'})

    def testSetNumber(self):
        self.assertEqual(self.parseForm({'number': '1'}),
            ({('test', None): {'number': 1}}, []))
        self.assertEqual(self.parseForm({'number': '0'}),
            ({('test', None): {'number': 0}}, []))
        self.assertEqual(self.parseForm({'number': '\n0\n'}),
            ({('test', None): {'number': 0}}, []))

    def testSetNumberReplaceOne(self):
        nodeid = self.db.test.create(number=1)
        self.assertEqual(self.parseForm({'number': '1'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))
        self.assertEqual(self.parseForm({'number': '0'}, 'test', nodeid),
            ({('test', nodeid): {'number': 0}}, []))

    def testSetNumberReplaceZero(self):
        nodeid = self.db.test.create(number=0)
        self.assertEqual(self.parseForm({'number': '0'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))

    def testSetNumberReplaceNone(self):
        nodeid = self.db.test.create()
        self.assertEqual(self.parseForm({'number': '0'}, 'test', nodeid),
            ({('test', nodeid): {'number': 0}}, []))
        self.assertEqual(self.parseForm({'number': '1'}, 'test', nodeid),
            ({('test', nodeid): {'number': 1}}, []))

    def testEmptyNumberSet(self):
        nodeid = self.db.test.create(number=0)
        self.assertEqual(self.parseForm({'number': ''}, 'test', nodeid),
            ({('test', nodeid): {'number': None}}, []))
        nodeid = self.db.test.create(number=1)
        self.assertEqual(self.parseForm({'number': ' '}, 'test', nodeid),
            ({('test', nodeid): {'number': None}}, []))

    def testRequiredNumber(self):
        self.assertRaises(FormError, self.parseForm, {'number': '',
            ':required': 'number'})
        try:
            self.parseForm({'number': '0', ':required': 'number'})
        except FormError:
            self.fail('number "no" raised "required missing"')

    #
    # Integer
    #
    def testEmptyInteger(self):
        self.assertEqual(self.parseForm({'intval': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'intval': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'intval': ['', '']})

    def testInvalidInteger(self):
        self.assertRaises(FormError, self.parseForm, {'intval': 'hi, mum!'})

    def testSetInteger(self):
        self.assertEqual(self.parseForm({'intval': '1'}),
            ({('test', None): {'intval': 1}}, []))
        self.assertEqual(self.parseForm({'intval': '0'}),
            ({('test', None): {'intval': 0}}, []))
        self.assertEqual(self.parseForm({'intval': '\n0\n'}),
            ({('test', None): {'intval': 0}}, []))

    def testSetIntegerReplaceOne(self):
        nodeid = self.db.test.create(intval=1)
        self.assertEqual(self.parseForm({'intval': '1'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))
        self.assertEqual(self.parseForm({'intval': '0'}, 'test', nodeid),
            ({('test', nodeid): {'intval': 0}}, []))

    def testSetIntegerReplaceZero(self):
        nodeid = self.db.test.create(intval=0)
        self.assertEqual(self.parseForm({'intval': '0'}, 'test', nodeid),
            ({('test', nodeid): {}}, []))

    def testSetIntegerReplaceNone(self):
        nodeid = self.db.test.create()
        self.assertEqual(self.parseForm({'intval': '0'}, 'test', nodeid),
            ({('test', nodeid): {'intval': 0}}, []))
        self.assertEqual(self.parseForm({'intval': '1'}, 'test', nodeid),
            ({('test', nodeid): {'intval': 1}}, []))

    def testEmptyIntegerSet(self):
        nodeid = self.db.test.create(intval=0)
        self.assertEqual(self.parseForm({'intval': ''}, 'test', nodeid),
            ({('test', nodeid): {'intval': None}}, []))
        nodeid = self.db.test.create(intval=1)
        self.assertEqual(self.parseForm({'intval': ' '}, 'test', nodeid),
            ({('test', nodeid): {'intval': None}}, []))

    def testRequiredInteger(self):
        self.assertRaises(FormError, self.parseForm, {'intval': '',
            ':required': 'intval'})
        try:
            self.parseForm({'intval': '0', ':required': 'intval'})
        except FormError:
            self.fail('intval "no" raised "required missing"')

    #
    # Date
    #
    def testEmptyDate(self):
        self.assertEqual(self.parseForm({'date': ''}),
            ({('test', None): {}}, []))
        self.assertEqual(self.parseForm({'date': ' '}),
            ({('test', None): {}}, []))
        self.assertRaises(FormError, self.parseForm, {'date': ['', '']})

    def testInvalidDate(self):
        self.assertRaises(FormError, self.parseForm, {'date': '12'})

    def testSetDate(self):
        self.assertEqual(self.parseForm({'date': '2003-01-01'}),
            ({('test', None): {'date': date.Date('2003-01-01')}}, []))
        nodeid = self.db.test.create(date=date.Date('2003-01-01'))
        self.assertEqual(self.parseForm({'date': '2003-01-01'}, 'test',
            nodeid), ({('test', nodeid): {}}, []))

    def testEmptyDateSet(self):
        nodeid = self.db.test.create(date=date.Date('.'))
        self.assertEqual(self.parseForm({'date': ''}, 'test', nodeid),
            ({('test', nodeid): {'date': None}}, []))
        nodeid = self.db.test.create(date=date.Date('1970-01-01.00:00:00'))
        self.assertEqual(self.parseForm({'date': ' '}, 'test', nodeid),
            ({('test', nodeid): {'date': None}}, []))

    #
    # Test multiple items in form
    #
    def testMultiple(self):
        self.assertEqual(self.parseForm({'string': 'a', 'issue-1@title': 'b'}),
            ({('test', None): {'string': 'a'},
              ('issue', '-1'): {'title': 'b'}
             }, []))

    def testMultipleExistingContext(self):
        nodeid = self.db.test.create()
        self.assertEqual(self.parseForm({'string': 'a', 'issue-1@title': 'b'},
            'test', nodeid),({('test', nodeid): {'string': 'a'},
            ('issue', '-1'): {'title': 'b'}}, []))

    def testLinking(self):
        self.assertEqual(self.parseForm({
            'string': 'a',
            'issue-1@add@nosy': '1',
            'issue-2@link@superseder': 'issue-1',
            }),
            ({('test', None): {'string': 'a'},
              ('issue', '-1'): {'nosy': ['1']},
             },
             [('issue', '-2', 'superseder', [('issue', '-1')])
             ]
            )
        )

    def testMessages(self):
        self.assertEqual(self.parseForm({
            'msg-1@content': 'asdf',
            'msg-2@content': 'qwer',
            '@link@messages': 'msg-1, msg-2'}),
            ({('test', None): {},
              ('msg', '-2'): {'content': 'qwer'},
              ('msg', '-1'): {'content': 'asdf'}},
             [('test', None, 'messages', [('msg', '-1'), ('msg', '-2')])]
            )
        )

    def testLinkBadDesignator(self):
        self.assertRaises(FormError, self.parseForm,
            {'test-1@link@link': 'blah'})
        self.assertRaises(FormError, self.parseForm,
            {'test-1@link@link': 'issue'})

    def testLinkNotLink(self):
        self.assertRaises(FormError, self.parseForm,
            {'test-1@link@boolean': 'issue-1'})
        self.assertRaises(FormError, self.parseForm,
            {'test-1@link@string': 'issue-1'})

    def testBackwardsCompat(self):
        res = self.parseForm({':note': 'spam'}, 'issue')
        date = res[0][('msg', '-1')]['date']
        self.assertEqual(res, ({('issue', None): {}, ('msg', '-1'):
            {'content': 'spam', 'author': '1', 'date': date}},
            [('issue', None, 'messages', [('msg', '-1')])]))
        file = FileUpload('foo', 'foo.txt')
        self.assertEqual(self.parseForm({':file': file}, 'issue'),
            ({('issue', None): {}, ('file', '-1'): {'content': 'foo',
            'name': 'foo.txt', 'type': 'text/plain'}},
            [('issue', None, 'files', [('file', '-1')])]))

    def testFormValuePreserveOnError(self):
        page_template = """
        <html>
         <body>
          <p tal:condition="options/error_message|nothing"
             tal:repeat="m options/error_message"
             tal:content="structure m"/>
          <p tal:content="context/title/plain"/>
          <p tal:content="context/priority/plain"/>
          <p tal:content="context/status/plain"/>
          <p tal:content="context/nosy/plain"/>
          <p tal:content="context/keyword/plain"/>
          <p tal:content="structure context/superseder/field"/>
         </body>
        </html>
        """.strip ()
        self.db.keyword.create (name = 'key1')
        self.db.keyword.create (name = 'key2')
        nodeid = self.db.issue.create (title = 'Title', priority = '1',
            status = '1', nosy = ['1'], keyword = ['1'])
        self.db.commit ()
        form = {':note': 'msg-content', 'title': 'New title',
            'priority': '2', 'status': '2', 'nosy': '1,2', 'keyword': '',
            'superseder': '5000', ':action': 'edit'}
        cl = self.setupClient(form, 'issue', '1')
        pt = RoundupPageTemplate()
        pt.pt_edit(page_template, 'text/html')
        out = []
        def wh(s):
            out.append(s)
        cl.write_html = wh
        # Enable the following if we get a templating error:
        #def send_error (*args, **kw):
        #    import pdb; pdb.set_trace()
        #cl.send_error_to_admin = send_error
        # Need to rollback the database on error -- this usually happens
        # in web-interface (and for other databases) anyway, need it for
        # testing that the form values are really used, not the database!
        # We do this together with the setup of the easy template above
        def load_template(x):
            cl.db.rollback()
            return pt
        cl.instance.templates.load = load_template
        cl.selectTemplate = MockNull()
        cl.determine_context = MockNull ()
        def hasPermission(s, p, classname=None, d=None, e=None, **kw):
            return True
        actions.Action.hasPermission = hasPermission
        e1 = _HTMLItem.is_edit_ok
        _HTMLItem.is_edit_ok = lambda x : True
        e2 = HTMLProperty.is_edit_ok
        HTMLProperty.is_edit_ok = lambda x : True
        cl.inner_main()
        _HTMLItem.is_edit_ok = e1
        HTMLProperty.is_edit_ok = e2
        self.assertEqual(len(out), 1)
        self.assertEqual(out [0].strip (), """
        <html>
         <body>
          <p>Edit Error: issue has no node 5000</p>
          <p>New title</p>
          <p>urgent</p>
          <p>deferred</p>
          <p>admin, anonymous</p>
          <p></p>
          <p><input type="text" name="superseder" value="5000" size="30"></p>
         </body>
        </html>
        """.strip ())

    #
    # SECURITY
    #
    # XXX test all default permissions
    def _make_client(self, form, classname='user', nodeid='1',
           userid='2', template='item'):
        cl = client.Client(self.instance, None, {'PATH_INFO':'/',
            'REQUEST_METHOD':'POST'}, makeForm(form))
        cl.classname = classname
        if nodeid is not None:
            cl.nodeid = nodeid
        cl.db = self.db
        cl.userid = userid
        cl.language = ('en',)
        cl._error_message = []
        cl._ok_message = []
        cl.template = template
        return cl

    def testClassPermission(self):
        cl = self._make_client(dict(username='bob'))
        self.failUnlessRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl.nodeid = '1'
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)

    def testCheckAndPropertyPermission(self):
        self.db.security.permissions = {}
        def own_record(db, userid, itemid):
            return userid == itemid
        p = self.db.security.addPermission(name='Edit', klass='user',
            check=own_record, properties=("password", ))
        self.db.security.addPermissionToRole('User', p)

        cl = self._make_client(dict(username='bob'))
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl = self._make_client(dict(roles='User,Admin'), userid='4', nodeid='4')
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl = self._make_client(dict(roles='User,Admin'), userid='4')
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl = self._make_client(dict(roles='User,Admin'))
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        # working example, mary may change her pw
        cl = self._make_client({'password':'ob', '@confirm@password':'ob'},
            nodeid='4', userid='4')
        self.assertRaises(exceptions.Redirect,
            actions.EditItemAction(cl).handle)
        cl = self._make_client({'password':'bob', '@confirm@password':'bob'})
        self.failUnlessRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)

    def testCreatePermission(self):
        # this checks if we properly differentiate between create and
        # edit permissions
        self.db.security.permissions = {}
        self.db.security.addRole(name='UserAdd')
        # Don't allow roles
        p = self.db.security.addPermission(name='Create', klass='user',
            properties=("username", "password", "address",
            "alternate_address", "realname", "phone", "organisation",
            "timezone"))
        self.db.security.addPermissionToRole('UserAdd', p)
        # Don't allow roles *and* don't allow username
        p = self.db.security.addPermission(name='Edit', klass='user',
            properties=("password", "address", "alternate_address",
            "realname", "phone", "organisation", "timezone"))
        self.db.security.addPermissionToRole('UserAdd', p)
        self.db.user.set('4', roles='UserAdd')

        # anonymous may not
        cl = self._make_client({'username':'new_user', 'password':'secret',
            '@confirm@password':'secret', 'address':'new_user@bork.bork',
            'roles':'Admin'}, nodeid=None, userid='2')
        self.assertRaises(exceptions.Unauthorised,
            actions.NewItemAction(cl).handle)
        # Don't allow creating new user with roles
        cl = self._make_client({'username':'new_user', 'password':'secret',
            '@confirm@password':'secret', 'address':'new_user@bork.bork',
            'roles':'Admin'}, nodeid=None, userid='4')
        self.assertRaises(exceptions.Unauthorised,
            actions.NewItemAction(cl).handle)
        self.assertEqual(cl._error_message,[])
        # this should work
        cl = self._make_client({'username':'new_user', 'password':'secret',
            '@confirm@password':'secret', 'address':'new_user@bork.bork'},
            nodeid=None, userid='4')
        self.assertRaises(exceptions.Redirect,
            actions.NewItemAction(cl).handle)
        self.assertEqual(cl._error_message,[])
        # don't allow changing (my own) username (in this example)
        cl = self._make_client(dict(username='new_user42'), userid='4')
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl = self._make_client(dict(username='new_user42'), userid='4',
            nodeid='4')
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        # don't allow changing (my own) roles
        cl = self._make_client(dict(roles='User,Admin'), userid='4',
            nodeid='4')
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl = self._make_client(dict(roles='User,Admin'), userid='4')
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)
        cl = self._make_client(dict(roles='User,Admin'))
        self.assertRaises(exceptions.Unauthorised,
            actions.EditItemAction(cl).handle)

    def testSearchPermission(self):
        # this checks if we properly check for search permissions
        self.db.security.permissions = {}
        self.db.security.addRole(name='User')
        self.db.security.addRole(name='Project')
        self.db.security.addPermissionToRole('User', 'Web Access')
        self.db.security.addPermissionToRole('Project', 'Web Access')
        # Allow viewing department
        p = self.db.security.addPermission(name='View', klass='department')
        self.db.security.addPermissionToRole('User', p)
        # Allow viewing interesting things (but not department) on iss
        # But users might only view issues where they are on nosy
        # (so in the real world the check method would be better)
        p = self.db.security.addPermission(name='View', klass='iss',
            properties=("title", "status"), check=lambda x,y,z: True)
        self.db.security.addPermissionToRole('User', p)
        # Allow all relevant roles access to stat
        p = self.db.security.addPermission(name='View', klass='stat')
        self.db.security.addPermissionToRole('User', p)
        self.db.security.addPermissionToRole('Project', p)
        # Allow role "Project" access to whole iss
        p = self.db.security.addPermission(name='View', klass='iss')
        self.db.security.addPermissionToRole('Project', p)

        department = self.instance.backend.Class(self.db, "department",
            name=hyperdb.String())
        status = self.instance.backend.Class(self.db, "stat",
            name=hyperdb.String())
        issue = self.instance.backend.Class(self.db, "iss",
            title=hyperdb.String(), status=hyperdb.Link('stat'),
            department=hyperdb.Link('department'))

        d1 = department.create(name='d1')
        d2 = department.create(name='d2')
        open = status.create(name='open')
        closed = status.create(name='closed')
        issue.create(title='i1', status=open, department=d2)
        issue.create(title='i2', status=open, department=d1)
        issue.create(title='i2', status=closed, department=d1)

        chef = self.db.user.lookup('Chef')
        mary = self.db.user.lookup('mary')
        self.db.user.set(chef, roles = 'User, Project')

        perm = self.db.security.hasPermission
        search = self.db.security.hasSearchPermission
        self.assert_(perm('View', chef, 'iss', 'department', '1'))
        self.assert_(perm('View', chef, 'iss', 'department', '2'))
        self.assert_(perm('View', chef, 'iss', 'department', '3'))
        self.assert_(search(chef, 'iss', 'department'))

        self.assert_(not perm('View', mary, 'iss', 'department'))
        self.assert_(perm('View', mary, 'iss', 'status'))
        # Conditionally allow view of whole iss (check is False here,
        # this might check for department owner in the real world)
        p = self.db.security.addPermission(name='View', klass='iss',
            check=lambda x,y,z: False)
        self.db.security.addPermissionToRole('User', p)
        self.assert_(perm('View', mary, 'iss', 'department'))
        self.assert_(not perm('View', mary, 'iss', 'department', '1'))
        self.assert_(not search(mary, 'iss', 'department'))

        self.assert_(perm('View', mary, 'iss', 'status'))
        self.assert_(not search(mary, 'iss', 'status'))
        # Allow user to search for iss.status
        p = self.db.security.addPermission(name='Search', klass='iss',
            properties=("status",))
        self.db.security.addPermissionToRole('User', p)
        self.assert_(search(mary, 'iss', 'status'))

        dep = {'@action':'search','columns':'id','@filter':'department',
            'department':'1'}
        stat = {'@action':'search','columns':'id','@filter':'status',
            'status':'1'}
        depsort = {'@action':'search','columns':'id','@sort':'department'}
        depgrp = {'@action':'search','columns':'id','@group':'department'}

        # Filter on department ignored for role 'User':
        cl = self._make_client(dep, classname='iss', nodeid=None, userid=mary,
            template='index')
        h = HTMLRequest(cl)
        self.assertEqual([x.id for x in h.batch()],['1', '2', '3'])
        # Filter on department works for role 'Project':
        cl = self._make_client(dep, classname='iss', nodeid=None, userid=chef,
            template='index')
        h = HTMLRequest(cl)
        self.assertEqual([x.id for x in h.batch()],['2', '3'])
        # Filter on status works for all:
        cl = self._make_client(stat, classname='iss', nodeid=None, userid=mary,
            template='index')
        h = HTMLRequest(cl)
        self.assertEqual([x.id for x in h.batch()],['1', '2'])
        cl = self._make_client(stat, classname='iss', nodeid=None, userid=chef,
            template='index')
        h = HTMLRequest(cl)
        self.assertEqual([x.id for x in h.batch()],['1', '2'])
        # Sorting and grouping for class Project works:
        cl = self._make_client(depsort, classname='iss', nodeid=None,
            userid=chef, template='index')
        h = HTMLRequest(cl)
        self.assertEqual([x.id for x in h.batch()],['2', '3', '1'])
        self.assertEqual(cl._error_message, []) # test for empty _error_message when sort is valid
        self.assertEqual(cl._ok_message, []) # test for empty _ok_message when sort is valid

        # Test for correct _error_message for invalid sort/group properties
        baddepsort = {'@action':'search','columns':'id','@sort':'dep'}
        baddepgrp = {'@action':'search','columns':'id','@group':'dep'}
        cl = self._make_client(baddepsort, classname='iss', nodeid=None,
            userid=chef, template='index')
        h = HTMLRequest(cl)
        self.assertEqual(cl._error_message, ['Unknown sort property dep'])
        cl = self._make_client(baddepgrp, classname='iss', nodeid=None,
            userid=chef, template='index')
        h = HTMLRequest(cl)
        self.assertEqual(cl._error_message, ['Unknown group property dep'])

        cl = self._make_client(depgrp, classname='iss', nodeid=None,
            userid=chef, template='index')
        h = HTMLRequest(cl)
        self.assertEqual([x.id for x in h.batch()],['2', '3', '1'])
        # Sorting and grouping for class User fails:
        cl = self._make_client(depsort, classname='iss', nodeid=None,
            userid=mary, template='index')
        h = HTMLRequest(cl)
        self.assertEqual([x.id for x in h.batch()],['1', '2', '3'])
        cl = self._make_client(depgrp, classname='iss', nodeid=None,
            userid=mary, template='index')
        h = HTMLRequest(cl)
        self.assertEqual([x.id for x in h.batch()],['1', '2', '3'])

    def testEditCSV(self):
        form = dict(rows='id,name\n1,newkey')
        cl = self._make_client(form, userid='1', classname='keyword')
        cl._ok_message = []
        actions.EditCSVAction(cl).handle()
        self.assertEqual(cl._ok_message, ['Items edited OK'])
        k = self.db.keyword.getnode('1')
        self.assertEqual(k.name, 'newkey')
        form = dict(rows=u'id,name\n1,\xe4\xf6\xfc'.encode('utf-8'))
        cl = self._make_client(form, userid='1', classname='keyword')
        cl._ok_message = []
        actions.EditCSVAction(cl).handle()
        self.assertEqual(cl._ok_message, ['Items edited OK'])
        k = self.db.keyword.getnode('1')
        self.assertEqual(k.name, u'\xe4\xf6\xfc'.encode('utf-8'))

    def testRoles(self):
        cl = self._make_client({})
        self.db.user.set('1', roles='aDmin,    uSer')
        item = HTMLItem(cl, 'user', '1')
        self.assert_(item.hasRole('Admin'))
        self.assert_(item.hasRole('User'))
        self.assert_(item.hasRole('AdmiN'))
        self.assert_(item.hasRole('UseR'))
        self.assert_(item.hasRole('UseR','Admin'))
        self.assert_(item.hasRole('UseR','somethingelse'))
        self.assert_(item.hasRole('somethingelse','Admin'))
        self.assert_(not item.hasRole('userr'))
        self.assert_(not item.hasRole('adminn'))
        self.assert_(not item.hasRole(''))
        self.assert_(not item.hasRole(' '))
        self.db.user.set('1', roles='')
        self.assert_(not item.hasRole(''))

    def testCSVExport(self):
        cl = self._make_client({'@columns': 'id,name'}, nodeid=None,
            userid='1')
        cl.classname = 'status'
        output = StringIO.StringIO()
        cl.request = MockNull()
        cl.request.wfile = output
        actions.ExportCSVAction(cl).handle()
        self.assertEquals('id,name\r\n1,unread\r\n2,deferred\r\n3,chatting\r\n'
            '4,need-eg\r\n5,in-progress\r\n6,testing\r\n7,done-cbb\r\n'
            '8,resolved\r\n',
            output.getvalue())

    def testCSVExportBadColumnName(self):
        cl = self._make_client({'@columns': 'falseid,name'}, nodeid=None,
            userid='1')
        cl.classname = 'status'
        output = StringIO.StringIO()
        cl.request = MockNull()
        cl.request.wfile = output
        self.assertRaises(exceptions.NotFound,
            actions.ExportCSVAction(cl).handle)

    def testCSVExportFailPermissionBadColumn(self):
        cl = self._make_client({'@columns': 'id,email,password'}, nodeid=None,
            userid='2')
        cl.classname = 'user'
        output = StringIO.StringIO()
        cl.request = MockNull()
        cl.request.wfile = output
        # used to be self.assertRaises(exceptions.Unauthorised,
        # but not acting like the column name is not found
        # see issue2550755 - should this return Unauthorised?
        # The unauthorised user should never get to the point where
        # they can determine if the column name is valid or not.
        self.assertRaises(exceptions.NotFound,
            actions.ExportCSVAction(cl).handle)

    def testCSVExportFailPermissionValidColumn(self):
        cl = self._make_client({'@columns': 'id,address,password'}, nodeid=None,
            userid='2')
        cl.classname = 'user'
        output = StringIO.StringIO()
        cl.request = MockNull()
        cl.request.wfile = output
        # used to be self.assertRaises(exceptions.Unauthorised,
        # but not acting like the column name is not found
        self.assertRaises(exceptions.Unauthorised,
            actions.ExportCSVAction(cl).handle)

class TemplateHtmlRendering(unittest.TestCase):
    ''' try to test the rendering code for tal '''
    def setUp(self):
        self.dirname = '_test_template'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname)

        # open the database
        self.db = self.instance.open('admin')
        self.db.tx_Source = "web"
        self.db.user.create(username='Chef', address='chef@bork.bork.bork',
            realname='Bork, Chef', roles='User')
        self.db.user.create(username='mary', address='mary@test.test',
            roles='User', realname='Contrary, Mary')
        self.db.post_init()

        # create a client instance and hijack write_html
        self.client = client.Client(self.instance, "user",
                {'PATH_INFO':'/user', 'REQUEST_METHOD':'POST'},
                form=makeForm({"@template": "item"}))

        self.client._error_message = []
        self.client._ok_message = []
        self.client.db = self.db
        self.client.userid = '1'
        self.client.language = ('en',)

        self.output = []
        # ugly hack to get html_write to return data here.
        def html_write(s):
            self.output.append(s)

        # hijack html_write
        self.client.write_html = html_write

        self.db.issue.create(title='foo')

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testrenderFrontPage(self):
        self.client.renderFrontPage("hello world RaNdOmJunk")
        # make sure we can find the "hello world RaNdOmJunk"
        # message in the output.
        self.assertNotEqual(-1,
           self.output[0].index('<p class="error-message">hello world RaNdOmJunk <br/ > </p>'))
        # make sure we can find issue 1 title foo in the output
        self.assertNotEqual(-1,
           self.output[0].index('<a href="issue1">foo</a>'))

        # make sure we can find the last SHA1 sum line at the end of the
        # page
        self.assertNotEqual(-1,
           self.output[0].index('<!-- SHA: c87a4e18d59a527331f1d367c0c6cc67ee123e63 -->'))

    def testrenderContext(self):
        # set up the client;
        # run determine_context to set the required client attributes
        # run renderContext(); check result for proper page

        # this will generate the default home page like
        # testrenderFrontPage
        self.client.form=makeForm({})
        self.client.path = ''
        self.client.determine_context()
        self.assertEqual((self.client.classname, self.client.template, self.client.nodeid), (None, '', None))
        self.assertEqual(self.client._ok_message, [])

        result = self.client.renderContext()
        self.assertNotEqual(-1,
           result.index('<!-- SHA: c87a4e18d59a527331f1d367c0c6cc67ee123e63 -->'))

        # now look at the user index page
        self.client.form=makeForm({ "@ok_message": "ok message", "@template": "index"})
        self.client.path = 'user'
        self.client.determine_context()
        self.assertEqual((self.client.classname, self.client.template, self.client.nodeid), ('user', 'index', None))
        self.assertEqual(self.client._ok_message, ['ok message'])

        result = self.client.renderContext()
        self.assertNotEqual(-1, result.index('<title>User listing - Roundup issue tracker</title>'))
        self.assertNotEqual(-1, result.index('ok message'))
        # print result

    def testRenderAltTemplates(self):
        # check that right page is returned when rendering
        #  @template=oktempl|errortmpl

        # set up the client;
        # run determine_context to set the required client attributes
        # run renderContext(); check result for proper page

        # Test ok state template that uses user.forgotten.html
        self.client.form=makeForm({"@template": "forgotten|item"})
        self.client.path = 'user'
        self.client.determine_context()
        self.assertEqual((self.client.classname, self.client.template, self.client.nodeid), ('user', 'forgotten|item', None))
        self.assertEqual(self.client._ok_message, [])
        
        result = self.client.renderContext()
        self.assertNotEqual(-1,
                            result.index('<!-- SHA: 6fdb58c55fd854904ae98906d5935549a221fabf -->'))

        # now set an error in the form to get error template user.item.html
        self.client.form=makeForm({"@template": "forgotten|item",
                                   "@error_message": "this is an error"})
        self.client.path = 'user'
        self.client.determine_context()
        self.assertEqual((self.client.classname, self.client.template, self.client.nodeid), ('user', 'forgotten|item', None))
        self.assertEqual(self.client._ok_message, [])
        self.assertEqual(self.client._error_message, ["this is an error"])
        
        result = self.client.renderContext()
        print(result)
        self.assertNotEqual(-1,
                            result.index('<!-- SHA: 3b7ce7cbf24f77733c9b9f64a569d6429390cc3f -->'))


    def testexamine_url(self):
        ''' test the examine_url function '''

        def te(url, exception, raises=ValueError):
            with self.assertRaises(raises) as cm:
                examine_url(url)
            self.assertEqual(cm.exception.message, exception)


        action = actions.Action(self.client)
        examine_url = action.examine_url

        # Christmas tree url: test of every component that passes
        self.assertEqual(
            examine_url("http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue"),
            'http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue')

        # allow replacing http with https if base is http
        self.assertEqual(
            examine_url("https://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue"),
            'https://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue')


        # change base to use https and make sure we don't redirect to http
        saved_base = action.base
        action.base = "https://tracker.example/cgi-bin/roundup.cgi/bugs/"
        te("http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue",
           'Base url https://tracker.example/cgi-bin/roundup.cgi/bugs/ requires https. Redirect url http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue uses http.')
        action.base = saved_base

        # url doesn't have to be valid to roundup, just has to be contained
        # inside of roundup. No zoik class is defined
        self.assertEqual(examine_url("http://tracker.example/cgi-bin/roundup.cgi/bugs/zoik7;parm=bar?@template=foo&parm=(zot)#issue"), "http://tracker.example/cgi-bin/roundup.cgi/bugs/zoik7;parm=bar?@template=foo&parm=(zot)#issue")

        # test with wonky schemes
        te("email://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue",
        'Unrecognized scheme in email://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue')

        te("http%3a//tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue", 'Unrecognized scheme in http%3a//tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue')

        # test different netloc/path prefix
        # assert port
        te("http://tracker.example:1025/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue",'Net location in http://tracker.example:1025/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue does not match base: tracker.example')

        #assert user
        te("http://user@tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue", 'Net location in http://user@tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue does not match base: tracker.example')

        #assert user:password
        te("http://user:pass@tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue", 'Net location in http://user:pass@tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue does not match base: tracker.example')

        # try localhost http scheme
        te("http://localhost/cgi-bin/roundup.cgi/bugs/user3", 'Net location in http://localhost/cgi-bin/roundup.cgi/bugs/user3 does not match base: tracker.example')

        # try localhost https scheme
        te("https://localhost/cgi-bin/roundup.cgi/bugs/user3", 'Net location in https://localhost/cgi-bin/roundup.cgi/bugs/user3 does not match base: tracker.example')

        # try different host
        te("http://bad.guys.are.us/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue", 'Net location in http://bad.guys.are.us/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#issue does not match base: tracker.example')

        # change the base path to .../bug from .../bugs
        te("http://tracker.example/cgi-bin/roundup.cgi/bug/user3;parm=bar?@template=foo&parm=(zot)#issue", 'Base path /cgi-bin/roundup.cgi/bugs/ is not a prefix for url http://tracker.example/cgi-bin/roundup.cgi/bug/user3;parm=bar?@template=foo&parm=(zot)#issue')

        # change the base path eliminate - in cgi-bin
        te("http://tracker.example/cgibin/roundup.cgi/bug/user3;parm=bar?@template=foo&parm=(zot)#issue",'Base path /cgi-bin/roundup.cgi/bugs/ is not a prefix for url http://tracker.example/cgibin/roundup.cgi/bug/user3;parm=bar?@template=foo&parm=(zot)#issue')


        # scan for unencoded characters
        # we skip schema and net location since unencoded character
        # are allowed only by an explicit match to a reference.
        #
        # break components with unescaped character '<'
        # path component
        te("http://tracker.example/cgi-bin/roundup.cgi/bugs/<user3;parm=bar?@template=foo&parm=(zot)#issue", 'Path component (/cgi-bin/roundup.cgi/bugs/<user3) in http://tracker.example/cgi-bin/roundup.cgi/bugs/<user3;parm=bar?@template=foo&parm=(zot)#issue is not properly escaped')

        # params component
        te("http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=b<ar?@template=foo&parm=(zot)#issue", 'Params component (parm=b<ar) in http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=b<ar?@template=foo&parm=(zot)#issue is not properly escaped')

        # query component
        te("http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=<foo>&parm=(zot)#issue", 'Query component (@template=<foo>&parm=(zot)) in http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=<foo>&parm=(zot)#issue is not properly escaped')

        # fragment component
        te("http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#iss<ue", 'Fragment component (iss<ue) in http://tracker.example/cgi-bin/roundup.cgi/bugs/user3;parm=bar?@template=foo&parm=(zot)#iss<ue is not properly escaped')

class TemplateTestCase(unittest.TestCase):
    ''' Test the template resolving code, i.e. what can be given to @template
    '''
    def setUp(self):
        self.dirname = '_test_template'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname)

        # open the database
        self.db = self.instance.open('admin')
        self.db.tx_Source = "web"
        self.db.user.create(username='Chef', address='chef@bork.bork.bork',
            realname='Bork, Chef', roles='User')
        self.db.user.create(username='mary', address='mary@test.test',
            roles='User', realname='Contrary, Mary')
        self.db.post_init()

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testTemplateSubdirectory(self):
        # test for templates in subdirectories

        # make the directory
        subdir = self.dirname + "/html/subdir"
        os.mkdir(subdir)

        # get the client instance The form is needed to initialize,
        # but not used since I call selectTemplate directly.
        t = client.Client(self.instance, "user",
                {'PATH_INFO':'/user', 'REQUEST_METHOD':'POST'},
         form=makeForm({"@template": "item"}))

        # create new file in subdir and a dummy file outside of
        # the tracker's html subdirectory
        shutil.copyfile(self.dirname + "/html/issue.item.html",
                        subdir + "/issue.item.html")
        shutil.copyfile(self.dirname + "/html/user.item.html",
                        self.dirname + "/user.item.html")

        # create link outside the html subdir. This should fail due to
        # path traversal check.
        os.symlink("../../user.item.html", subdir + "/user.item.html")
        # it will be removed and replaced by a later test

        # make sure a simple non-subdir template works.
        # user.item.html exists so this works.
        # note that the extension is not included just the basename
        self.assertEqual("user.item", t.selectTemplate("user", "item"))


        # make sure home templates work
        self.assertEqual("home", t.selectTemplate(None, ""))
        self.assertEqual("home.classlist", t.selectTemplate(None, "classlist"))

        # home.item doesn't exist should return _generic.item.
        self.assertEqual("_generic.item", t.selectTemplate(None, "item"))

        # test case where there is no view so generic template can't
        # be determined.
        with self.assertRaises(NoTemplate) as cm:
            t.selectTemplate("user", "")
        self.assertEqual(cm.exception.message,
                         '''Template "user" doesn't exist''')

        # there is no html/subdir/user.item.{,xml,html} so it will
        # raise NoTemplate.
        self.assertRaises(NoTemplate,
                          t.selectTemplate, "user", "subdir/item")

        # there is an html/subdir/issue.item.html so this succeeeds
        r = t.selectTemplate("issue", "subdir/item")
        self.assertEqual("subdir/issue.item", r)

        # there is a self.directory + /html/subdir/user.item.html file,
        # but it is a link to self.dir /user.item.html which is outside
        # the html subdir so is rejected by the path traversal check.
        # Prefer NoTemplate here, or should the code be changed to
        # report a new PathTraversal exception? Could the PathTraversal
        # exception leak useful info to an attacker??
        self.assertRaises(NoTemplate,
                          t.selectTemplate, "user", "subdir/item")

        # clear out the link and create a new one to self.dirname +
        # html/user.item.html which is inside the html subdir
        # so the template check returns the symbolic link path.
        os.remove(subdir + "/user.item.html")
        os.symlink("../user.item.html", subdir + "/user.item.xml")

        # template check works
        r = t.selectTemplate("user", "subdir/item")
        self.assertEquals("subdir/user.item", r)

# vim: set filetype=python sts=4 sw=4 et si :
