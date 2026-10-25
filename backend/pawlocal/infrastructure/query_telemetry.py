"""Fail-closed SELECT templates for telemetry; never export SQL bind values."""

import re

# Code-owned model vocabulary. New schema identifiers require explicit review.
_IDENTIFIERS = frozenset(
    [
        "places",
        "place_facilities",
        "contributions",
        "favourites",
        "reports",
        "id",
        "name",
        "category",
        "area",
        "address",
        "description",
        "dog_access_rules",
        "average_rating",
        "source_updated_at",
        "is_published",
        "created_at",
        "updated_at",
        "place_id",
        "facility",
        "ordinal",
        "kind",
        "rating",
        "body",
        "contributor_subject",
        "user_subject",
        "target_type",
        "target_place_id",
        "target_contribution_id",
        "reporter_subject",
        "reason",
        "status",
    ]
)
_KEYWORDS = frozenset(
    [
        "SELECT",
        "FROM",
        "WHERE",
        "AND",
        "OR",
        "NOT",
        "IS",
        "NULL",
        "TRUE",
        "FALSE",
        "AS",
        "IN",
        "EXISTS",
        "JOIN",
        "INNER",
        "LEFT",
        "OUTER",
        "ON",
        "ORDER",
        "BY",
        "ASC",
        "DESC",
        "LIMIT",
        "OFFSET",
        "DISTINCT",
        "GROUP",
        "HAVING",
        "NULLS",
        "FIRST",
        "LAST",
        "LIKE",
        "ILIKE",
        "ESCAPE",
        "COUNT",
        "AVG",
        "LOWER",
        "UPPER",
        "COALESCE",
        "CAST",
        "UUID",
        "VARCHAR",
        "INTEGER",
        "FLOAT",
        "BOOLEAN",
        "TEXT",
        "BIGINT",
        "SMALLINT",
        "NUMERIC",
        "DOUBLE",
        "PRECISION",
    ]
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_BIND = re.compile(
    r"%\([A-Za-z_][A-Za-z0-9_]*\)s|%s|:[A-Za-z_][A-Za-z0-9_]*|\$[1-9][0-9]*|__\[POSTCOMPILE_[A-Za-z_][A-Za-z0-9_]*\]"
)
_ALIAS = re.compile(r"([a-z_]+)_[0-9]{1,3}\Z")


def _identifier(value):
    if value in _IDENTIFIERS:
        return value
    if value.upper() in _KEYWORDS:
        return value.upper()
    if value in {"subquery_alias", "count_alias", "avg_alias"}:
        return value
    if value.endswith("_alias") and value[:-6] in _IDENTIFIERS:
        return value
    match = _ALIAS.fullmatch(value)
    if match:
        base = match[1]
        if base == "anon":
            return "subquery_alias"
        if base in _IDENTIFIERS or base in {"count", "avg"}:
            return base + "_alias"
    return None


def safe_query_template(statement):
    """Return bounded canonical SQL with placeholders, or omit unsupported SQL.

    This lexical allowlist is deliberately narrower than SQL. It never formats
    parameters, preserves string/numeric literals, or trusts SQL-looking span
    attributes. Comments, unknown identifiers and unsupported syntax fail closed.
    """
    if not isinstance(statement, str) or not statement or len(statement) > 16384:
        return None
    if any(ord(char) < 32 and char not in "\r\n\t" for char in statement):
        return None
    tokens, index, depth = [], 0, 0
    while index < len(statement):
        char = statement[index]
        if char.isspace():
            index += 1
            continue
        if statement.startswith(("--", "/*", "*/"), index) or char == ";":
            return None
        # PostgreSQL E strings allow backslash escapes; ordinary strings use ''.
        escaped = char in "eE" and statement[index : index + 2].lower() == "e'"
        if char == "'" or escaped:
            index += 2 if escaped else 1
            while index < len(statement):
                if escaped and statement[index] == "\\":
                    index += 2
                elif statement[index] == "'":
                    if statement[index : index + 2] == "''":
                        index += 2
                    else:
                        index += 1
                        break
                else:
                    index += 1
            else:
                return None
            tokens.append("?")
            continue
        if char == '"':
            index += 1
            identifier = []
            while index < len(statement):
                if statement[index] == '"':
                    if statement[index : index + 2] == '""':
                        identifier.append('"')
                        index += 2
                    else:
                        index += 1
                        break
                else:
                    identifier.append(statement[index])
                    index += 1
            else:
                return None
            token = _identifier("".join(identifier))
            if token is None:
                return None
            tokens.append(token)
            continue
        if statement.startswith("::", index):
            tokens.append("::")
            index += 2
            continue
        bind = _BIND.match(statement, index)
        if bind:
            tokens.append("?")
            index = bind.end()
            continue
        number = _NUMBER.match(statement, index)
        if number:
            tokens.append("?")
            index = number.end()
            continue
        word = _WORD.match(statement, index)
        if word:
            token = _identifier(word[0])
            if token is None:
                return None
            tokens.append(token)
            index = word.end()
            continue
        if statement[index : index + 2] in {"<=", ">=", "!=", "<>", "||"}:
            tokens.append(statement[index : index + 2])
            index += 2
            continue
        if char in "(),.=<>!*+-/%?|":
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    return None
            tokens.append(char)
            index += 1
            continue
        return None
    if not tokens or tokens[0] != "SELECT" or depth:
        return None
    result = " ".join(tokens)
    return result if len(result) <= 4096 else None
