# -*- coding: utf-8 -*-
# Unit and doctests for specific database backends.
import unittest
from django.db import backend, connection, DEFAULT_DB_ALIAS
from django.db.backends.signals import connection_created
from django.conf import settings

class Callproc(unittest.TestCase):

    def test_dbms_session(self):
        # If the backend is Oracle, test that we can call a standard
        # stored procedure through our cursor wrapper.
        if settings.DATABASES[DEFAULT_DB_ALIAS]['ENGINE'] == 'django.db.backends.oracle':
            convert_unicode = backend.convert_unicode
            cursor = connection.cursor()
            cursor.callproc(convert_unicode('DBMS_SESSION.SET_IDENTIFIER'),
                            [convert_unicode('_django_testing!'),])
            return True
        else:
            return True

class LongString(unittest.TestCase):

    def test_long_string(self):
        # If the backend is Oracle, test that we can save a text longer
        # than 4000 chars and read it properly
        if settings.DATABASES[DEFAULT_DB_ALIAS]['ENGINE'] == 'django.db.backends.oracle':
            c = connection.cursor()
            c.execute('CREATE TABLE ltext ("TEXT" NCLOB)')
            long_str = ''.join([unicode(x) for x in xrange(4000)])
            c.execute('INSERT INTO ltext VALUES (%s)',[long_str])
            c.execute('SELECT text FROM ltext')
            row = c.fetchone()
            c.execute('DROP TABLE ltext')
            self.assertEquals(long_str, row[0].read())

def connection_created_test(sender, **kwargs):
    print 'connection_created signal'

__test__ = {'API_TESTS': """
# Check Postgres version parsing
>>> from django.db.backends.postgresql import version as pg_version

>>> pg_version._parse_version("PostgreSQL 8.3.1 on i386-apple-darwin9.2.2, compiled by GCC i686-apple-darwin9-gcc-4.0.1 (GCC) 4.0.1 (Apple Inc. build 5478)")
(8, 3, 1)

>>> pg_version._parse_version("PostgreSQL 8.3.6")
(8, 3, 6)

>>> pg_version._parse_version("PostgreSQL 8.3")
(8, 3, None)

>>> pg_version._parse_version("EnterpriseDB 8.3")
(8, 3, None)

>>> pg_version._parse_version("PostgreSQL 8.3 beta4")
(8, 3, None)

>>> pg_version._parse_version("PostgreSQL 8.4beta1")
(8, 4, None)

"""}

# Unfortunately with sqlite3 the in-memory test database cannot be
# closed, and so it cannot be re-opened during testing, and so we
# sadly disable this test for now.
if settings.DATABASES[DEFAULT_DB_ALIAS]['ENGINE'] != 'django.db.backends.sqlite3':
    __test__['API_TESTS'] += """
>>> connection_created.connect(connection_created_test)
>>> connection.close() # Ensure the connection is closed
>>> cursor = connection.cursor()
connection_created signal
>>> connection_created.disconnect(connection_created_test)
>>> cursor = connection.cursor()
"""

if __name__ == '__main__':
    unittest.main()
