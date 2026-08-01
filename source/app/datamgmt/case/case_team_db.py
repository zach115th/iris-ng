#  iris-next: per-case analyst team helpers (datamgmt layer).
#
#  Manages two join tables:
#    case_analyst_link    — analysts assigned to a case (lead / analyst role)
#    case_required_skill  — skills this case requires (drives team suggestion)

from app import db
from app.models.authorization import CaseAnalystLink, CaseRequiredSkill, Skill, UserSkill, User


# ---------------------------------------------------------------------------
# Required skills
# ---------------------------------------------------------------------------

def get_case_required_skill_ids(case_id: int) -> list[int]:
    rows = (CaseRequiredSkill.query
            .filter(CaseRequiredSkill.case_id == case_id)
            .with_entities(CaseRequiredSkill.skill_id)
            .all())
    return [r.skill_id for r in rows]


# ---------------------------------------------------------------------------
# Skill derivation — rule-based mapping from case classification + tags
# ---------------------------------------------------------------------------

# substring → skill slugs (must match actual skill_slug values in the catalog).
# Classification: key is a substring of the lowercased classification name.
# All matching entries contribute (additive, not first-match).
_CLASSIFICATION_SKILL_MAP = {
    'ransomware':                   ['ransomware-response', 'disk-forensics', 'memory-forensics',
                                     'malware-static', 'malware-dynamic'],
    'malicious-code':               ['edr-analysis', 'malware-static', 'malware-dynamic',
                                     'disk-forensics', 'log-analysis'],
    'intrusion:privileged':         ['edr-analysis', 'disk-forensics', 'windows-forensics',
                                     'cti', 'attribution'],
    'intrusion:domain':             ['edr-analysis', 'disk-forensics', 'windows-forensics', 'cti'],
    'intrusion:':                   ['edr-analysis', 'disk-forensics', 'log-analysis'],
    'intrusion-attempts:exploit':   ['penetration-testing', 'edr-analysis', 'log-analysis'],
    'intrusion-attempts:':          ['edr-analysis', 'log-analysis'],
    'information-gathering:social': ['bec-investigation', 'cti'],
    'information-gathering:':       ['cti', 'edr-analysis', 'log-analysis'],
    'fraud:phishing':               ['bec-investigation', 'edr-analysis'],
    'fraud:':                       ['cti', 'bec-investigation', 'edr-analysis'],
    'availability:ddos':            ['network-forensics', 'log-analysis'],
    'availability:':                ['edr-analysis', 'network-forensics', 'log-analysis'],
    'information-content-security:': ['disk-forensics', 'log-analysis', 'edr-analysis'],
    'conformity:':                  ['compliance'],
    'vulnerable:':                  ['penetration-testing'],
    'virus':                        ['malware-static', 'malware-dynamic', 'edr-analysis'],
    'worm':                         ['malware-static', 'malware-dynamic', 'edr-analysis'],
    'dialer':                       ['malware-static', 'edr-analysis'],
    'rootkit':                      ['malware-static', 'malware-dynamic', 'disk-forensics'],
    'spyware':                      ['malware-static', 'malware-dynamic', 'edr-analysis'],
    'trojan':                       ['malware-static', 'malware-dynamic', 'edr-analysis'],
}

# Tag substring → skill slugs. All matching entries contribute.
_TAG_SKILL_MAP = {
    'ransomware':          ['ransomware-response', 'malware-static', 'malware-dynamic', 'disk-forensics'],
    'malware':             ['malware-static', 'malware-dynamic', 'edr-analysis'],
    'threat-actor':        ['cti', 'attribution'],
    'apt':                 ['cti', 'attribution', 'threat-hunting'],
    'phishing':            ['bec-investigation', 'edr-analysis'],
    'vulnerability':       ['penetration-testing'],
    'exploit':             ['penetration-testing', 'edr-analysis'],
    'lateral-movement':    ['edr-analysis', 'windows-forensics', 'cti', 'threat-hunting'],
    'command-and-control': ['cti', 'network-forensics', 'threat-hunting'],
    'exfiltration':        ['disk-forensics', 'network-forensics', 'cti'],
    'insider':             ['disk-forensics', 'compliance', 'log-analysis'],
    'supply-chain':        ['cti', 'malware-static', 'edr-analysis'],
    'mobile':              ['mobile-forensics'],
    'cloud':               ['cloud-security', 'cloud-forensics'],
    'aws':                 ['cloud-security', 'cloud-forensics'],
    'azure':               ['cloud-security', 'cloud-forensics'],
    'gcp':                 ['cloud-security', 'cloud-forensics'],
    'network':             ['network-forensics'],
    'ics':                 ['ot-ics-security'],
    'scada':               ['ot-ics-security'],
}


