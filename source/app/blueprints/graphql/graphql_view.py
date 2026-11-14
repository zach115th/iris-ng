#  IRIS Source Code
#  Copyright (C) 2026 - iris-ng
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
"""The HTTP side of ``/graphql``: one POST, executed with graphql-core.

Until IRIS-NG-v2.14.0 the endpoint ran on the graphql-server 3.0.0b7 Flask
view. graphql-server 3.0.0 rewrote that view and changed what clients see
(200 instead of 400 for an invalid query, plain-text request errors, only
``application/json`` bodies), so IRIS answers from this small view instead,
which keeps the existing behaviour request for request:

* the body is read by its media type: ``application/json`` (a JSON object),
  ``application/graphql`` (the query text), a form post
  (``application/x-www-form-urlencoded`` or ``multipart/form-data``, the
  fields ``query`` / ``variables`` / ``operationName``); any other type reads
  as an empty body. A field missing from the body is taken from the query
  string;
* ``variables`` may be a JSON object or a string holding one;
* a JSON list (a batch) is refused, as is anything that is not an object;
* an answer whose errors all sit on a field (they carry a ``path``) is 200
  with ``data`` and ``errors``; a parse, validation or operation error (no
  ``path``) is 400 with ``errors`` only;
* a request the server cannot run (no query, invalid JSON, a batch) is 400
  with ``{"errors": [{"message": ...}]}``;
* the reply is compact JSON, indented when the query string has ``pretty``.

The resolvers see ``info.context == {"request": <the Flask request>}``.
Authentication and CSRF stay in ``graphql_route._check_authentication_wrapper``.
"""

import json
from collections.abc import MutableMapping

from flask import Response
from flask import request
from flask.views import View
from graphql import ExecutionResult
from graphql import GraphQLError
from graphql import GraphQLSchema
from graphql import execute
from graphql import parse
from graphql import specified_rules
from graphql import validate
from graphql import validate_schema


class GraphQLRequestError(Exception):
    """A request /graphql cannot run; answered as ``{"errors": [...]}``."""

    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def encode(data, pretty=False):
    if not pretty:
        return json.dumps(data, separators=(',', ':'))
    return json.dumps(data, indent=2, separators=(',', ': '))


def read_body():
    """The request body as the parameters it carries (a dict, or what the JSON held)."""
    media_type = request.mimetype
    if media_type == 'application/graphql':
        return {'query': request.data.decode('utf8')}

    if media_type == 'application/json':
        text = request.data.decode('utf8')
        try:
            return json.loads(text)
        except Exception:
            raise GraphQLRequestError(400, 'POST body sent invalid JSON.')

    if media_type in ('application/x-www-form-urlencoded', 'multipart/form-data'):
        return request.form

    return {}


def read_variables(variables):
    if variables and isinstance(variables, str):
        try:
            return json.loads(variables)
        except Exception:
            raise GraphQLRequestError(400, 'Variables are invalid JSON.')
    return variables


def read_params(body, query_string):
    """(query, variables, operation name): the body first, then the query string."""
    if isinstance(body, list):
        raise GraphQLRequestError(400, 'Batch GraphQL requests are not enabled.')
    if not isinstance(body, (dict, MutableMapping)):
        raise GraphQLRequestError(400, f'GraphQL params should be a dict. Received {body!r}.')

    query = body.get('query') or query_string.get('query')
    variables = body.get('variables') or query_string.get('variables')
    operation_name = body.get('operationName') or query_string.get('operationName')
    return query, read_variables(variables), operation_name


def _never_awaitable(_value):
    return False


def run_query(schema, query, variables, operation_name, context):
    if not query:
        raise GraphQLRequestError(400, 'Must provide query string.')
    if not isinstance(query, str):
        raise GraphQLRequestError(400, 'Unexpected query type.')

    schema_errors = validate_schema(schema)
    if schema_errors:
        return ExecutionResult(data=None, errors=schema_errors)

    try:
        document = parse(query)
    except GraphQLError as error:
        return ExecutionResult(data=None, errors=[error])
    except Exception as error:
        return ExecutionResult(data=None, errors=[GraphQLError(str(error), original_error=error)])

    validation_errors = validate(schema, document, rules=specified_rules)
    if validation_errors:
        return ExecutionResult(data=None, errors=validation_errors)

    return execute(
        schema,
        document,
        variable_values=variables,
        operation_name=operation_name,
        context_value=context,
        is_awaitable=_never_awaitable,
    )


def format_result(result):
    """(body, status) for one execution result."""
    if not result.errors:
        return {'data': result.data}, 200

    body = {'errors': [error.formatted for error in result.errors]}
    if any(not getattr(error, 'path', None) for error in result.errors):
        return body, 400

    body['data'] = result.data
    return body, 200


class GraphQLView(View):
    methods = ['POST']

    def __init__(self, schema):
        super().__init__()
        # A graphene Schema wraps the graphql-core one.
        if not isinstance(schema, GraphQLSchema):
            schema = getattr(schema, 'graphql_schema', None)
        if not isinstance(schema, GraphQLSchema):
            raise TypeError('A Schema is required to be provided to GraphQLView.')
        self.schema = schema

    def dispatch_request(self):
        try:
            body = read_body()
            pretty = request.args.get('pretty')
            query, variables, operation_name = read_params(body, request.args)
            result = run_query(self.schema, query, variables, operation_name, {'request': request})
            data, status = format_result(result)
            return Response(encode(data, pretty=pretty), status=status, content_type='application/json')

        except GraphQLRequestError as error:
            return Response(
                encode({'errors': [GraphQLError(error.message).formatted]}),
                status=error.status_code,
                content_type='application/json',
            )
