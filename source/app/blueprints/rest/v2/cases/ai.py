#  IRIS Source Code
#
#  Tier-1 AI endpoints for cases. v0 is synchronous: a POST runs the LLM
#  inline and returns the result. The call typically takes 5-30s; if the
#  client times out, the artifact is still persisted and a follow-up GET
#  retrieves it.

from flask import Blueprint
from flask import request

from app.blueprints.access_controls import ac_api_requires
from app.blueprints.access_controls import ac_api_return_access_denied
from app.blueprints.rest.endpoints import response_api_error
from app.blueprints.rest.endpoints import response_api_not_found
from app.blueprints.rest.endpoints import response_api_success
from app.blueprints.rest.parsing import parse_boolean
from app.iris_engine.access_control.utils import ac_fast_check_current_user_has_case_access
from app.iris_engine.ai.case_summary import CaseSummaryError
from app.iris_engine.ai.case_summary import generate_case_summary
from app.iris_engine.ai.case_summary import get_cached_summary
from app.iris_engine.ai.attack_suggester import AttackSuggesterError
from app.iris_engine.ai.attack_suggester import suggest_attack_techniques
from app.iris_engine.ai.case_chat import CaseChatError
from app.iris_engine.ai.case_chat import ask_case
from app.iris_engine.ai.event_analysis import EventAnalysisError
from app.iris_engine.ai.event_analysis import generate_event_analysis
from app.iris_engine.ai.event_analysis import get_cached_event_analysis
from app.iris_engine.ai.evidence_type_suggester import EvidenceTypeSuggesterError
from app.iris_engine.ai.evidence_type_suggester import suggest_evidence_type
from app.iris_engine.ai.ioc_extractor import IocExtractorError
from app.iris_engine.ai.ioc_extractor import extract_iocs
from app.iris_engine.ai.timeline_analysis import TimelineAnalysisError
from app.iris_engine.ai.timeline_analysis import generate_timeline_analysis
from app.iris_engine.ai.timeline_analysis import get_cached_analysis as get_cached_timeline_analysis
from app.models.authorization import CaseAccessLevel
from app.models.models import CaseAiArtifact

case_ai_blueprint = Blueprint(
    'case_ai_rest_v2',
    __name__,
    url_prefix='/<int:case_identifier>/ai'
)


def _serialize_artifact(artifact: CaseAiArtifact) -> dict:
    return {
        'id': artifact.id,
        'case_id': artifact.case_id,
        'kind': artifact.kind,
        'prompt_id': artifact.prompt_id,
        'model': artifact.model,
        'input_hash': artifact.input_hash,
        'content': artifact.content,
        'confidence': artifact.confidence,
        'generated_at': artifact.generated_at.isoformat() if artifact.generated_at else None
    }


@case_ai_blueprint.get('/summary')
@ac_api_requires()
def get_case_summary(case_identifier):
    """Return the latest cached AI summary for the case, or 404 if none exists."""
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    artifact = get_cached_summary(case_identifier)
    if artifact is None:
        return response_api_not_found()
    return response_api_success(_serialize_artifact(artifact))


@case_ai_blueprint.post('/summary')
@ac_api_requires()
def generate_case_summary_endpoint(case_identifier):
    """Generate (or return cached) AI summary for the case.

    Query params:
      - force=true  bypass the cache and re-run the model
    """
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    force = request.args.get('force', False, type=parse_boolean) or False

    try:
        artifact = generate_case_summary(case_identifier, force=force)
    except CaseSummaryError as exc:
        return response_api_error(str(exc))

    return response_api_success(_serialize_artifact(artifact))


@case_ai_blueprint.get('/timeline-analysis')
@ac_api_requires()
def get_case_timeline_analysis(case_identifier):
    """Return the latest cached AI technical-analysis artifact, or 404."""
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    artifact = get_cached_timeline_analysis(case_identifier)
    if artifact is None:
        return response_api_not_found()
    return response_api_success(_serialize_artifact(artifact))


@case_ai_blueprint.post('/timeline-analysis')
@ac_api_requires()
def generate_case_timeline_analysis(case_identifier):
    """Generate (or return cached) AI technical analysis for the case.

    Uses the user's CaseAnalysisSystemPrompt — analyst-grade structured
    narrative covering what is evidenced vs suspected, gaps, priorities,
    and forensic actions. Heavier than the executive summary; runs against
    the full timeline + IOCs + assets.

    Query params:
      - force=true  bypass the cache and re-run the model
    """
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    force = request.args.get('force', False, type=parse_boolean) or False

    try:
        artifact = generate_timeline_analysis(case_identifier, force=force)
    except TimelineAnalysisError as exc:
        return response_api_error(str(exc))

    return response_api_success(_serialize_artifact(artifact))


@case_ai_blueprint.post('/ask')
@ac_api_requires()
def case_ai_ask(case_identifier):
    """Case-scoped chat assistant.

    Body (JSON):
      - question: str  (required)
      - history:  list of {role: 'user'|'assistant', content: str}  (optional, last 10 turns)

    Returns: {question, answer, model, usage} — not persisted server-side; the
    client owns the conversation state across turns.
    """
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    body = request.get_json(silent=True) or {}
    question = body.get('question')
    history = body.get('history') or []
    variant = body.get('variant')  # Optional: 'notes' / 'timeline' / 'iocs' / etc.

    if not isinstance(question, str) or not question.strip():
        return response_api_error("'question' is required and must be a non-empty string")

    try:
        result = ask_case(
            case_identifier,
            question,
            history=history,
            variant=variant if isinstance(variant, str) else None
        )
    except CaseChatError as exc:
        return response_api_error(str(exc))

    return response_api_success(result)


