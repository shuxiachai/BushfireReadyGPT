
TIMEFRAME_OPTIONS = [
    "7-day action plan",
    "This-month preparedness plan",
    "Before the next bushfire season",
    "Long-term community resilience planning",
]

SCENARIO_OPTIONS = [
    "School bushfire preparedness",
    "Council community preparedness",
    "Community workshop material",
    "Household bushfire preparedness",
    "Aged care / care facility preparedness",
    "Farm / land management preparedness",
]

CONCERN_OPTIONS = [
    "Evacuation",
    "Candidate assembly points",
    "First aid training",
    "Roles and responsibilities",
    "Communication channels",
    "Smoke and health risk",
    "Road disruption",
    "Power / communications outage",
    "Official information sources",
    "Human review and approval",
]

EXAMPLE_CASES = {
    "Cairns Council pilot": {
        "location": "Cairns, Queensland",
        "audience": "Council community resilience officers, school safety leads, and local service partners",
        "scenario": "Council community preparedness",
        "timeframe": "This-month preparedness plan",
        "concerns": [
            "Evacuation",
            "Communication channels",
            "Smoke and health risk",
            "Roles and responsibilities",
            "Official information sources",
            "Human review and approval",
        ],
        "extra_context": (
            "Government pilot demonstration for Cairns. The report should be written as a draft evidence report "
            "for human review, using the selected ABS geography and clearly separating preparedness planning from "
            "live emergency instructions."
        ),
        "pilot_mode": "Council Community Preparedness",
        "organisation_name": "Cairns Council Community Preparedness Pilot",
        "reviewer_role": "Council disaster management / community resilience reviewer",
        "map_selection": {"state": "Queensland", "level": "SA4", "area_name": "Cairns"},
    },
    "Cairns school pilot": {
        "location": "Cairns, Queensland",
        "audience": "Students, teachers, school administrators and parents",
        "scenario": "School bushfire preparedness",
        "timeframe": "7-day action plan",
        "concerns": [
            "Evacuation",
            "Candidate assembly points",
            "First aid training",
            "Roles and responsibilities",
            "Official information sources",
        ],
        "extra_context": (
            "School pilot demonstration. The campus has not confirmed formal assembly points yet, so the report must "
            "distinguish candidate assembly point criteria from confirmed official arrangements."
        ),
        "pilot_mode": "School Preparedness",
        "organisation_name": "Cairns Campus Preparedness Pilot",
        "reviewer_role": "School safety / facilities reviewer",
        "map_selection": {"state": "Queensland", "level": "SA4", "area_name": "Cairns"},
    },
    "Remote Queensland community pilot": {
        "location": "Remote Queensland Community, Queensland",
        "audience": "Community residents, local service providers, volunteers and council officers",
        "scenario": "Community workshop material",
        "timeframe": "This-month preparedness plan",
        "concerns": [
            "Evacuation",
            "Road disruption",
            "Power / communications outage",
            "Communication channels",
            "Official information sources",
        ],
        "extra_context": (
            "Remote community pilot. The report should emphasise early planning, transport support, backup communications, "
            "neighbour checks and official source verification."
        ),
        "pilot_mode": "Community Workshop Material",
        "organisation_name": "Remote Queensland Community Preparedness Pilot",
        "reviewer_role": "Local resilience coordinator",
        "map_selection": {"state": "Queensland", "level": "SA4", "area_name": "Queensland - Outback"},
    },
}

DEMO_SCENARIO_PACK = [
    {
        "title": "Cairns Council Executive Demo",
        "example_case": "Cairns Council pilot",
        "audience_label": "Council / community resilience team",
        "demo_goal": "Show a council-style draft report with evidence tables, source register, review status and export package.",
        "talking_points": [
            "All outputs are draft planning support, not emergency directions.",
            "The selected SA4 geography is linked to ABS ASGS and LGA reference data.",
            "The pilot package includes report exports, audit JSON, data register and reviewer sign-off.",
        ],
        "expected_export": "Council-ready pilot package for stakeholder review.",
    },
    {
        "title": "Cairns School Campus Demo",
        "example_case": "Cairns school pilot",
        "audience_label": "School leadership / campus safety team",
        "demo_goal": "Show a school-focused preparedness report covering evacuation, candidate assembly points, first aid and staff roles.",
        "talking_points": [
            "Candidate assembly points are presented as criteria requiring local approval.",
            "Student, teacher, parent communication and first-aid readiness are foregrounded.",
            "The report remains a draft until reviewed by the responsible school or organisation.",
        ],
        "expected_export": "School pilot report with reviewer sign-off and evidence tables.",
    },
    {
        "title": "Remote Queensland Community Demo",
        "example_case": "Remote Queensland community pilot",
        "audience_label": "Remote community / local services / council officers",
        "demo_goal": "Show how the tool supports remote-area planning where roads, communications and service access are key constraints.",
        "talking_points": [
            "The selected geography uses Queensland - Outback as a demonstration area.",
            "The report emphasises early planning, backup communications and welfare checks.",
            "Official sources must still be checked for current warnings and local emergency instructions.",
        ],
        "expected_export": "Community workshop package for controlled pilot discussion.",
    },
]