def _slugs_to_ids(slugs: list[str]) -> list[int]:
    """Resolve skill slugs to IDs; silently drop unrecognised slugs."""
    if not slugs:
        return []
    rows = Skill.query.filter(Skill.skill_slug.in_(slugs), Skill.is_active == True).all()
    return [r.id for r in rows]


def derive_required_skills_for_case(case_id: int) -> list[int]:
    """Return suggested required-skill IDs derived from the case's classification + tags.

    Rule-based — no LLM needed; classification names and MISP tags map cleanly
    to skill slugs. All matching rules contribute (additive, not first-match).
    Returns an empty list when neither classification nor tags give a signal.
    """
    from app.datamgmt.case.case_db import get_case  # local import to avoid circular
    case = get_case(case_id)
    if not case:
        return []

    found_slugs: list[str] = []
    seen: set[str] = set()

    def _add(slugs):
        for s in slugs:
            if s not in seen:
                seen.add(s)
                found_slugs.append(s)

    # 1. Classification-based mapping (all matching patterns contribute)
    cls_name = (case.classification.name or '').lower() if case.classification else ''
    for pattern, slugs in _CLASSIFICATION_SKILL_MAP.items():
        if pattern in cls_name:
            _add(slugs)

    # 2. Tag-based mapping (all matching patterns contribute)
    tag_text = ' '.join(t.tag_title.lower() for t in (case.tags or []))
    for pattern, slugs in _TAG_SKILL_MAP.items():
        if pattern in tag_text:
            _add(slugs)

    return _slugs_to_ids(found_slugs)


def set_case_required_skills(case_id: int, skill_ids: list[int]) -> list[int]:
    """Replace the case's required-skill set atomically (delete-all + bulk-insert)."""
    wanted = list({int(s) for s in (skill_ids or [])})
    if wanted:
        valid = {r.id for r in Skill.query.filter(Skill.id.in_(wanted)).with_entities(Skill.id).all()}
        wanted = [s for s in wanted if s in valid]

    CaseRequiredSkill.query.filter(CaseRequiredSkill.case_id == case_id).delete()
    for sid in wanted:
        db.session.add(CaseRequiredSkill(case_id=case_id, skill_id=sid))
    db.session.commit()
    return wanted


# ---------------------------------------------------------------------------
# Assigned analysts
# ---------------------------------------------------------------------------

def get_case_analysts(case_id: int) -> list[dict]:
    """Return analysts assigned to a case, with their role and skill IDs."""
    rows = (CaseAnalystLink.query
            .filter(CaseAnalystLink.case_id == case_id)
            .join(CaseAnalystLink.user)
            .all())
    result = []
    for link in rows:
        skill_ids = [r.skill_id for r in
                     UserSkill.query.filter(UserSkill.user_id == link.user_id)
                     .with_entities(UserSkill.skill_id).all()]
        result.append({
            'user_id': link.user_id,
            'user_name': link.user.name,
            'user_login': link.user.user,
            'role': link.role,
            'skill_ids': skill_ids,
        })
    return result