@case_ai_blueprint.get('/timeline/events/<int:event_id>/analysis')
@ac_api_requires()
def get_event_analysis(case_identifier, event_id):
    """Return the latest cached single-event AI analysis, or 404."""
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.read_only, CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    artifact = get_cached_event_analysis(case_identifier, event_id)
    if artifact is None:
        return response_api_not_found()
    return response_api_success(_serialize_artifact(artifact))


@case_ai_blueprint.post('/evidence-type-suggestion')
@ac_api_requires()
def suggest_evidence_type_endpoint(case_identifier):
    """Suggest a single EvidenceTypes catalog entry for a file being registered.

    Stateless / not cached. The file may not exist on the server yet (the
    Register evidence modal computes hash locally before any upload).
    Body fields are passed straight to the prompt.

    Body (JSON):
      - filename:    str  (required, the local file name as the analyst sees it)
      - size_bytes:  int  (optional, file size in bytes)
      - file_hash:   str  (optional, MD5 hex from the modal's compute step)
      - magic_hex:   str  (optional, first 4 KB of the file as a hex string)
      - description: str  (optional, analyst-typed description / context)

    Returns: {
      suggestion: {
        type_id: int,            # validated against EvidenceTypes catalog
        type_name: str,          # canonical from DB, not the model
        type_description: str,
        confidence: float,
        reason: str | null
      } | null,
      model: str,
      catalog_size: int
    }
    """
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    body = request.get_json(silent=True) or {}
    filename = body.get('filename') or ''
    if isinstance(filename, str):
        filename = filename.strip()
    else:
        filename = ''

    size_bytes = body.get('size_bytes')
    if size_bytes is not None and not isinstance(size_bytes, int):
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError):
            size_bytes = None

    file_hash = body.get('file_hash')
    magic_hex = body.get('magic_hex')
    description = body.get('description')

    if not filename and not (isinstance(magic_hex, str) and magic_hex.strip()):
        return response_api_error("'filename' or 'magic_hex' is required")

    try:
        result = suggest_evidence_type(
            filename=filename,
            size_bytes=size_bytes,
            file_hash=file_hash if isinstance(file_hash, str) else None,
            magic_hex=magic_hex if isinstance(magic_hex, str) else None,
            description=description if isinstance(description, str) else None,
        )
    except EvidenceTypeSuggesterError as exc:
        return response_api_error(str(exc))

    return response_api_success(result)


@case_ai_blueprint.post('/ioc-extraction')
@ac_api_requires()
def extract_iocs_endpoint(case_identifier):
    """Extract IOCs from free text (a note body, alert paste, etc.).

    Stateless / not cached. The caller (typically the note editor's ✨
    Extract IOCs button) is responsible for promoting accepted suggestions
    into real Ioc rows via the existing POST /api/v2/cases/{id}/iocs.

    Body (JSON):
      - text:        str  (required, the note body / free-text source)

    Returns: {
      iocs: [
        {value, type, type_id, tlp_id, tlp_name, confidence, reason,
         noise_flag, tags},
        ...  # 0..10 entries, sorted by confidence
      ],
      rationale: str | null,
      model:     str,
      default_tlp: {id, name} | null,
    }
    """
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    body = request.get_json(silent=True) or {}
    text = body.get('text')
    if not isinstance(text, str) or not text.strip():
        return response_api_error("'text' is required")

    try:
        result = extract_iocs(text, case_id=case_identifier)
    except IocExtractorError as exc:
        return response_api_error(str(exc))

    return response_api_success(result)


@case_ai_blueprint.post('/attack-suggestion')
@ac_api_requires()
def suggest_attack_techniques_endpoint(case_identifier):
    """Suggest MITRE ATT&CK techniques for an event-in-progress.

    Stateless / not cached. The event may not exist in the DB yet (analyst is
    in the create modal). Body fields are passed straight to the prompt.

    Body (JSON):
      - title:         str  (required if no description)
      - content:       str  (event description; required if no title)
      - source:        str  (optional, event source string)
      - category:      str  (optional, event category name)
      - existing_tags: str  (optional, comma-separated tags already on the event)

    Returns: {
      techniques: [{id, name, confidence, reason}, ...]  # 0-4 entries, sorted by confidence
      rationale:  str | null
      tags_string: str   # 'T1078, T1059.001' — ready to paste into event_tags
      model: str
    }
    """
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    body = request.get_json(silent=True) or {}
    title = body.get('title') or ''
    content = body.get('content')
    source = body.get('source')
    category = body.get('category')
    existing_tags = body.get('existing_tags')

    title = title.strip() if isinstance(title, str) else ''
    if not isinstance(content, str):
        content = None
    if not title and not (content or '').strip():
        return response_api_error("'title' or 'content' is required")

    try:
        result = suggest_attack_techniques(
            title=title,
            content=content,
            source=source if isinstance(source, str) else None,
            category=category if isinstance(category, str) else None,
            existing_tags=existing_tags if isinstance(existing_tags, str) else None,
        )
    except AttackSuggesterError as exc:
        return response_api_error(str(exc))

    return response_api_success(result)


@case_ai_blueprint.post('/timeline/events/<int:event_id>/analysis')
@ac_api_requires()
def generate_event_analysis_endpoint(case_identifier, event_id):
    """Generate (or return cached) AI analysis for a single timeline event.

    Query params:
      - force=true   bypass the cache and re-run the model
    """
    if not ac_fast_check_current_user_has_case_access(
        case_identifier, [CaseAccessLevel.full_access]
    ):
        return ac_api_return_access_denied(caseid=case_identifier)

    force = request.args.get('force', False, type=parse_boolean) or False

    try:
        artifact = generate_event_analysis(case_identifier, event_id, force=force)
    except EventAnalysisError as exc:
        return response_api_error(str(exc))

    return response_api_success(_serialize_artifact(artifact))
