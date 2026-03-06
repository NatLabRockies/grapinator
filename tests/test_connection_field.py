"""Unit tests for MyConnectionField.get_query (grapinator/schema.py).

All filter operators, AND/OR logic, sort direction, and the graphene-3.x
behaviour of passing None for unset fields are covered using an in-memory
SQLite database so no external DB is required.
"""

import os
os.environ.setdefault('GQLAPI_CRYPT_KEY', 'testkey')

import unittest
from unittest.mock import patch, MagicMock
import datetime

from . import context  # noqa: F401

from sqlalchemy import Column, Integer, String, Date, create_engine, event
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from graphene_sqlalchemy import SQLAlchemyConnectionField

from grapinator.schema import MyConnectionField


# ---------------------------------------------------------------------------
# In-memory SQLite database with test model
# ---------------------------------------------------------------------------

_TestBase = declarative_base()


class _Item(_TestBase):
    __tablename__ = 'items'
    id   = Column('id',   Integer, primary_key=True)
    name = Column('name', String)
    age  = Column('age',  Integer)
    dob  = Column('dob',  Date)


_engine = create_engine('sqlite:///:memory:')


@event.listens_for(_engine, 'connect')
def _register_regexp(dbapi_conn, _):
    """Register a Python REGEXP function so SQLite supports regexp_match()."""
    import re
    dbapi_conn.create_function(
        'REGEXP', 2,
        lambda pattern, value: bool(
            re.search(pattern, str(value)) if value is not None else False
        ),
    )


_TestBase.metadata.create_all(_engine)
_Session = scoped_session(sessionmaker(bind=_engine))
_Item.query = _Session.query_property()

# Seed data (inserted once for the entire module)
_session = _Session()
_session.add_all([
    _Item(id=1, name='Alice',          age=30, dob=datetime.date(1994, 1, 1)),
    _Item(id=2, name='Bob Smith',      age=25, dob=datetime.date(1999, 6, 15)),
    _Item(id=3, name='Charlie',        age=35, dob=datetime.date(1989, 3, 10)),
    _Item(id=4, name='alice lowercase', age=20, dob=datetime.date(2004, 12, 31)),
])
_session.commit()


def _base_query():
    """Return a fresh un-filtered SQLAlchemy query for _Item."""
    return _Session.query(_Item)


def _run(args):
    """Call MyConnectionField.get_query with the parent's get_query mocked to
    return a plain _Item query, then return the final filtered/sorted query."""
    with patch.object(SQLAlchemyConnectionField, 'get_query',
                      return_value=_base_query()):
        return MyConnectionField.get_query(_Item, MagicMock(), **args)


def _ids(query):
    return sorted(r.id for r in query.all())


# ---------------------------------------------------------------------------
# Filter operators
# ---------------------------------------------------------------------------

class TestContainsFilter(unittest.TestCase):
    """Default 'contains' match uses case-insensitive ilike('%value%')."""

    def test_default_matches_both_cases(self):
        """'alice' should match 'Alice' and 'alice lowercase' (ilike)."""
        result = _ids(_run({'name': 'alice'}))
        self.assertEqual(result, [1, 4])

    def test_explicit_contains_matches_substring(self):
        result = _ids(_run({'name': 'Smith', 'matches': 'contains'}))
        self.assertEqual(result, [2])

    def test_no_filter_when_value_is_none(self):
        """graphene 3.x sends None for every unset field — must be ignored."""
        result = _ids(_run({'name': None, 'age': None}))
        self.assertEqual(result, [1, 2, 3, 4])


class TestExactFilter(unittest.TestCase):

    def test_exact_is_case_sensitive(self):
        result = _ids(_run({'name': 'Alice', 'matches': 'exact'}))
        self.assertEqual(result, [1])

    def test_exact_no_match_wrong_case(self):
        result = _ids(_run({'name': 'alice', 'matches': 'exact'}))
        self.assertEqual(result, [])

    def test_eq_alias(self):
        result = _ids(_run({'name': 'Alice', 'matches': 'eq'}))
        self.assertEqual(result, [1])


class TestStartswithFilter(unittest.TestCase):

    def test_startswith_case_insensitive(self):
        result = _ids(_run({'name': 'ali', 'matches': 'startswith'}))
        self.assertEqual(result, [1, 4])

    def test_sw_alias(self):
        result = _ids(_run({'name': 'bob', 'matches': 'sw'}))
        self.assertEqual(result, [2])


class TestEndswithFilter(unittest.TestCase):

    def test_endswith_case_insensitive(self):
        result = _ids(_run({'name': 'smith', 'matches': 'endswith'}))
        self.assertEqual(result, [2])

    def test_ew_alias(self):
        result = _ids(_run({'name': 'lie', 'matches': 'ew'}))
        self.assertEqual(result, [3])  # 'Charlie' ends with 'lie'


class TestComparisonFilters(unittest.TestCase):

    def test_lt(self):
        result = _ids(_run({'age': 30, 'matches': 'lt'}))
        self.assertEqual(result, [2, 4])  # age 25, 20

    def test_lte(self):
        result = _ids(_run({'age': 30, 'matches': 'lte'}))
        self.assertEqual(result, [1, 2, 4])  # age 30, 25, 20

    def test_gt(self):
        result = _ids(_run({'age': 30, 'matches': 'gt'}))
        self.assertEqual(result, [3])  # age 35

    def test_gte(self):
        result = _ids(_run({'age': 30, 'matches': 'gte'}))
        self.assertEqual(result, [1, 3])  # age 30, 35

    def test_ne(self):
        result = _ids(_run({'age': 30, 'matches': 'ne'}))
        self.assertEqual(result, [2, 3, 4])  # age 25, 35, 20