DEMO_PRESENTATION_STEPS = [
    {
        "step": "1",
        "title": "Introduce the product",
        "say": (
            "BushfireReadyGPT is an Australia-focused preparedness planning assistant. "
            "It helps councils, schools and communities create draft bushfire preparedness reports "
            "while keeping official emergency decisions outside the tool."
        ),
        "show": [
            "Sidebar Safety Boundary",
            "Government pilot positioning",
            "Demo Mode / Sample Scenario Pack",
        ],
        "expected": "The audience understands this is a planning and review prototype, not an emergency command system.",
    },
    {
        "step": "2",
        "title": "Load or generate a demo",
        "say": (
            "The demo cards provide controlled scenarios. Load fills the form and map; Generate runs the "
            "multi-agent pipeline and creates a draft report."
        ),
        "show": [
            "Choose Cairns Council Executive Demo or Cairns School Campus Demo",
            "Click Generate for a complete example report",
        ],
        "expected": "A formal draft report appears in Latest Report Preview.",
    },
    {
        "step": "3",
        "title": "Explain the report structure",
        "say": (
            "The output is a structured English draft report covering selected geography, data limitations, "
            "local risk context, evacuation planning, candidate assembly point criteria, roles, communications, "
            "training, action planning and safety disclaimers."
        ),
        "show": [
            "Latest Report Preview",
            "Evidence Tables",
            "Human Review Sign-off section",
        ],
        "expected": "The audience sees that the tool produces a reviewable report rather than a loose chat answer.",
    },
    {
        "step": "4",
        "title": "Show the Evidence Trail",
        "say": (
            "The pipeline separates responsibilities across Profile, Australian Data, Community Vulnerability, "
            "Risk Context, Planner, Report and Quality agents."
        ),
        "show": [
            "Evidence Trail",
            "ABS ASGS Geography Reference",
            "Report Quality Check",
        ],
        "expected": "The audience sees explainable intermediate outputs and limitations.",
    },
    {
        "step": "5",
        "title": "Show map and data context",
        "say": (
            "The map is not a live fire map. It shows the selected ABS geography used for community context, "
            "and the selection affects the evidence used in the report."
        ),
        "show": [
            "Map and Data Table Analysis",
            "State / SA4 / SA3 / SA2 controls",
            "Aggregated profile table",
        ],
        "expected": "The selected geography is visibly tied to local evidence.",
    },
    {
        "step": "6",
        "title": "Show governance controls",
        "say": (
            "For a government or school pilot, AI output remains a draft until reviewed by the responsible organisation."
        ),
        "show": [
            "Data Register",
            "Human Review Checklist",
            "Reviewer Approval / Human Sign-off",
        ],
        "expected": "The audience sees review status, reviewer metadata and auditability.",
    },
    {
        "step": "7",
        "title": "Export the pilot package",
        "say": (
            "The export package bundles the report, PDF, DOCX, audit record, data register, reviewer sign-off "
            "and package manifest for stakeholder handover."
        ),
        "show": [
            "Pilot Export Package",
            "Download pilot export package",
            "Package manifest",
        ],
        "expected": "A zip package is ready for controlled pilot review.",
    },
    {
        "step": "8",
        "title": "Close with limitations and next step",
        "say": (
            "This is an MVP for preparedness planning and stakeholder feedback. The production path is live official "
            "data integration, legal review, security hardening, deployment and controlled user testing."
        ),
        "show": [
            "Safety Boundary",
            "Commercial readiness notes",
            "Official Information Sources",
        ],
        "expected": "The audience understands both the value and the current boundaries.",
    },
]

DEMO_EXPECTED_QUESTIONS = [
    {
        "question": "Does it provide live warnings?",
        "answer": "No. It is a preparedness planning tool. Live warnings, fire bans and evacuation orders must come from official emergency services.",
    },
    {
        "question": "Can it be used by government now?",
        "answer": "It can support a controlled pilot or demonstration. It is not yet ready for operational procurement without legal, data, security and deployment review.",
    },
    {
        "question": "Why multi-agent?",
        "answer": "The multi-agent structure makes the workflow explainable: input profiling, source selection, community context, risk matching, planning, reporting and quality checking are separated.",
    },
    {
        "question": "What should be built next for commercial readiness?",
        "answer": "Live official data status, stronger licence review, user accounts, approval workflows, deployment hardening and pilot feedback with real reviewers.",
    },
]

