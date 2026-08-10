#  IRIS Source Code
#
#  /api/v2/misp-tags — read-only autocomplete catalog for MISP taxonomy
#  + galaxy machine tags. Backed by the in-process catalog at
#  app.iris_engine.misp_tag_catalog (bundled snapshot under
#  source/app/resources/misp_{taxonomies,galaxies}/).
#
#  Used by:
#    - the suggestags-based tag inputs on the IOC / asset / task / case /
#      event modals (typeahead while the analyst types)
#    - the "MISP tag" picker in the soft-mapping admin page

from flask import Blueprint, request

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.rest.endpoints import response_api_success
from app.iris_engine import misp_tag_catalog


misp_tags_blueprint = Blueprint("misp_tags", __name__, url_prefix="/misp-tags")


# Cap responses so a misclick or stuck typeahead can't pull the entire
# 6,000+ record catalog down the wire.
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20


@misp_tags_blueprint.route("", methods=["GET"])
@ac_api_requires()
def search_misp_tags():
    """Return up to `limit` MISP tags matching `q`.

    Query params:
      q       free-text query. Empty -> first `limit` records (browse mode).
      limit   1..100, default 20.
      kinds   optional comma-separated subset of {taxonomy, galaxy}.
    """
    query = request.args.get("q", "", type=str)

    try:
        limit = int(request.args.get("limit", _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    limit = max(1, min(limit, _MAX_LIMIT))

    raw_kinds = (request.args.get("kinds") or "").strip()
    kinds: tuple[str, ...] | None = None
    if raw_kinds:
        wanted = {k.strip() for k in raw_kinds.split(",") if k.strip()}
        valid = wanted & {"taxonomy", "galaxy"}
        if valid:
            kinds = tuple(sorted(valid))

    matches = misp_tag_catalog.search(query, limit=limit, kinds=kinds)

    return response_api_success(
        data={
            "query": query,
            "limit": limit,
            "kinds": list(kinds) if kinds else ["taxonomy", "galaxy"],
            "total_in_catalog": misp_tag_catalog.catalog_size(),
            "matches": matches,
        }
    )
