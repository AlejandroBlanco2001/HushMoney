from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

import pytest


def _load_query_transactions() -> ModuleType:
    """Load the standalone summaries skill script by path (it is not a package)."""
    path = (
        pathlib.Path(__file__).parents[2]
        / 'skills'
        / 'summaries'
        / 'scripts'
        / 'query_transactions.py'
    )
    spec = importlib.util.spec_from_file_location('query_transactions', path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['query_transactions'] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def qt():
    return _load_query_transactions()


def _filters(bank=None, category=None, exclude_types=None):
    return {'bank': bank, 'category': category, 'exclude_types': exclude_types or []}


def test_no_filters_yields_nothing(qt):
    assert qt._filter_clauses(_filters()) == ([], [])


def test_bank_and_category_filters(qt):
    where, params = qt._filter_clauses(_filters(bank='bancolombia', category='food'))
    assert where == ['a.bank = ?', 't.category = ?']
    assert params == ['bancolombia', 'food']


def test_exclude_types_uses_one_placeholder_per_value(qt):
    where, params = qt._filter_clauses(_filters(exclude_types=['transfer_out', 'fee']))
    assert where == ['t.transaction_type NOT IN (?,?)']
    assert params == ['transfer_out', 'fee']


@pytest.mark.parametrize('bank', ["x'; DROP TABLE t;--", 'a OR 1=1'])
def test_user_values_are_never_interpolated_into_sql(qt, bank):
    """Injection-safety invariant: untrusted values reach only the params list,
    and each clause carries exactly one ? per param (no value in the SQL text)."""
    where, params = qt._filter_clauses(_filters(bank=bank, exclude_types=['a', 'b']))
    sql = ' '.join(where)
    assert sql.count('?') == len(params)
    assert bank not in sql
    assert bank in params
