#  IRIS Source Code
#
#  iris-ng (2026-11-16, H8): the request body size limits.
#
#  `MAX_CONTENT_LENGTH` (configuration.py, IRIS_MAX_REQUEST_MB, default 32 MB) caps the body every route reads; a
#  larger one is refused with 413 when the route first touches it. The routes below take files or whole imports and
#  lift that cap for their own request - nginx keeps the caps it already has in front of them (100 MB, or none on
#  the template / case-file / datastore / working-timeline import locations). The hook runs before any view
#  decorator, so the per-route limit is set before anything reads the body.
#
#  A new route that takes an upload belongs in UPLOAD_RULES, written exactly as `url_map` shows it - the suite
#  `scripts/_test_request_order_and_size.py` fails on an entry that matches no rule and on a route that reads files
#  without an entry.

from flask import request

from app import app
from app.blueprints.responses import response_error

# Large enough to leave the limit to nginx and to the routes' own checks (a war-room datastore file, the 512 MB master
# CSV, a .iris-case archive).
UPLOAD_MAX_CONTENT_LENGTH = 1 << 40

UPLOAD_RULES = frozenset({
    # multipart uploads
    '/manage/templates/add',
    '/manage/cases/upload_files',
    '/manage/asset-type/add',
    '/manage/asset-type/update/<int:cur_id>',
    '/datastore/file/add/<int:cur_id>',
    '/datastore/file/add-interactive',
    '/datastore/file/update/<int:cur_id>',
    '/api/v2/cases/import',
    '/api/v2/customer-assets/import',
    '/api/v2/cases/<int:case_identifier>/working-timeline/import/hayabusa',
    '/api/v2/cases/<int:case_identifier>/working-timeline/import/eztools',
    '/api/v2/cases/<int:case_identifier>/working-timeline/import/master-csv',
    '/api/v2/war-rooms/<int:room_id>/datastore/files',
    '/api/v2/war-rooms/<int:room_id>/datastore/files/<int:file_id>/replace',
    '/api/v2/war-rooms/<int:room_id>/files',
    # CSV imports sent as JSON
    '/case/ioc/upload',
    '/case/assets/upload',
    '/case/timeline/events/csv_upload',
})


@app.before_request
def iris_upload_size_limit():
    rule = request.url_rule
    if rule is not None and rule.rule in UPLOAD_RULES:
        request.max_content_length = UPLOAD_MAX_CONTENT_LENGTH


@app.errorhandler(413)
def iris_request_too_large(e):
    limit = request.max_content_length
    if limit and limit < UPLOAD_MAX_CONTENT_LENGTH:
        msg = 'The request is too large: this route accepts at most %d MB' % (limit // (1024 * 1024))
    else:
        msg = 'The request is too large'
    return response_error(msg, status=413)
