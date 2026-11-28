"""Text compared with a typed column keeps the column's type (iris-ng, the psycopg 3 move).

IRIS compares columns with values straight from requests in many places, and the legacy UI posts its forms with
serializeObject(), which sends every field as text: `AssetsType.asset_id == "3"`. SQLAlchemy types such a bound
value from the Python value, not the column (TypeEngine.coerce_compared_value), so "3" became a VARCHAR
parameter. Under psycopg2 that did not matter: the value went out as the literal '3' and PostgreSQL read it as the
column's type. The psycopg 3 dialect writes each parameter's type as a cast, `asset_id = $1::VARCHAR`, and
PostgreSQL has no integer = varchar operator, so the request failed.

keep_column_type_for_text() gives the integer, numeric and date / time types the rule SQLAlchemy already applies to
Uuid and binary columns: a str compared with (or combined with) the column takes the column's type, so the
parameter goes out as `$1::INTEGER` and PostgreSQL parses the text exactly as it parsed psycopg2's literal - "3"
matches 3, "abc" is refused as before. Under psycopg2 nothing changes on the wire (no casts are written). Values
of any other Python type keep SQLAlchemy's own behaviour. A boolean column is left out (see TYPES): bool_value()
is for a call site that compares one with request text.

Pure module (no Flask / ORM imports); app/__init__.py calls it once, before the engines exist.
"""
from sqlalchemy.sql import sqltypes

# the types whose literals PostgreSQL parses from text; their subclasses (BigInteger, SmallInteger, Double, the
# dialects' own) inherit the rule. Float is listed of its own: since SQLAlchemy 2.1 it shares NumericCommon with
# Numeric instead of deriving from it. Interval is listed too: it would hand a str to DateTime's rule. Boolean is
# NOT: its bind processor refuses a str before the driver sees it ("Not a boolean value"), so the rule would turn
# psycopg 3's database error into a client one - a call site converts text for a boolean column itself.
TYPES = (sqltypes.Integer, sqltypes.Numeric, sqltypes.Float, sqltypes.DateTime, sqltypes.Date, sqltypes.Time,
         sqltypes.Interval)

_MARK = "_iris_text_keeps_column_type"


def keep_column_type_for_text():
    """Install the rule on TYPES (once; a second call changes nothing)."""
    for cls in TYPES:
        current = cls.__dict__.get("coerce_compared_value")
        if current is not None and getattr(current, _MARK, False):
            continue
        inherited = cls.coerce_compared_value

        def coerce_compared_value(self, op, value, _inherited=inherited):
            if isinstance(value, str):
                return self
            return _inherited(self, op, value)

        setattr(coerce_compared_value, _MARK, True)
        cls.coerce_compared_value = coerce_compared_value


def id_value(value):
    """An id from a request as its integer column holds it - "3" -> 3, the legacy forms send ids as text - for the
    call sites that compare one (the schema validators, the alert filters). Anything that is not a whole number in
    text, and every non-str, comes back unchanged for the caller's own checks."""
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value)
    return value


_TRUE = frozenset(("true", "t", "yes", "y", "on", "1"))
_FALSE = frozenset(("false", "f", "no", "n", "off", "0"))


def bool_value(value):
    """Text for a boolean column as the bool PostgreSQL would have read from it ("false" -> False); anything
    else unchanged."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUE:
            return True
        if v in _FALSE:
            return False
    return value


def installed():
    """True when every type in TYPES carries the rule (a check for the boot and the suites)."""
    return all(getattr(cls.__dict__.get("coerce_compared_value"), _MARK, False) for cls in TYPES)
