import re
import unittest
from urlparse import urlsplit, urlunsplit
from xml.dom.minidom import parseString, Node

from django.conf import settings
from django.core.management import call_command
from django.db import transaction, connections, DEFAULT_DB_ALIAS
from django.test import _doctest as doctest
from django.utils import simplejson
from django.utils.encoding import smart_str

try:
    all
except NameError:
    from django.utils.itercompat import all

normalize_long_ints = lambda s: re.sub(r'(?<![\w])(\d+)L(?![\w])', '\\1', s)
normalize_decimals = lambda s: re.sub(r"Decimal\('(\d+(\.\d*)?)'\)", lambda m: "Decimal(\"%s\")" % m.groups()[0], s)

def to_list(value):
    """
    Puts value into a list if it's not already one.
    Returns an empty list if value is None.
    """
    if value is None:
        value = []
    elif not isinstance(value, list):
        value = [value]
    return value

real_commit = transaction.commit
real_rollback = transaction.rollback
real_enter_transaction_management = transaction.enter_transaction_management
real_leave_transaction_management = transaction.leave_transaction_management
real_savepoint_commit = transaction.savepoint_commit
real_savepoint_rollback = transaction.savepoint_rollback
real_managed = transaction.managed

def nop(*args, **kwargs):
    return

def disable_transaction_methods():
    transaction.commit = nop
    transaction.rollback = nop
    transaction.savepoint_commit = nop
    transaction.savepoint_rollback = nop
    transaction.enter_transaction_management = nop
    transaction.leave_transaction_management = nop
    transaction.managed = nop

def restore_transaction_methods():
    transaction.commit = real_commit
    transaction.rollback = real_rollback
    transaction.savepoint_commit = real_savepoint_commit
    transaction.savepoint_rollback = real_savepoint_rollback
    transaction.enter_transaction_management = real_enter_transaction_management
    transaction.leave_transaction_management = real_leave_transaction_management
    transaction.managed = real_managed

class OutputChecker(doctest.OutputChecker):
    def check_output(self, want, got, optionflags):
        "The entry method for doctest output checking. Defers to a sequence of child checkers"
        checks = (self.check_output_default,
                  self.check_output_numeric,
                  self.check_output_xml,
                  self.check_output_json)
        for check in checks:
            if check(want, got, optionflags):
                return True
        return False

    def check_output_default(self, want, got, optionflags):
        "The default comparator provided by doctest - not perfect, but good for most purposes"
        return doctest.OutputChecker.check_output(self, want, got, optionflags)

    def check_output_numeric(self, want, got, optionflags):
        """Doctest does an exact string comparison of output, which means that
        some numerically equivalent values aren't equal. This check normalizes
         * long integers (22L) so that they equal normal integers. (22)
         * Decimals so that they are comparable, regardless of the change
           made to __repr__ in Python 2.6.
        """
        return doctest.OutputChecker.check_output(self,
            normalize_decimals(normalize_long_ints(want)),
            normalize_decimals(normalize_long_ints(got)),
            optionflags)

    def check_output_xml(self, want, got, optionsflags):
        """Tries to do a 'xml-comparision' of want and got.  Plain string
        comparision doesn't always work because, for example, attribute
        ordering should not be important.

        Based on http://codespeak.net/svn/lxml/trunk/src/lxml/doctestcompare.py
        """
        _norm_whitespace_re = re.compile(r'[ \t\n][ \t\n]+')
        def norm_whitespace(v):
            return _norm_whitespace_re.sub(' ', v)

        def child_text(element):
            return ''.join([c.data for c in element.childNodes
                            if c.nodeType == Node.TEXT_NODE])

        def children(element):
            return [c for c in element.childNodes
                    if c.nodeType == Node.ELEMENT_NODE]

        def norm_child_text(element):
            return norm_whitespace(child_text(element))

        def attrs_dict(element):
            return dict(element.attributes.items())

        def check_element(want_element, got_element):
            if want_element.tagName != got_element.tagName:
                return False
            if norm_child_text(want_element) != norm_child_text(got_element):
                return False
            if attrs_dict(want_element) != attrs_dict(got_element):
                return False
            want_children = children(want_element)
            got_children = children(got_element)
            if len(want_children) != len(got_children):
                return False
            for want, got in zip(want_children, got_children):
                if not check_element(want, got):
                    return False
            return True

        want, got = self._strip_quotes(want, got)
        want = want.replace('\\n','\n')
        got = got.replace('\\n','\n')

        # If the string is not a complete xml document, we may need to add a
        # root element. This allow us to compare fragments, like "<foo/><bar/>"
        if not want.startswith('<?xml'):
            wrapper = '<root>%s</root>'
            want = wrapper % want
            got = wrapper % got

        # Parse the want and got strings, and compare the parsings.
        try:
            want_root = parseString(want).firstChild
            got_root = parseString(got).firstChild
        except:
            return False
        return check_element(want_root, got_root)

    def check_output_json(self, want, got, optionsflags):
        "Tries to compare want and got as if they were JSON-encoded data"
        want, got = self._strip_quotes(want, got)
        try:
            want_json = simplejson.loads(want)
            got_json = simplejson.loads(got)
        except:
            return False
        return want_json == got_json

    def _strip_quotes(self, want, got):
        """
        Strip quotes of doctests output values:

        >>> o = OutputChecker()
        >>> o._strip_quotes("'foo'")
        "foo"
        >>> o._strip_quotes('"foo"')
        "foo"
        >>> o._strip_quotes("u'foo'")
        "foo"
        >>> o._strip_quotes('u"foo"')
        "foo"
        """
        def is_quoted_string(s):
            s = s.strip()
            return (len(s) >= 2
                    and s[0] == s[-1]
                    and s[0] in ('"', "'"))

        def is_quoted_unicode(s):
            s = s.strip()
            return (len(s) >= 3
                    and s[0] == 'u'
                    and s[1] == s[-1]
                    and s[1] in ('"', "'"))

        if is_quoted_string(want) and is_quoted_string(got):
            want = want.strip()[1:-1]
            got = got.strip()[1:-1]
        elif is_quoted_unicode(want) and is_quoted_unicode(got):
            want = want.strip()[2:-1]
            got = got.strip()[2:-1]
        return want, got