class TestRegexFilter(unittest.TestCase):

    def test_regex_match(self):
        """'re' alias triggers regexp_match (REGEXP registered for SQLite)."""
        result = _ids(_run({'name': r'^Alice$', 'matches': 're'}))
        self.assertEqual(result, [1])

    def test_regex_alias_re(self):
        result = _ids(_run({'name': r'[Bb]ob', 'matches': 'regex'}))
        self.assertEqual(result, [2])


class TestListFilter(unittest.TestCase):

    def test_list_value_uses_in_(self):
        """A list value should use SQL IN (only when no special matches)."""
        result = _ids(_run({'name': ['Alice', 'Charlie']}))
        self.assertEqual(result, [1, 3])


class TestDateFilter(unittest.TestCase):

    def test_date_value_uses_gte_by_default(self):
        """datetime.date values default to >= (opinionated default)."""
        cutoff = datetime.date(1999, 1, 1)
        result = _ids(_run({'dob': cutoff}))
        # dob >= 1999-01-01: Bob (1999-06-15), alice lowercase (2004-12-31)
        self.assertEqual(result, [2, 4])


# ---------------------------------------------------------------------------
# AND / OR logic
# ---------------------------------------------------------------------------

class TestLogicOperators(unittest.TestCase):

    def test_and_logic_default(self):
        """Default logic is AND: both conditions must be satisfied."""
        result = _ids(_run({
            'name': 'Alice', 'age': 35, 'matches': 'exact', 'logic': 'and'
        }))
        # Alice has age=30, not 35 → no match
        self.assertEqual(result, [])

    def test_or_logic(self):
        """logic='or': either condition is sufficient."""
        result = _ids(_run({
            'name': 'Alice', 'age': 35, 'matches': 'exact', 'logic': 'or'
        }))
        # name=='Alice' → id=1  OR  age==35 → id=3
        self.assertEqual(result, [1, 3])

    def test_single_condition_and_vs_or_identical(self):
        """With only one filter condition, and/or produce the same result."""
        and_result = _ids(_run({'name': 'Alice', 'matches': 'exact', 'logic': 'and'}))
        or_result  = _ids(_run({'name': 'Alice', 'matches': 'exact', 'logic': 'or'}))
        self.assertEqual(and_result, or_result)


# ---------------------------------------------------------------------------
# Relay pagination args must be ignored
# ---------------------------------------------------------------------------

class TestRelayArgsSuppressed(unittest.TestCase):

    def test_relay_args_do_not_filter(self):
        """first/last/before/after are relay pagination args and must be
        skipped — they should not appear as field filters."""
        result = _ids(_run({'first': 2, 'last': None, 'before': None, 'after': None}))
        self.assertEqual(result, [1, 2, 3, 4])

    def test_none_relay_args_also_skipped(self):
        result = _ids(_run({'first': None, 'last': None}))
        self.assertEqual(result, [1, 2, 3, 4])


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

class TestSorting(unittest.TestCase):

    def test_sort_ascending_by_age(self):
        query = _run({'sort_by': 'age', 'sort_dir': 'asc'})
        ages = [r.age for r in query.all()]
        self.assertEqual(ages, sorted(ages))

    def test_sort_descending_by_age(self):
        query = _run({'sort_by': 'age', 'sort_dir': 'desc'})
        ages = [r.age for r in query.all()]
        self.assertEqual(ages, sorted(ages, reverse=True))

    def test_no_sort_when_sort_by_is_none(self):
        """sort_by=None must not raise an error and must return all rows."""
        result = _ids(_run({'sort_by': None}))
        self.assertEqual(result, [1, 2, 3, 4])

    def test_default_sort_dir_is_ascending(self):
        """Omitting sort_dir should default to ascending (not 'desc')."""
        query = _run({'sort_by': 'age'})
        ages = [r.age for r in query.all()]
        self.assertEqual(ages, sorted(ages))


# ---------------------------------------------------------------------------
# Custom args (matches/logic/sort_by/sort_dir) are NOT treated as field
# filters even if they happen to match a column name
# ---------------------------------------------------------------------------

class TestCustomArgsSuppressed(unittest.TestCase):

    def test_matches_arg_not_treated_as_field_filter(self):
        """'matches' controls comparator mode; it is not a column filter."""
        # If 'matches' were forwarded as a field filter it would error because
        # _Item has no 'matches' column.  Reaching this point is enough.
        result = _ids(_run({'matches': 'exact'}))
        self.assertEqual(result, [1, 2, 3, 4])

    def test_logic_arg_not_treated_as_field_filter(self):
        result = _ids(_run({'logic': 'or'}))
        self.assertEqual(result, [1, 2, 3, 4])

    def test_sort_by_arg_not_treated_as_field_filter(self):
        result = _ids(_run({'sort_by': 'age', 'sort_dir': 'asc'}))
        self.assertEqual(len(result), 4)


if __name__ == '__main__':
    unittest.main()