def set_case_analysts(case_id: int, assignments: list[dict]) -> list[dict]:
    """Replace the case's analyst team atomically.

    assignments: [{'user_id': int, 'role': 'lead'|'analyst'}, ...]
    Returns the saved assignment list.
    """
    CaseAnalystLink.query.filter(CaseAnalystLink.case_id == case_id).delete()
    seen_ids = set()
    for a in (assignments or []):
        uid = int(a.get('user_id', 0))
        if not uid or uid in seen_ids:
            continue
        role = a.get('role', 'analyst')
        if role not in ('lead', 'analyst'):
            role = 'analyst'
        db.session.add(CaseAnalystLink(case_id=case_id, user_id=uid, role=role))
        seen_ids.add(uid)
    db.session.commit()
    return get_case_analysts(case_id)


# ---------------------------------------------------------------------------
# Skill-coverage scorer (used by the suggestion endpoint)
# ---------------------------------------------------------------------------

def suggest_analysts_for_case(case_id: int, max_team_size: int = 5) -> list[dict]:
    """Greedy set-cover: pick analysts whose combined skills maximally cover
    the case's required skills, favouring diversity over depth.

    Excludes: the case owner, the case reviewer, and anyone already assigned.

    Returns a ranked list of analyst dicts, each with:
      user_id, user_name, user_login, skill_ids, coverage_count,
      coverage_fraction, role_suggestion ('lead'|'analyst')
    """
    from app.datamgmt.case.case_db import get_case  # local import to avoid circular
    required_ids = set(get_case_required_skill_ids(case_id))

    # Build exclusion set: owner + reviewer + already-assigned analysts
    exclude_ids: set[int] = set()
    case = get_case(case_id)
    if case:
        if case.owner_id:
            exclude_ids.add(case.owner_id)
        if case.reviewer_id:
            exclude_ids.add(case.reviewer_id)
    already_assigned = {r.user_id for r in
                        CaseAnalystLink.query
                        .filter(CaseAnalystLink.case_id == case_id)
                        .with_entities(CaseAnalystLink.user_id).all()}
    exclude_ids |= already_assigned

    # All active users with at least one enabled skill, minus excluded
    active_user_skills: dict[int, set[int]] = {}
    rows = (UserSkill.query
            .join(Skill, UserSkill.skill_id == Skill.id)
            .filter(Skill.is_active == True)
            .with_entities(UserSkill.user_id, UserSkill.skill_id)
            .all())
    for r in rows:
        if r.user_id not in exclude_ids:
            active_user_skills.setdefault(r.user_id, set()).add(r.skill_id)

    if not active_user_skills:
        return []

    # If no required skills specified, fall back to all analysts by skill count
    if not required_ids:
        candidates = [
            (uid, skills) for uid, skills in active_user_skills.items()
        ]
        candidates.sort(key=lambda x: len(x[1]), reverse=True)
        top = candidates[:max_team_size]
    else:
        # Greedy set cover
        covered: set[int] = set()
        selected: list[tuple[int, set[int]]] = []
        remaining_candidates = dict(active_user_skills)

        while len(selected) < max_team_size and remaining_candidates:
            # pick the analyst that covers the most uncovered required skills
            best_uid = max(
                remaining_candidates,
                key=lambda uid: len(remaining_candidates[uid] & required_ids - covered)
            )
            best_skills = remaining_candidates.pop(best_uid)
            gained = best_skills & required_ids - covered
            if not gained and selected:
                # no more coverage gain — stop
                break
            covered |= gained
            selected.append((best_uid, best_skills))

        top = selected

    # Fetch user names in one query
    uids = [uid for uid, _ in top]
    users = {u.id: u for u in User.query.filter(User.id.in_(uids)).all()}

    result = []
    for i, (uid, skills) in enumerate(top):
        u = users.get(uid)
        if not u:
            continue
        cov = len(skills & required_ids) if required_ids else 0
        result.append({
            'user_id': uid,
            'user_name': u.name,
            'user_login': u.user,
            'skill_ids': sorted(skills),
            'coverage_count': cov,
            'coverage_fraction': round(cov / len(required_ids), 2) if required_ids else 0.0,
            'role_suggestion': 'lead' if i == 0 else 'analyst',
        })

    return result
