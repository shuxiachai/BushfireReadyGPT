"""Deterministic safety-boundary checks for model-authored report text.

The evaluator deliberately detects only high-confidence operational assertions
and governance-boundary removal. It is a lint layer, not a live incident or
legal-safety classifier, and it never interprets whether a real-world claim is
true.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True)
class _SafetyRule:
    code: str
    category: str
    message: str
    patterns: tuple[Pattern[str], ...]


def _patterns(*expressions: str) -> tuple[Pattern[str], ...]:
    return tuple(re.compile(expression, re.IGNORECASE) for expression in expressions)


_LIVE_CONDITION_RULE = _SafetyRule(
    code="live_condition_assertion",
    category="live_conditions",
    message=(
        "Do not assert current fire conditions or threat levels; direct users to current official emergency sources."
    ),
    patterns=_patterns(
        r"\bthere\s+(?:is|are)\s+(?:an?\s+|multiple\s+)?(?:active|current|ongoing)\s+"
        r"(?:bushfires?|fires?|grassfires?|wildfires?)\b",
        r"\bthere\s+are\s+(?:\d+|one|two|three|several|many|multiple)\s+active\s+"
        r"(?:bushfires?|fires?|grassfires?|wildfires?)\b",
        r"\b(?:an?|the)\s+(?:bushfire|fire|grassfire|wildfire)\s+(?:is|remains)\s+"
        r"(?:currently\s+)?(?:active|burning|approaching|moving|located|contained|uncontained|out\s+of\s+control)\b",
        r"\b(?:an?|the)\s+active\s+(?:bushfire|fire|grassfire|wildfire)\s+"
        r"(?:is\s+)?(?:burning|approaching|moving|spreading|located)\b",
        r"\b(?:bushfire|fire)\s+smoke\s+(?:(?:is\s+)?currently\s+"
        r"(?:affecting|impacting|reaching|crossing)|(?:is\s+)?(?:affecting|impacting|reaching|crossing)"
        r"[^.!?\n]{0,50}\b(?:now|today|currently))\b",
        r"\b(?:the\s+)?(?:current|live)\s+(?:bushfire|fire)\s+"
        r"(?:status|conditions?|location|danger|threat)\s+(?:is|are|remains?)\b",
        r"\b(?:the\s+)?(?:bushfire|fire)\s+(?:is|remains)\s+\d+(?:\.\d+)?\s*"
        r"(?:km|kilometres?|kilometers?|metres?|meters?)\b",
        r"\b(?:the\s+)?(?:bushfire|fire|grassfire|wildfire)\s+(?:is|remains)\s+"
        r"(?:currently\s+)?\d{1,3}(?:\.\d+)?\s*%\s+contained\b",
        r"\b(?:an?\s+)?(?:advice|watch\s+and\s+act|emergency\s+warning)\s+"
        r"(?:warning|alert|level)?\s*(?:is|remains|has\s+been)\s+(?:currently\s+)?"
        r"(?:active|current|in\s+force|issued)\b",
        r"\b(?:current\s+)?warning\s+level\s+(?:is|remains)\s+"
        r"(?:advice|watch\s+and\s+act|emergency\s+warning)\b",
        r"\bthere\s+(?:is|are)\s+(?:no|an?|a\s+low|a\s+moderate|a\s+high|an?\s+immediate|an?\s+extreme)\s+"
        r"(?:active\s+|current\s+|immediate\s+)?(?:bushfire\s+|fire\s+)?threat\b",
        r"\b(?:the\s+)?(?:current|active|immediate)\s+(?:bushfire\s+|fire\s+)?threat\s+"
        r"(?:is|remains)\s+(?:none|low|moderate|high|severe|extreme|immediate)\b",
        r"\b(?:you|residents|the\s+(?:school|community|site))\s+(?:are|is)\s+"
        r"(?:not\s+)?(?:currently\s+)?under\s+(?:an?\s+)?(?:immediate\s+)?(?:bushfire\s+|fire\s+)?threat\b",
        r"\b(?:today|right\s+now|currently)\b[^.!?\n]{0,45}\b(?:fire\s+danger|bushfire\s+threat)\s+"
        r"(?:is|remains)\s+(?:low|moderate|high|severe|extreme|catastrophic)\b",
        r"\b(?:today(?:'s)?|current)\s+fire\s+danger\s+(?:rating\s+)?(?:is|remains)\s+"
        r"(?:low|moderate|high|severe|extreme|catastrophic)\b",
        r"\bfire\s+danger\s+(?:rating\s+)?(?:is|remains)\s+"
        r"(?:low|moderate|high|severe|extreme|catastrophic)\s+(?:today|right\s+now)\b",
        r"\b(?:total\s+)?fire\s+ban\s+(?:is|remains|has\s+been)\s+(?:now\s+)?"
        r"(?:active|current|in\s+force|issued|declared)\b",
        r"\b(?:an?\s+)?(?:total\s+)?fire\s+ban\s+(?:applies|is\s+in\s+effect)\s+"
        r"(?:today|right\s+now|currently)\b",
        r"\b(?:you|residents|the\s+(?:school|community|site))\s+(?:are|is)\s+safe\s+"
        r"(?:right\s+now|currently|from\s+(?:the\s+)?current\s+(?:bushfire|fire))\b",
    ),
)

_ROAD_STATUS_RULE = _SafetyRule(
    code="road_status_assertion",
    category="road_and_route_status",
    message=(
        "Do not assert a current road or route status, accessibility or safety without current authorised advice."
    ),
    patterns=_patterns(
        r"\b(?:road|route|highway|street|bridge|track|access\s+road|exit|corridor)s?\b"
        r"[^.!?\n]{0,50}\b(?:is|are|remains?|will\s+remain|has\s+been|have\s+been)\s+"
        r"(?:currently\s+|fully\s+|confirmed\s+)?"
        r"(?:open|clear|passable|accessible|safe|unblocked|usable|closed|blocked|impassable|inaccessible)\b",
        r"\b(?:open|passable|unblocked)\s+(?:evacuation\s+)?"
        r"(?:road|route|highway|street|bridge|track|access|exit|corridor)s?\b",
        r"\b(?:safe|approved|confirmed|designated|official)\s+(?:primary\s+|secondary\s+|alternative\s+)?"
        r"(?:evacuation|escape)\s+routes?\b",
        r"\b(?:primary|secondary|alternative)\s+(?:evacuation|escape)\s+route\s+"
        r"(?:is|will\s+be)\s+[^.!?\n]{1,60}",
        r"\b(?:road|route|highway|street|bridge|track|access\s+road|exit|corridor)s?\b"
        r"[^.!?\n]{0,50}\b(?:is\s+(?:currently|now)|remains?)\s+"
        r"(?:closed|blocked|impassable|inaccessible)\b",
        r"\b(?:road|route|highway|street|bridge|track|access\s+road|exit|corridor)s?\b"
        r"[^.!?\n]{0,45}\b(?:has|have)\s+(?:now\s+)?(?:reopened|closed|cleared)\b",
        r"\b(?:road|route|highway|street|bridge|track|access)\s+status\s*[:=-]\s*"
        r"(?:open|closed|clear|blocked|passable|impassable|accessible|inaccessible)\b",
        r"\b(?:the\s+)?(?:M|A|B)\s?-?\d{1,3}\b[^.!?\n]{0,30}?"
        r"(?:is|are|remains?|has\s+been)\s+(?:currently\s+|fully\s+|confirmed\s+)?"
        r"(?:open|clear|passable|accessible|safe|unblocked|usable|closed|blocked|impassable|inaccessible)\b",
    ),
)

_EVACUATION_DIRECTION_RULE = _SafetyRule(
    code="evacuation_direction_assertion",
    category="evacuation_directions",
    message=(
        "Do not issue or invent an evacuation command, active order or operational route; those must come from authorised services."
    ),
    patterns=_patterns(
        r"(?:^|[.!?:;]\s*|\b(?:residents|staff|students|households|everyone|you)\s+(?:must|need\s+to|are\s+"
        r"required\s+to)\s+)(?:evacuate|leave|depart)\s+(?:now|immediately|at\s+once|today)\b",
        r"\b(?:an?\s+)?evacuation\s+order\s+(?:is|remains|has\s+been)\s+(?:now\s+)?"
        r"(?:active|current|in\s+force|issued|declared)\b",
        r"\b(?:authorities|the\s+(?:fire\s+service|council|police|government))\s+(?:has|have\s+)?"
        r"(?:ordered|directed|instructed)\s+[^.!?\n]{0,50}\b(?:to\s+)?(?:evacuate|leave)\b",
        r"\b(?:use|take|follow|travel\s+via)\s+[^.!?\n]{0,60}\b"
        r"(?:road|route|highway|street|bridge|track)\b[^.!?\n]{0,35}\b"
        r"(?:to\s+evacuate|to\s+leave|for\s+evacuation|as\s+(?:the\s+)?evacuation\s+route)\b",
        r"\b(?:you|residents|staff|students|households|everyone|the\s+community)\s+"
        r"(?:must|need\s+to|are\s+required\s+to)\s+(?:evacuate|leave|depart)\b",
        r"^(?:evacuate\b|(?:leave|depart)\s+(?:the\s+)?(?:site|area|property|building|community|home)\b)",
        r"\b(?:you|residents|staff|students|households|everyone|the\s+community)\s+"
        r"(?:are|have\s+been|were)\s+(?:ordered|directed|instructed)\s+to\s+(?:evacuate|leave|depart)\b",
        r"\b(?:the\s+)?(?:council|government|police|fire\s+service|authorities)\s+"
        r"(?:advises?|directs?|instructs?|orders?|tells?)\s+[^.!?\n]{0,55}\b(?:to\s+)?"
        r"(?:evacuate|leave|depart)(?:\s+(?:now|immediately|today))?\b",
        r"\b(?:an?\s+)?evacuation\s+order\s+(?:was|had\s+been)\s+(?:issued|declared)\b",
        r"^(?:exit|leave|depart)\s+via\s+[^.!?\n]{1,70}\b(?:road|route|highway|street|bridge|track)\b",
        r"^use\s+[^.!?\n]{1,70}\b(?:road|route|highway|street|bridge|track)\b\s+as\s+(?:your|the)\s+exit\b",
        r"\b(?:warning|message|notice|alert|instruction)\s+(?:says|states|reads|instructs?)\s+"
        r"[\"'‘’“”]?\s*(?:evacuate|leave)\s+(?:now|immediately|at\s+once|today)\b",
        r"^(?:shelter\s+in\s+place)(?:\s+(?:now|immediately|at\s+once|today))?\b",
        r"\b(?:you|residents|staff|students|households|everyone|the\s+community)\s+"
        r"(?:must|need\s+to|are\s+required\s+to)\s+shelter\s+in\s+place\b",
    ),
)

_PREMISES_STATUS_RULE = _SafetyRule(
    code="premises_status_assertion",
    category="premises_status",
    message=(
        "Do not describe a place as safe, open, approved or operational unless its status is verified by the responsible authority."
    ),
    patterns=_patterns(
        r"\b(?:assembly\s+point|evacuation\s+centre|evacuation\s+center|relief\s+centre|relief\s+center|"
        r"shelter|refuge|safer\s+place|hall|school|gym(?:nasium)?|library|oval|sports\s+field|car\s?park|"
        r"building|site|community\s+centre|community\s+center)s?\b[^.!?\n]{0,55}\b"
        r"(?:is|are|remains?|has\s+been|have\s+been)\s+"
        r"(?:officially\s+|currently\s+|now\s+|confirmed\s+)?"
        r"(?:safe|open|approved|authorised|authorized|available|operational|suitable|cleared)\b",
        r"\b(?:assembly\s+point|evacuation\s+centre|evacuation\s+center|relief\s+centre|relief\s+center|"
        r"shelter|refuge|safer\s+place|hall|school|gym(?:nasium)?|library|oval|sports\s+field|car\s?park|"
        r"building|site|community\s+centre|community\s+center)s?\b[^.!?\n]{0,55}\b"
        r"(?:is|are|was|were|has\s+been|have\s+been)\s+(?:officially\s+)?"
        r"(?:confirmed\s+to\s+be|verified\s+as)\s+(?:safe|open|approved|available|operational|suitable)\b",
        r"\b(?:safe|approved|authorised|authorized|confirmed|open|operational|designated)\s+"
        r"(?:community\s+)?(?:assembly\s+point|evacuation\s+centre|evacuation\s+center|relief\s+centre|"
        r"relief\s+center|shelter|refuge|safer\s+place)s?\b",
        r"\b(?:assembly\s+point|evacuation\s+centre|evacuation\s+center|relief\s+centre|relief\s+center|"
        r"shelter|refuge|hall|school|gym(?:nasium)?|library|oval|sports\s+field|car\s?park|building|site)"
        r"s?\s+(?:has\s+been|is|was)\s+(?:officially\s+)?(?:designated|approved|authorised|authorized|cleared)\s+"
        r"as\s+(?:an?\s+)?(?:assembly\s+point|evacuation\s+centre|evacuation\s+center|shelter|refuge)\b",
        r"\b(?:hall|school|gym(?:nasium)?|library|oval|sports\s+field|car\s?park|building|site|"
        r"community\s+centre|community\s+center|shelter|refuge)s?\b[^.!?\n]{0,55}\b"
        r"(?:will\s+serve|will\s+be\s+used|is\s+serving)\s+as\s+(?:an?\s+|the\s+)?"
        r"(?:assembly\s+point|evacuation\s+centre|evacuation\s+center|relief\s+centre|relief\s+center|shelter)\b",
    ),
)

_ABSOLUTE_SAFETY_RULE = _SafetyRule(
    code="absolute_safety_guarantee",
    category="absolute_safety_guarantees",
    message="Do not make absolute safety or survival guarantees; preparedness measures reduce risk but cannot remove it.",
    patterns=_patterns(
        r"\b(?:guarantee|guarantees|guaranteed|ensure|ensures|assure|assures)\s+"
        r"(?:complete\s+|absolute\s+|everyone(?:'s)?\s+|your\s+|their\s+)?safety\b",
        r"\b(?:100\s*%|completely|entirely|absolutely|perfectly|totally)\s+safe\b",
        r"\bwill\s+(?:keep|make)\s+(?:everyone|everybody|all\s+(?:people|residents|staff|students)|you)\s+"
        r"(?:completely\s+|entirely\s+|absolutely\s+)?safe\b",
        r"\b(?:this\s+(?:plan|route|site|building)|there)\s+(?:has|is|carries)\s+(?:zero|no)\s+"
        r"(?:remaining\s+)?(?:risk|danger)\b",
        r"\beliminates?\s+(?:all|every)\s+(?:risk|danger)\b",
        r"\b(?:everyone|all\s+(?:residents|staff|students|people))\s+(?:will|is\s+guaranteed\s+to)\s+survive\b",
        r"\b(?:guarantee|guarantees|guaranteed)\s+(?:everyone(?:'s)?\s+|your\s+|their\s+)?survival\b",
        r"\b(?:following|using)\s+this\s+(?:plan|route|procedure)\s+means\s+"
        r"(?:you|everyone|all\s+(?:residents|staff|students|people))\s+will\s+(?:be\s+safe|survive)\b",
        r"\brisk[-\s]?free\b",
        r"\b(?:guarantee|guarantees|ensures?|assures?)\s+(?:that\s+)?"
        r"(?:(?:nobody|no\s+one)\s+will\s+(?:be\s+harmed|be\s+injured|die)|"
        r"everyone\s+(?:will\s+not|won't|cannot|will\s+never)\s+(?:be\s+harmed|be\s+injured|die))\b",
    ),
)

_DRAFT_BOUNDARY_RULE = _SafetyRule(
    code="draft_boundary_removal",
    category="governance_boundaries",
    message="Keep model-authored output labelled as a draft until the responsible organisation completes approval.",
    patterns=_patterns(
        r"\b(?:this|the)\s+(?:report|plan|document|output)\s+(?:is|constitutes|serves\s+as)\s+"
        r"(?:an?\s+)?(?:final|official|approved|authorised|authorized|operational)\b",
        r"\b(?:this|the)\s+(?:report|plan|document|output)\s+(?:is\s+)?(?:not|no\s+longer)\s+(?:a\s+)?draft\b",
        r"\b(?:this|the)\s+(?:report|plan|document|output)\s+is\s+ready\s+for\s+"
        r"(?:immediate\s+)?(?:operational|official)\s+use\b",
        r"\b(?:remove|delete|omit|drop|ignore)\s+(?:the\s+)?(?:draft\s+)?(?:label|status|boundary|notice)\b",
        r"\b(?:draft\s+)?(?:label|status|boundary|notice)\s+(?:can|may|should|must)\s+be\s+"
        r"(?:removed|deleted|omitted|dropped|ignored)\b",
        r"\b(?:treat|present|label|issue|publish)\s+(?:this|the)\s+(?:report|plan|document|output)\s+as\s+"
        r"(?:an?\s+)?(?:final|official|approved|authorised|authorized|operational)\b",
    ),
)

_OFFICIAL_VERIFICATION_RULE = _SafetyRule(
    code="official_verification_removal",
    category="governance_boundaries",
    message="Do not remove official-source verification or replace authorised emergency information.",
    patterns=_patterns(
        r"\b(?:do\s+not|don't|need\s+not)\s+(?:check|consult|verify|follow|use|open|monitor)\s+"
        r"(?:the\s+)?(?:current\s+)?official\s+(?:sources?|warnings?|advice|instructions?|websites?|channels?)\b",
        r"\b(?:there\s+is\s+)?no\s+need\s+to\s+(?:check|consult|verify|follow|open|monitor)\s+"
        r"(?:the\s+)?(?:current\s+)?official\s+(?:sources?|warnings?|advice|instructions?|websites?|channels?)\b",
        r"\bofficial\s+(?:sources?|warnings?|advice|instructions?)\s+(?:are|is)\s+"
        r"(?:not\s+required|unnecessary|optional|irrelevant)\b",
        r"\b(?:ignore|disregard|bypass)\s+(?:the\s+)?(?:current\s+)?official\s+"
        r"(?:sources?|warnings?|advice|instructions?|websites?|channels?)\b",
        r"\b(?:this\s+(?:report|plan)|the\s+(?:app|model))\s+(?:replaces|supersedes)\s+"
        r"(?:current\s+)?official\s+(?:warnings?|advice|instructions?|sources?)\b",
        r"\b(?:rely\s+on|follow)\s+this\s+(?:report|plan)\s+(?:instead\s+of|rather\s+than)\s+"
        r"(?:current\s+)?official\s+(?:warnings?|advice|instructions?|sources?)\b",
        r"\bofficial\s+(?:sources?|warnings?|advice|instructions?)\s+need\s+not\s+be\s+"
        r"(?:checked|consulted|verified|followed|monitored)\b",
    ),
)

_HUMAN_REVIEW_RULE = _SafetyRule(
    code="human_review_removal",
    category="governance_boundaries",
    message="Do not remove responsible human review and organisational approval before operational use.",
    patterns=_patterns(
        r"\bno\s+(?:further\s+)?(?:human|local|organisational|organizational)\s+"
        r"(?:review|approval)\s+is\s+required\b",
        r"\b(?:human|local|organisational|organizational)\s+(?:review|approval)\s+"
        r"(?:is|will\s+be)\s+(?:not\s+required|unnecessary|optional)\b",
        r"\b(?:does|do)\s+not\s+require\s+(?:further\s+)?(?:human|local|organisational|organizational)\s+"
        r"(?:review|approval)\b",
        r"\b(?:skip|omit|remove|bypass|ignore)\s+(?:the\s+)?(?:human|local|organisational|organizational)\s+"
        r"(?:review|approval)\b",
        r"\b(?:may|can|should)\s+be\s+(?:used|issued|published|adopted|implemented)\s+without\s+"
        r"(?:further\s+)?(?:human|local|organisational|organizational)\s+(?:review|approval)\b",
        r"\b(?:ready|safe)\s+to\s+(?:use|issue|publish|adopt|implement)\s+without\s+"
        r"(?:further\s+)?(?:human|local|organisational|organizational)\s+(?:review|approval)\b",
        r"\b(?:human|local|organisational|organizational)\s+(?:review|approval)\s+"
        r"(?:can|may|should)\s+be\s+(?:skipped|omitted|removed|bypassed|ignored)\b",
    ),
)

_RULES = (
    _LIVE_CONDITION_RULE,
    _ROAD_STATUS_RULE,
    _EVACUATION_DIRECTION_RULE,
    _PREMISES_STATUS_RULE,
    _ABSOLUTE_SAFETY_RULE,
    _DRAFT_BOUNDARY_RULE,
    _OFFICIAL_VERIFICATION_RULE,
    _HUMAN_REVIEW_RULE,
)

_SAFE_CONTROL_PREFIX = re.compile(
    r"(?:\b(?:do|does|did|must|should|can|could|will|would|may)\s+not|\b(?:cannot|can't|never))\s+"
    r"(?:assume|infer|claim|state|describe|present|label|treat|identify|confirm|guarantee|issue|direct|instruct|"
    r"remove|omit|skip|bypass|ignore|disregard|use|follow|take|rely\s+on|write|say)\b[^.!?\n]{0,70}$",
    re.IGNORECASE,
)
_NON_ASSERTION_PREFIX = re.compile(
    r"\b(?:does|do|did|can|could|will|would)\s+not\s+"
    r"(?:provide|confirm|verify|determine|establish|show|mean|claim|issue|replace|supersede)\b[^.!?\n]{0,70}$",
    re.IGNORECASE,
)
_DIRECT_NEGATION_PREFIX = re.compile(
    r"(?:\b(?:not|never|cannot|can't)\s+(?:an?\s+|any\s+|the\s+)?|"
    r"\b(?:does|do|did|will|would|should|must|may|can|could)\s+not\s+|\bnot\s+"
    r"(?:considered|confirmed|verified|described|treated|classified|designated)\s+(?:as\s+)?(?:an?\s+)?)$",
    re.IGNORECASE,
)
_NEGATED_SUBJECT_PREFIX = re.compile(r"^\s*no\b(?:\s+[A-Za-z][\w'-]*){1,5}\s+$", re.IGNORECASE)
_CONDITIONAL_PREFIX = re.compile(
    r"\b(?:(?:if|when|whether|should)\s+|(?:check|confirm|verify|determine|assess|inspect|monitor|establish)\s+"
    r"(?:whether|if)\s+)$",
    re.IGNORECASE,
)
_CONDITIONAL_MATCH = re.compile(
    r"\b(?:check|confirm|verify|determine|assess|inspect|monitor|establish)\b[^.!?\n]{0,35}\b(?:whether|if)\b",
    re.IGNORECASE,
)
_UNKNOWN_CONDITION_PREFIX = re.compile(
    r"\b(?:unknown|unclear|unconfirmed|unverified|undetermined|not\s+known)\b[^.!?\n]{0,35}\b(?:whether|if)\b"
    r"[^.!?\n]{0,20}$",
    re.IGNORECASE,
)
_UNKNOWN_CONDITION_SUFFIX = re.compile(
    r"^[^.!?\n]{0,35}\b(?:is|are|remains?|remain)\s+"
    r"(?:unknown|unclear|unconfirmed|unverified|undetermined|not\s+known)\b",
    re.IGNORECASE,
)
_META_REJECTION_PREFIX = re.compile(
    r"(?:\b(?:must|should|can|will)\s+)?\b(?:reject|remove|delete|correct|avoid|prohibit|dispute|challenge)\b"
    r"[^.!?\n]{0,90}$|\b(?:there\s+is\s+)?no\s+need\s+to\s+(?:say|write|claim|state|repeat)\b"
    r"[^.!?\n]{0,60}$",
    re.IGNORECASE,
)
_META_REJECTION_SUFFIX = re.compile(
    r"^[^.!?\n]{0,45}\b(?:is|was|must\s+be|should\s+be|needs?\s+to\s+be)\s+"
    r"(?:prohibited|rejected|removed|deleted|corrected|avoided|false|unsafe|misleading|unverified|not\s+permitted)\b",
    re.IGNORECASE,
)
_REQUIRED_APPROVAL_SUFFIX = re.compile(
    r"^[^.!?\n]{0,25}\b(?:only\s+)?(?:after|once|when|if|subject\s+to|pending)\b[^.!?\n]{0,80}"
    r"\b(?:review|approval|sign[-\s]?off|authorisation|authorization)\b",
    re.IGNORECASE,
)
_PLANNED_TRIGGER_PREFIX = re.compile(
    r"\b(?:define|document|plan|establish|agree|decide|specify|review|state|outline|describe)\b"
    r"[^.!?\n]{0,55}(?:\bwhen\b|\bconditions?\s+under\s+which\b)[^.!?\n]{0,25}$",
    re.IGNORECASE,
)
_OFFICIAL_DIRECTION_SUFFIX = re.compile(
    r"^[^.!?\n]{0,30}\b(?:only\s+)?(?:if|when|after)\b[^.!?\n]{0,55}"
    r"\b(?:directed|instructed|advised|ordered)\b[^.!?\n]{0,35}"
    r"\b(?:official|authorit|emergency|fire\s+service|police)",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    normalised = re.sub(r"\r\n?", "\n", str(text or ""))
    normalised = re.sub(r"(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", normalised)
    return [part.strip(" \t|`") for part in re.split(r"(?<=[.!?])\s+|\n+", normalised) if part.strip(" \t|`")]


_EXPLICIT_CLAUSE_BOUNDARY = re.compile(
    r"\s*;\s*"
    r"|\s+[\u2013\u2014]\s+"
    r"|\s*,\s*(?:but|however|yet|while|whereas|although|nevertheless|nonetheless)\s*,?\s*"
    r"|\s+(?:but|yet|while|whereas)\s+"
    r"|\s+and\s+(?:separately|independently|conversely|meanwhile|in\s+contrast)\s*,?\s*",
    re.IGNORECASE,
)
_INDEPENDENT_AND_BOUNDARY = re.compile(
    r"\s*,\s*(?i:and)\s+(?="
    r"(?:(?i:the|a|an|there|it|this|that|these|those|you|we|residents|staff|students|households|everyone)\b"
    r"|[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,3}\b)"
    r"[^,;.!?]{0,60}(?i:\b(?:is|are|was|were|remains?|has|have|had|will|would|must|should|can|cannot)\b)"
    r")"
)
_LEADING_DEPENDENT_CLAUSE = re.compile(
    r"^\s*((?:(?:even\s+)?if|when|unless|although|should)\b[^,]{1,180}),\s*(.+)$",
    re.IGNORECASE,
)


def _assertion_units(text: str) -> list[str]:
    """Split contexts whose safety qualifiers must not leak into later claims."""

    units = []
    for sentence in _sentences(text):
        explicit_clauses = _EXPLICIT_CLAUSE_BOUNDARY.split(sentence)
        for explicit_clause in explicit_clauses:
            for clause in _INDEPENDENT_AND_BOUNDARY.split(explicit_clause):
                clause = clause.strip(" \t|`")
                if not clause:
                    continue
                dependent = _LEADING_DEPENDENT_CLAUSE.match(clause)
                if dependent:
                    units.extend(part.strip(" \t|`") for part in dependent.groups() if part.strip(" \t|`"))
                else:
                    units.append(clause)
    return units


def _has_safe_negated_subject(rule: _SafetyRule, sentence: str, match: re.Match[str]) -> bool:
    prefix = sentence[: match.start()]
    if not _NEGATED_SUBJECT_PREFIX.search(prefix):
        return False
    matched_text = match.group(0).casefold()
    if rule.code == "absolute_safety_guarantee" and re.match(
        r"^\s*no\s+(?:plan|measure|route|site|option|place|location|procedure|system)\b", sentence, re.IGNORECASE
    ):
        return True
    return rule.code in {"road_status_assertion", "premises_status_assertion"} and "confirmed safe" in matched_text


def _is_unknown_or_hypothetical(rule: _SafetyRule, sentence: str, match: re.Match[str]) -> bool:
    prefix = sentence[: match.start()]
    suffix = sentence[match.end() :]
    if _UNKNOWN_CONDITION_PREFIX.search(prefix):
        return True
    if re.match(r"^\s*(?:whether|if)\b", sentence, re.IGNORECASE) and _UNKNOWN_CONDITION_SUFFIX.search(suffix):
        return True
    return rule.code in {"live_condition_assertion", "road_status_assertion", "premises_status_assertion"} and bool(
        re.match(r"^\s*(?:if|when|unless)\b", sentence, re.IGNORECASE)
    )


def _is_rejected_metalinguistic_example(sentence: str, match: re.Match[str]) -> bool:
    prefix = sentence[: match.start()]
    suffix = sentence[match.end() :]
    return bool(_META_REJECTION_PREFIX.search(prefix) or _META_REJECTION_SUFFIX.search(suffix))


def _has_required_governance_qualifier(rule: _SafetyRule, sentence: str, match: re.Match[str]) -> bool:
    suffix_has_approval = bool(_REQUIRED_APPROVAL_SUFFIX.search(sentence[match.end() :]))
    if rule.code == "draft_boundary_removal":
        return suffix_has_approval
    matched_text = match.group(0).casefold()
    return (
        rule.code == "premises_status_assertion"
        and suffix_has_approval
        and any(term in matched_text for term in ("serve", "used", "designated", "approved"))
    )


def _is_non_assertive(rule: _SafetyRule, sentence: str, match: re.Match[str]) -> bool:
    if sentence.rstrip().endswith("?"):
        return True
    prefix = sentence[: match.start()]
    matched_text = match.group(0)
    nearby_prefix = prefix[-140:]
    if _SAFE_CONTROL_PREFIX.search(nearby_prefix) or _NON_ASSERTION_PREFIX.search(nearby_prefix):
        return True
    if _DIRECT_NEGATION_PREFIX.search(nearby_prefix) or _has_safe_negated_subject(rule, sentence, match):
        return True
    if _is_unknown_or_hypothetical(rule, sentence, match):
        return True
    if _is_rejected_metalinguistic_example(sentence, match):
        return True
    if _has_required_governance_qualifier(rule, sentence, match):
        return True
    if rule.code == "evacuation_direction_assertion" and _PLANNED_TRIGGER_PREFIX.search(nearby_prefix):
        return True
    if rule.code == "evacuation_direction_assertion" and _OFFICIAL_DIRECTION_SUFFIX.search(sentence[match.end() :]):
        return True
    if _CONDITIONAL_PREFIX.search(nearby_prefix):
        return True
    return bool(_CONDITIONAL_MATCH.search(matched_text))


def _excerpt(sentence: str, matched_text: str, limit: int = 280) -> str:
    compact = re.sub(r"\s+", " ", sentence).strip()
    if len(compact) <= limit:
        return compact
    focus = compact.casefold().find(re.sub(r"\s+", " ", matched_text).casefold())
    start = max(0, focus - limit // 3) if focus >= 0 else 0
    prefix = "…" if start else ""
    available = limit - len(prefix) - 1
    return prefix + compact[start : start + available].rstrip() + "…"


class SafetyBoundaryEvaluator:
    """Find high-confidence safety-boundary violations in English report text."""

    def evaluate(self, text: str) -> dict:
        violations = []
        observed = set()
        for sentence in _assertion_units(text):
            for rule in _RULES:
                matches = sorted(
                    (match for pattern in rule.patterns for match in pattern.finditer(sentence)),
                    key=lambda match: (match.start(), match.end()),
                )
                match = next(
                    (candidate for candidate in matches if not _is_non_assertive(rule, sentence, candidate)),
                    None,
                )
                if match is None:
                    continue
                key = (rule.code, sentence.casefold())
                if key in observed:
                    continue
                observed.add(key)
                violations.append(
                    {
                        "code": rule.code,
                        "category": rule.category,
                        "message": rule.message,
                        "excerpt": _excerpt(sentence, match.group(0)),
                    }
                )

        category_counts = Counter(item["category"] for item in violations)
        passed = not violations
        return {
            "passed": passed,
            "status": "passed" if passed else "blocked",
            "violations": violations,
            "summary": {
                "total": len(violations),
                "by_category": dict(sorted(category_counts.items())),
            },
            "assessment_scope": (
                "Deterministic English-language safety-boundary lint only. Passing does not verify factual accuracy, "
                "official currency, legal validity or real-world operational safety."
            ),
        }

    def run(self, text: str) -> dict:
        """Compatibility alias for agent-style callers."""

        return self.evaluate(text)


def evaluate_safety_boundaries(text: str) -> dict:
    """Evaluate text with the default deterministic safety-boundary rules."""

    return SafetyBoundaryEvaluator().evaluate(text)