class DocTestRunner(doctest.DocTestRunner):
    def __init__(self, *args, **kwargs):
        doctest.DocTestRunner.__init__(self, *args, **kwargs)
        self.optionflags = doctest.ELLIPSIS

    def report_unexpected_exception(self, out, test, example, exc_info):
        doctest.DocTestRunner.report_unexpected_exception(self, out, test,
                                                          example, exc_info)
        # Rollback, in case of database errors. Otherwise they'd have
        # side effects on other tests.
        for conn in connections:
            transaction.rollback_unless_managed(using=conn)

class TransactionTestCase(unittest.TestCase):
    def _pre_setup(self):
        """Performs any pre-test setup. This includes:

            * Flushing the database.
            * If the Test Case class has a 'fixtures' member, installing the
              named fixtures.
            * If the Test Case class has a 'urls' member, replace the
              ROOT_URLCONF with it.
            * Clearing the mail test outbox.
        """
        self._fixture_setup()
        mail.outbox = []

    def _fixture_setup(self):
        # If the test case has a multi_db=True flag, flush all databases.
        # Otherwise, just flush default.
        if getattr(self, 'multi_db', False):
            databases = connections
        else:
            databases = [DEFAULT_DB_ALIAS]
        for db in databases:
            call_command('flush', verbosity=0, interactive=False, database=db)

            if hasattr(self, 'fixtures'):
                # We have to use this slightly awkward syntax due to the fact
                # that we're using *args and **kwargs together.
                call_command('loaddata', *self.fixtures, **{'verbosity': 0, 'database': db})

    def __call__(self, result=None):
        """
        Wrapper around default __call__ method to perform common Django test
        set up. This means that user-defined Test Cases aren't required to
        include a call to super().setUp().
        """

        try:
            self._pre_setup()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            import sys
            result.addError(self, sys.exc_info())
            return
        super(TransactionTestCase, self).__call__(result)
        try:
            self._post_teardown()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            import sys
            result.addError(self, sys.exc_info())
            return

    def _post_teardown(self):
        """ Performs any post-test things. This includes:

            * Putting back the original ROOT_URLCONF if it was changed.
        """
        self._fixture_teardown()

    def _fixture_teardown(self):
        pass



def connections_support_transactions():
    """
    Returns True if all connections support transactions.  This is messy
    because 2.4 doesn't support any or all.
    """
    return all(conn.settings_dict['SUPPORTS_TRANSACTIONS']
        for conn in connections.all())

class TestCase(TransactionTestCase):
    """
    Does basically the same as TransactionTestCase, but surrounds every test
    with a transaction, monkey-patches the real transaction management routines to
    do nothing, and rollsback the test transaction at the end of the test. You have
    to use TransactionTestCase, if you need transaction management inside a test.
    """

    def _fixture_setup(self):
        if not connections_support_transactions():
            return super(TestCase, self)._fixture_setup()

        # If the test case has a multi_db=True flag, setup all databases.
        # Otherwise, just use default.
        if getattr(self, 'multi_db', False):
            databases = connections
        else:
            databases = [DEFAULT_DB_ALIAS]

        for db in databases:
            transaction.enter_transaction_management(using=db)
            transaction.managed(True, using=db)
        disable_transaction_methods()

        from django.contrib.sites.models import Site
        Site.objects.clear_cache()

        for db in databases:
            if hasattr(self, 'fixtures'):
                call_command('loaddata', *self.fixtures, **{
                                                            'verbosity': 0,
                                                            'commit': False,
                                                            'database': db
                                                            })

    def _fixture_teardown(self):
        if not connections_support_transactions():
            return super(TestCase, self)._fixture_teardown()

        # If the test case has a multi_db=True flag, teardown all databases.
        # Otherwise, just teardown default.
        if getattr(self, 'multi_db', False):
            databases = connections
        else:
            databases = [DEFAULT_DB_ALIAS]

        restore_transaction_methods()
        for db in databases:
            transaction.rollback(using=db)
            transaction.leave_transaction_management(using=db)

        for connection in connections.all():
            connection.close()