PROJECT_MATURITY_ASSESSMENT = {
    "current_stage": "Government-pilot MVP",
    "summary": (
        "The project is strong enough for internship demonstration, portfolio presentation and controlled "
        "stakeholder pilot discussion. It is not yet ready for operational emergency use, public deployment "
        "or government procurement."
    ),
    "scores": [
        {"area": "Product concept", "score": "8/10", "status": "Strong MVP", "note": "Clear Australia bushfire preparedness positioning and report workflow."},
        {"area": "User workflow", "score": "8/10", "status": "Strong MVP", "note": "Form, demo mode, evidence trail, reviewer sign-off and export package are in place."},
        {"area": "Data foundation", "score": "6/10", "status": "Pilot ready", "note": "ABS SA2/ASGS data is local and traceable; live warning data is not integrated."},
        {"area": "Multi-agent architecture", "score": "7/10", "status": "Pilot ready", "note": "Agent responsibilities are separated and visible, but testing and orchestration can be strengthened."},
        {"area": "Governance and audit", "score": "7/10", "status": "Pilot ready", "note": "Draft notices, evidence tables, sign-off and audit JSON exist; role-based approval is still missing."},
        {"area": "Commercial readiness", "score": "4/10", "status": "Not commercial yet", "note": "Needs licence review, legal boundary, deployment, privacy and user testing."},
        {"area": "Government procurement readiness", "score": "3/10", "status": "Early", "note": "Needs security, accessibility, procurement documentation and official data agreements."},
    ],
    "completed": [
        "Australia-specific bushfire preparedness positioning.",
        "Form-first report generation instead of generic chatbot flow.",
        "Local Ollama model service, no OpenAI API requirement.",
        "Local multi-agent analysis pipeline with visible Evidence Trail.",
        "ABS all-Australia SA2/SA3/SA4 map selection.",
        "ABS ASGS allocation and LGA 2025 reference data.",
        "Evidence Tables appended to generated reports.",
        "Reviewer Approval / Human Sign-off workflow.",
        "Markdown, PDF, DOCX, audit JSON and pilot export package.",
        "Demo Mode, Presentation Mode and sample scenario pack.",
    ],
    "gaps": [
        {
            "priority": "P0",
            "area": "Safety and legal boundary",
            "gap": "The app still needs formal legal review before commercial or government use.",
            "next_action": "Prepare a legal/disclaimer review brief and keep all outputs labelled as draft planning support.",
        },
        {
            "priority": "P0",
            "area": "Live official information",
            "gap": "The app now checks official source entry-point reachability, but does not ingest structured live warning feeds.",
            "next_action": "Keep the status panel non-decision, then decide whether official feed integration is legally and operationally appropriate.",
        },
        {
            "priority": "P1",
            "area": "Data licensing",
            "gap": "A licence register exists, but its assumptions still need commercial/legal review.",
            "next_action": "Convert licence assumptions into reviewed decisions for allowed use, attribution, caching and redistribution.",
        },
        {
            "priority": "P1",
            "area": "User testing",
            "gap": "The report format has not been validated by real school/council/community reviewers.",
            "next_action": "Run a controlled pilot with 3-5 reviewers using the pilot feedback form.",
        },
        {
            "priority": "P1",
            "area": "Authentication and approval",
            "gap": "Reviewer fields exist, but there are no user accounts, permissions or signed approval states.",
            "next_action": "Design roles for drafter, reviewer and admin; later add login and immutable approval records.",
        },
        {
            "priority": "P2",
            "area": "Deployment",
            "gap": "The app runs locally, but is not packaged for secure hosting.",
            "next_action": "Add Docker, environment profiles, health checks, logs and deployment notes.",
        },
        {
            "priority": "P2",
            "area": "Automated testing",
            "gap": "A deterministic test suite exists, but UI smoke tests and broader export/regression coverage are still limited.",
            "next_action": "Add UI smoke tests, scenario regression tests and stronger PDF/DOCX export checks.",
        },
    ],
    "roadmap": [
        {"phase": "Now", "goal": "Demo-ready portfolio MVP", "work": "Polish UI, keep demo scenarios reliable, use pilot export package for presentation."},
        {"phase": "Next 2 weeks", "goal": "Controlled pilot readiness", "work": "Tighten licence review, source-status boundaries, pilot feedback workflow and data-confidence labelling."},
        {"phase": "Next 1-2 months", "goal": "Stakeholder pilot", "work": "Test with school/council/community reviewers and refine report templates from feedback."},
        {"phase": "Commercial path", "goal": "Procurement-ready product concept", "work": "Add authentication, deployment hardening, privacy controls, legal review and data agreements."},
    ],
}
