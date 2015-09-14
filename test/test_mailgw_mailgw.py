import mailbox
import textwrap
import os
from tempfile import mkstemp
from unittest import TestCase

from roundup import mailgw
from roundup.hyperdb import String

from . import memorydb
from .test_mailgw import Tracker


class DoMailboxMailGWTests(TestCase):
    def setUp(self):
        class MailGW(mailgw.MailGW):
            def handle_message(self, message):
                self.db = self.instance.db
                # HACK: memorydb hardcoded auditor requires tx_Source to be set
                self.db.tx_Source = "email"
                return self._handle_message(message)

        _, self.filename = mkstemp()

        self.db = memorydb.create('admin')
        self.instance = Tracker()
        self.instance.db = self.db
        self.instance.config = self.db.config
        self.mailgw = MailGW(self.instance)

        # HACK: memorydb hardcodes the tx_Source property
        self.db.issue.addprop(tx_Source=String())
        self.db.msg.addprop(tx_Source=String())

        self.db.user.create(**{
            'username': 'suser',
            'address': 'some.user@example.com',
            'realname': 'Some User',
            'roles': 'User',
        })

    def tearDown(self):
        if os.path.exists(self.filename):
            os.unlink(self.filename)

    def write_to_mbox(self, contents):
        with open(self.filename, 'w') as f:
            f.write(textwrap.dedent(contents).lstrip())

    def test_parse_mbox(self):
        self.write_to_mbox("""
            From some.user@example.com Sat Sep 08 16:36:56 2012
            Content-Type: text/plain;
                charset="iso-8859-1"
            From: Some User <some.user@example.com>
            To: Issue Tracker <issue_tracker@example.com>
            Message-Id: <dummy_test_message_id>
            Subject: New Issue One

            This is a test submission of a new issue.


            From some.user@example.com Sat Sep 08 17:26:36 2012
            Content-Type: text/plain;
                charset="iso-8859-1"
            From: Some User <some.user@example.com>
            To: Issue Tracker <issue_tracker@example.com>
            Message-Id: <dummy_test_message_id>
            Subject: New Issue Two

            This is a test submission of another new issue.
        """)
        self.assertEqual(self.mailgw.do_mailbox(self.filename), 0)
        self.assertEqual(len(self.db.issue.list()), 2)

        # First email
        issue = self.db.issue.getnode('1')
        self.assertEqual(issue.title, 'New Issue One')
        self.assertEqual(issue.messages, ['1'])
        msg = self.db.msg.getnode('1')
        self.assertEqual(
            msg.content, 'This is a test submission of a new issue.')

        # Second email
        issue = self.db.issue.getnode('2')
        self.assertEqual(issue.title, 'New Issue Two')
        self.assertEqual(issue.messages, ['2'])
        msg = self.db.msg.getnode('2')
        self.assertEqual(
            msg.content, 'This is a test submission of another new issue.')

        mbox = mailbox.mbox(self.filename)
        mbox.lock()
        self.assertEqual(len(mbox.keys()), 0)
        mbox.unlock()
        mbox.close()

    def test_parse_partial_mbox(self):
        self.mailgw.trapExceptions = False
        self.write_to_mbox("""
            From some.user@example.com Sat Sep 08 16:36:56 2012
            Content-Type: text/plain;
                charset="iso-8859-1"
            From: Some User <some.user@example.com>
            To: Issue Tracker <issue_tracker@example.com>
            Message-Id: <dummy_test_message_id>
            Subject: New Issue One

            This is a test submission of a new issue.


            From some.user@example.com Sat Sep 08 17:26:36 2012
            Content-Type: text/plain;
                charset="iso-8859-1"
            From: Some User <some.user@example.com>
            To: Issue Tracker <issue_tracker@example.com>
            Message-Id: <dummy_test_message_id>
            X-No-Subject: New Issue Two

            This is a test submission of another new issue.
        """)
        self.assertEqual(self.mailgw.do_mailbox(self.filename), 1)
        self.assertEqual(len(self.db.issue.list()), 1)

        # First email
        issue = self.db.issue.getnode('1')
        self.assertEqual(issue.title, 'New Issue One')
        self.assertEqual(issue.messages, ['1'])
        msg = self.db.msg.getnode('1')
        self.assertEqual(
            msg.content, 'This is a test submission of a new issue.')

        mbox = mailbox.mbox(self.filename)
        mbox.lock()
        self.assertEqual(len(mbox.keys()), 1)
        mbox.unlock()
        mbox.close()

    def test_invalid_mailbox(self):
        os.unlink(self.filename)

        self.assertEqual(self.mailgw.do_mailbox(self.filename), 1)

    def test_locked_mailbox(self):
        mbox = mailbox.mbox(self.filename, create=False)
        mbox.lock()

        self.assertEqual(self.mailgw.do_mailbox(self.filename), 1)

        mbox.unlock()
        mbox.close()
