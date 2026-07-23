"""BuildYourWolfpack game knowledge — the map the copilot coaches from.

Distilled from the live game source (frontend/src/data/wolfDenTasks.ts and the
routed flow). Kept as plain Python data + a prompt block so the LLM coach knows
exactly where the player is and what comes next instead of guessing from pixels.
"""

# Routed flow (hash routes in the SPA)
FLOW = [
    ("select-startup", "Auth gate + pick 1 of 3 startup ideas (or custom). Sets onboardingStep=1."),
    ("select-card", "Pick a class card: The Builder (labor), The Capital (finance), The Connector (sales)."),
    ("mint ID", "Profile form (name/city/skills/tagline). Sets onboardingStep=2, lands on /dashboard."),
    ("dashboard", "The game: OPS = 40-task Kanban (HUNT -> CHASE -> FEAST), NET = radar/comms, PACK = squad."),
]

# Kanban columns and what they mean for coaching
COLUMNS = {
    "HUNT": "backlog + todo — ideas waiting to be worked. Dragging to CHASE opens the commitment modal (IVP/pace/approach/assignee).",
    "CHASE": "doing — active work.",
    "FEAST": "done — completed. Completion awards IVP and places a tile on the 40-tile gameboard.",
}

# The 40-step mission, in order. (step, title, objective)
STEPS = [
    (1, "Ideation", "Generate ideas for new products/services"),
    (2, "Market Research", "Conduct research to determine viability"),
    (3, "Competitive Analysis", "Analyze competitors in the market"),
    (4, "Target Market", "Determine the specific audience"),
    (5, "Unique Selling Proposition (USP)", "Develop a USP"),
    (6, "Minimum Viable Product (MVP)", "Develop an MVP to test"),
    (7, "Prototype", "Develop a prototype"),
    (8, "Customer Feedback", "Gather feedback from potential customers"),
    (9, "Product/Service Refinement", "Refine based on feedback"),
    (10, "Branding", "Develop branding (Logo, Identity)"),
    (11, "Marketing Plan", "Develop a marketing strategy"),
    (12, "Pricing Strategy", "Develop a pricing model"),
    (13, "Launch Preparation", "Prepare for the launch"),
    (14, "Launch", "Execute the product/service launch"),
    (15, "Early Sales", "Generate initial sales"),
    (16, "Customer Retention", "Develop strategies to keep customers"),
    (17, "Referral Program", "Develop word-of-mouth marketing"),
    (18, "Expansion", "Expand into new markets"),
    (19, "Strategic Partnerships", "Develop partnerships"),
    (20, "Scaling", "Plan to scale the product/service"),
    (21, "Operations", "Develop operational processes"),
    (22, "Financial Planning", "Develop financial support plans"),
    (23, "Funding", "Secure funding"),
    (24, "Investor Relations", "Develop relationships with investors"),
    (25, "Growth", "Continue to grow the product/service"),
    (26, "Industry Analysis", "Analyze market trends"),
    (27, "Pivot", "Determine if a pivot is necessary"),
    (28, "Innovation", "Explore new innovations"),
    (29, "Intellectual Property", "Develop IP strategies"),
    (30, "Talent Acquisition", "Develop strategies for hiring"),
    (31, "Organizational Structure", "Develop the team structure"),
    (32, "Performance Metrics", "Develop metrics to measure success"),
    (33, "Data Analysis", "Analyze data for decisions"),
    (34, "Risk Management", "Develop risk strategies"),
    (35, "Legal Compliance", "Ensure legal compliance"),
    (36, "Social Responsibility", "Develop CSR strategies"),
    (37, "Crisis Management", "Develop crisis strategies"),
    (38, "Reputation Management", "Manage brand reputation"),
    (39, "Exit Strategy", "Develop an exit strategy"),
    (40, "Success", "Celebrate the success — The Feast"),
]

PHASES = [
    ("Ideation & Validation", range(1, 9)),
    ("Refinement & Launch", range(9, 18)),
    ("Expansion & Scale", range(18, 25)),
    ("Optimization & Exit", range(25, 41)),
]


def phase_of(step: int) -> str:
    for name, r in PHASES:
        if step in r:
            return name
    return "Unknown"


def prompt_block() -> str:
    """The game map as a compact system-prompt block for the coach LLM."""
    lines = [
        "GAME MAP — BuildYourWolfpack (you know this cold; coach from it):",
        "",
        "FLOW: " + " -> ".join(route for route, _ in FLOW),
    ]
    lines += [f"  - {route}: {desc}" for route, desc in FLOW]
    lines += [
        "",
        "KANBAN (the core loop): " + " | ".join(f"{k}: {v}" for k, v in COLUMNS.items()),
        "",
        "THE 40-STEP MISSION (in order; phases marked):",
    ]
    current_phase = None
    for num, title, objective in STEPS:
        ph = phase_of(num)
        if ph != current_phase:
            current_phase = ph
            lines.append(f"  [{ph}]")
        lines.append(f"    {num}. {title} — {objective}")
    lines += [
        "",
        "COACHING RULES:",
        "  - Name the step the player is on (or should be on) and the NEXT one — never generic advice.",
        "  - Cards left in HUNT too long: push them to CHASE (one committed task beats five ideas).",
        "  - A task in CHASE too long: help break it down or finish it — FEAST is the only score.",
        "  - Tie advice to the player's actual startup idea and class card when visible.",
    ]
    return "\n".join(lines)
