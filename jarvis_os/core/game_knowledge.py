"""BuildYourWolfpack game knowledge — the map the copilot coaches from.

Distilled from the live game source (React SPA, cloned at /tmp/wtf):
  src/data/wolfDenTasks.ts        40 kanban task templates (deliverables, default approach)
  src/data/TaskData.ts            per-step base IVP values (100-10000)
  src/data/gameSteps.ts           BUILD(1-14)/MEASURE(15-28)/LEARN(29-40) sectors
  src/components/KanbanBoard.tsx  HUNT/CHASE/FEAST columns, commitment modal trigger
  src/components/CreateTaskModal.tsx  commitment modal fields (IVP/pace/approach/assignee)
  src/pages/CardSelection.tsx     class cards (Builder/Capital/Connector)
  src/utils/scoring.ts            IVP math, class multipliers, grind vs kill, Wolf Math
  src/hooks/useWolfPackLogic.ts   FEAST completion => "Kill Confirmed" +100 IVP
  src/components/GameboardCircle.tsx  40-tile circular gameboard
  src/pages/GameboardAndLeaderboard.tsx, Leaderboard.tsx  scoring/leaderboards
  src/pages/RadarPage.tsx, components/MyPackView.tsx, components/dashboard/Views.tsx
                                  NET radar/comms, PACK squad, Intel view
  src/components/GhostBar.tsx     EGO vs REALITY score bars
  src/pages/StartupSelection.tsx  auth + startup pick + custom idea

Kept as plain Python data + a prompt block so the LLM coach knows exactly where
the player is and what comes next instead of guessing from pixels.
"""

# Routed flow (hash routes in the SPA)
FLOW = [
    ("select-startup", "Auth gate (email/password) + pick 1 of 3 startup ideas, or custom (title/target market/price/channels). Sets onboardingStep=1 and the AlphaPitch (headline+strategy)."),  # StartupSelection.tsx:197-242
    ("select-card", "Pick a class card: The Builder (labor, 'I get things done'), The Capital (finance, 'I fund the vision'), The Connector (sales, 'I connect the dots'). Choice is PERMANENT."),  # CardSelection.tsx:100-104,221
    ("mint ID", "Profile form: wolf name, territory/city (used for location matching), skills (comma-separated), tagline. Sets onboardingStep=2, lands on /dashboard."),  # CardSelection.tsx:128-160,175-191
    ("dashboard", "The game: OPS = 40-task Kanban (HUNT -> CHASE -> FEAST, orbit or kanban view), NET = radar/comms (nearby players, coffee intel, chat), PACK = squad (scout talent, up to 12), INTEL = valuation/burn/Wolf-Math stats."),
]

# Kanban columns and what they mean for coaching
COLUMNS = {
    "HUNT": "backlog + todo — all 40 mission tasks start here, unassigned, default pace 'walk', default IVP 5 (wolfDenTasks.ts:392-396). Dragging a card to CHASE opens the commitment modal (KanbanBoard.tsx:107-115).",
    "CHASE": "doing — active, committed work. These tasks count toward the PROJECTED Wolf Math score but pay nothing yet (scoring.ts:41-49).",
    "FEAST": "done — completing a task is a 'Kill Confirmed': +100 IVP and +1 kill stat on the spot (useWolfPackLogic.ts:29-51), and it fills the step's tile on the 40-tile gameboard.",
}

# Game mechanics the coach must reason about. Sources cited per line.
MECHANICS = [
    "IVP = Intrinsic Value Points — the game's score/currency, shown as 'Valuation' on the INTEL view (Views.tsx:139-140). Player level = floor(IVP/1000)+1 (Views.tsx:217).",
    "Earning IVP: every task dragged to FEAST awards +100 IVP instantly (useWolfPackLogic.ts:32). Each step also has a base IVP value from 100 (Ideation) to 10000 (Success) in the preloaded data (TaskData.ts).",
    "Grind vs Kill: GRIND = routine low-IVP high-frequency work; KILL = milestone high-IVP work; a kill is worth 5x a grind in the scoring model (scoring.ts:4-9,29-32).",
    "Class multiplier: 1.5x IVP when a task matches your class — labor/Builder on build tasks (title matches code|dev|prototype|mvp), finance/Capital on fund tasks (finance|invest|pitch|money), sales/Connector on connect tasks (sales|call|meeting|network) (scoring.ts:18-26).",
    "Wolf Math: ACTUAL = sum of IVP on done tasks; PROJECTED = actual + IVP of in-progress (CHASE) tasks — CHASE is promise, FEAST is proof (scoring.ts:41-49). Ghost Bars show EGO (self-reported) vs REALITY (public) per role (GhostBar.tsx).",
    "Commitment modal (opens on HUNT->CHASE drag, KanbanBoard.tsx:107-115): fields are Mission Objective (title), Tactics (approach), Briefing (description), Value IVP (1-100), Pace (CreateTaskModal.tsx:165-208).",
    "Approach/Tactics options: build (internal), buy (acquire), partner (JV), outsource (delegate) (CreateTaskModal.tsx:16-21). Choosing outsource runs a network scan and shows recommended operatives with role, skill and match% you can assign (CreateTaskModal.tsx:73-86,237-267).",
    "Pace options: crawl (safe/low burn), walk (steady), run (high burn) (CreateTaskModal.tsx:196; profile setting Views.tsx:246-259). INTEL view shows Burn Rate HIGH/MED/LOW from pace (Views.tsx:147-149).",
    "Class cards: The Builder = labor (make things), The Capital = finance (fund things), The Connector = sales (sell/connect things) (CardSelection.tsx:100-104). The pick is permanent (CardSelection.tsx:221) — you cover the other two roles via PACK members and outsourcing.",
    "Gameboard: 40 tiles in a circle, one per mission step; tile colors by octant — steps 1-8 yellow, 9-16 orange, 17-24 red, 25-32 purple, 33-40 blue; a completed tile shows task title, completer and IVP; center shows n/40 with BUILD/MEASURE/LEARN sectors (GameboardCircle.tsx:136-184, gameSteps.ts:12-118).",
    "Sectors: steps 1-14 = BUILD, 15-28 = MEASURE, 29-40 = LEARN (gameSteps.ts). Kanban phase tabs: Phase 1 Intel & Setup, Phase 2 MVP Build, Phase 3 Traction, Phase 4 Scale (KanbanBoard.tsx:40-46).",
    "NET (Radar page): Perimeter Scan finds nearby players at 10/50/100 km (GPS), tap a player to open profile + secure-channel chat; Homebase Intel lists recommended coffee meetup spots; Wolfpack tab manages packs (RadarPage.tsx:132-289).",
    "PACK: your squad, max 12 members (Views.tsx:123). Scout talent filtered by role labor/finance/sales (Views.tsx:39-89). Packs have a name, mission, roster with an Alpha pack leader, and a secure group channel (MyPackView.tsx).",
    "Win/score: fill all 40 gameboard tiles; leaderboards rank players by Total IVP or by Tiles Filled (GameboardAndLeaderboard.tsx, Leaderboard.tsx). Success (step 40) is the 10000-IVP jackpot tile.",
]

# The 40-step mission, in order.
# (step, title, objective, deliverables, base_ivp, coaching tip)
# Deliverables + defaults: wolfDenTasks.ts. Base IVP: TaskData.ts (same order).
STEPS = [
    (1, "Ideation", "Generate ideas for new products/services", "Idea List + Selection Matrix", 100,
     "Pick the idea your class can execute — Builders should favor things they can build solo."),
    (2, "Market Research", "Conduct research to determine viability", "Market Research Report + SWOT Analysis", 150,
     "Get real market-size numbers; they feed your USP at step 5."),
    (3, "Competitive Analysis", "Analyze competitors in the market", "Competitor Matrix + Feature Comparison", 150,
     "Find the gap competitors ignore — that wedge becomes the USP."),
    (4, "Target Market", "Determine the specific audience", "User Personas + Target Audience Profile", 120,
     "One sharp persona, not five — step 8 needs real people to interview."),
    (5, "Unique Selling Proposition (USP)", "Develop a USP", "USP Statement + Value Proposition Canvas", 200,
     "One sentence a stranger can repeat; a paragraph is not a USP."),
    (6, "Minimum Viable Product (MVP)", "Develop an MVP to test", "MVP Specs + Core Feature List", 500,
     "Cut features until it hurts; Builder class gets 1.5x here — first big kill."),
    (7, "Prototype", "Develop a prototype", "Wireframes + Interactive Prototype", 300,
     "Clickable beats perfect — it only exists to feed step 8 feedback."),
    (8, "Customer Feedback", "Gather feedback from potential customers", "Feedback Report + Iteration Plan", 150,
     "Interview 5 real users; this closes Phase 1 — never launch on guesses."),
    (9, "Product/Service Refinement", "Refine based on feedback", "Refined Product Specs + Changelog", 200,
     "Fix what users complained about, not what's fun to build."),
    (10, "Branding", "Develop branding (Logo, Identity)", "Brand Guide + Logo Assets", 250,
     "Game default is BUY (wolfDenTasks.ts:105) — outsource it and keep building."),
    (11, "Marketing Plan", "Develop a marketing strategy", "Marketing Strategy Doc + Content Calendar", 300,
     "Pick 2 channels max, where your step-4 persona actually lives."),
    (12, "Pricing Strategy", "Develop a pricing model", "Pricing Model + Competitor Price Analysis", 150,
     "Price on value, not cost — decide high-end vs competitive explicitly."),
    (13, "Launch Preparation", "Prepare for the launch", "Launch Checklist + Press Kit", 400,
     "Checklist everything; Launch (14) is a 1000-IVP kill, no room for fumbles."),
    (14, "Launch", "Execute the product/service launch", "Live Product + Launch Announcement", 1000,
     "Biggest kill so far — run pace, whole pack assigned, announce everywhere."),
    (15, "Early Sales", "Generate initial sales", "Sales Report + First Customer List", 500,
     "10 real conversations beat 1000 impressions; Connector gets 1.5x on sales."),
    (16, "Customer Retention", "Develop strategies to keep customers", "Retention Strategy + Churn Analysis", 300,
     "Retention before expansion — don't scale a leaky bucket."),
    (17, "Referral Program", "Develop word-of-mouth marketing", "Referral Logic + Incentive Plan", 200,
     "Reward both referrer and referee; referrals compound step-15 sales."),
    (18, "Expansion", "Expand into new markets", "Expansion Plan + Market Analysis", 400,
     "Enter one new market only after retention (16) works."),
    (19, "Strategic Partnerships", "Develop partnerships", "Partnership Agreements + Partner List", 350,
     "Game default is PARTNER (wolfDenTasks.ts:188) — hunt allies on the NET radar."),
    (20, "Scaling", "Plan to scale the product/service", "Scaling Roadmap + Capacity Plan", 500,
     "Scale only what already works; check Wolf Math efficiency on INTEL first."),
    (21, "Operations", "Develop operational processes", "SOPs + Operational Flowchart", 250,
     "Write SOPs so pack members can pull tasks off your board."),
    (22, "Financial Planning", "Develop financial support plans", "Financial Model + Budget", 300,
     "Know your burn (INTEL view) before pitching at step 23."),
    (23, "Funding", "Secure funding", "Pitch Deck + Term Sheet", 1000,
     "1000-IVP kill; Capital class gets 1.5x on fund tasks — assign your finance wolf."),
    (24, "Investor Relations", "Develop relationships with investors", "Investor Updates + Cap Table", 400,
     "Monthly updates even when the news is bad — silence kills trust."),
    (25, "Growth", "Continue to grow the product/service", "Growth Metrics + Experiment Log", 500,
     "One growth experiment at a time, logged and measured."),
    (26, "Industry Analysis", "Analyze market trends", "Trend Report + Strategic Adjustments", 150,
     "Cheap crawl-pace IVP between big pushes; feeds the pivot decision."),
    (27, "Pivot", "Determine if a pivot is necessary", "Pivot Analysis + Decision Memo", 1000,
     "Decide with data from 25-26, not sunk cost; a right pivot pays like a launch."),
    (28, "Innovation", "Explore new innovations", "Innovation Pipeline + R&D Report", 300,
     "Park new ideas in HUNT — only one CHASE commitment at a time."),
    (29, "Intellectual Property", "Develop IP strategies", "IP Portfolio + Legal Filings", 500,
     "Game default is OUTSOURCE (wolfDenTasks.ts:280) — delegate legal, don't DIY."),
    (30, "Talent Acquisition", "Develop strategies for hiring", "Hiring Plan + Org Chart", 250,
     "Scout in PACK (cap 12) for the class you're missing."),
    (31, "Organizational Structure", "Develop the team structure", "Organizational Design + Role Descriptions", 200,
     "Every task needs one named owner — clear owners finish tasks."),
    (32, "Performance Metrics", "Develop metrics to measure success", "KPI Dashboard + Success Metrics", 150,
     "Pick 3 KPIs; INTEL already tracks your grind/kill efficiency per role."),
    (33, "Data Analysis", "Analyze data for decisions", "Data Warehouse + BI Reports", 200,
     "Analyze what step 32 measures — no dashboards without decisions."),
    (34, "Risk Management", "Develop risk strategies", "Risk Matrix + Mitigation Plan", 300,
     "Name your top 3 risks before the exit steps; buyers price them in."),
    (35, "Legal Compliance", "Ensure legal compliance", "Compliance Audit + Legal Docs", 400,
     "Game default OUTSOURCE (wolfDenTasks.ts:334) — a 400-IVP shield on valuation."),
    (36, "Social Responsibility", "Develop CSR strategies", "CSR Report + Impact Assessment", 200,
     "Authentic CSR feeds reputation (38); a checkbox campaign backfires."),
    (37, "Crisis Management", "Develop crisis strategies", "Crisis Playbook + Emergency Contacts", 500,
     "Write the playbook before you need it; run pace if a crisis is live."),
    (38, "Reputation Management", "Manage brand reputation", "Sentiment Analysis + PR Plan", 300,
     "Monitor sentiment weekly — reputation moves investor and exit steps."),
    (39, "Exit Strategy", "Develop an exit strategy", "Exit Plan + Valuation Model", 1000,
     "Your valuation IS your IVP — every FEAST tile raised it. Plan acquisition, IPO or succession."),
    (40, "Success", "Celebrate the success — The Feast", "The Feast + Wolfpack Legacy", 10000,
     "The 10000-IVP jackpot: fill all 40 tiles and top the leaderboard."),
]

PHASES = [
    ("Ideation & Validation", range(1, 9)),
    ("Refinement & Launch", range(9, 18)),
    ("Expansion & Scale", range(18, 25)),
    ("Optimization & Exit", range(25, 41)),
]

COACHING_RULES = [
    "Name the step the player is on (or should be on) and the NEXT one — never generic advice. One concrete move, not a menu.",
    "Cards rotting in HUNT: push exactly one into CHASE. The commitment modal is what makes a task real — one committed task beats five ideas.",
    "A task stuck in CHASE: break it down or finish it. Only FEAST pays — completion is a Kill Confirmed (+100 IVP, a gameboard tile).",
    "Match assignee class to task type for the 1.5x IVP multiplier: Builder on build (MVP, Prototype), Capital on fund (Funding, Pricing, Investor Relations), Connector on connect (Early Sales, Partnerships).",
    "Stage the big kills deliberately: Launch(14), Funding(23), Pivot(27), Exit(39) are 1000 IVP and Success(40) is 10000 — prep them, don't stumble into them.",
    "Respect the game's default approaches: Branding(10)=buy, Partnerships(19)/Funding(23)/Investor Relations(24)=partner, IP(29)/Legal(35)=outsource — use the outsource scan's match% to pick operatives.",
    "Pace is burn: run = HIGH burn on the INTEL view. Crawl/walk research and analysis tasks; save run for launch, sales and live crises.",
    "Solo wolves lose: use NET radar to recruit the two classes you didn't pick into your PACK (cap 12) before steps that need them — e.g. a Capital before Funding(23).",
    "Watch Wolf Math: if PROJECTED far exceeds ACTUAL, the player is over-committed in CHASE — finish before starting more.",
]

SCOPE_GUARD = (
    "SCOPE: You coach ONLY the BuildYourWolfpack game. If the player asks about anything "
    "unrelated (news, homework, other games, general chat), decline in one short line and "
    "steer back to their current step or next move in the game."
)


def phase_of(step: int) -> str:
    for name, r in PHASES:
        if step in r:
            return name
    return "Unknown"


def prompt_block() -> str:
    """The game map as a compact system-prompt block for the coach LLM."""
    lines = [
        "GAME MAP — BuildYourWolfpack (you know this cold; coach from it):",
        SCOPE_GUARD,
        "",
        "FLOW: " + " -> ".join(route for route, _ in FLOW),
    ]
    lines += [f"  - {route}: {desc}" for route, desc in FLOW]
    lines += [
        "",
        "KANBAN (the core loop): " + " | ".join(f"{k}: {v}" for k, v in COLUMNS.items()),
        "",
        "MECHANICS:",
    ]
    lines += [f"  - {m}" for m in MECHANICS]
    lines += [
        "",
        "THE 40-STEP MISSION (in order; phases marked; base IVP shown):",
    ]
    current_phase = None
    for num, title, objective, deliverables, ivp, tip in STEPS:
        ph = phase_of(num)
        if ph != current_phase:
            current_phase = ph
            lines.append(f"  [{ph}]")
        lines.append(f"    {num}. {title} — {objective} | deliver: {deliverables} | {ivp} IVP | TIP: {tip}")
    lines += [
        "",
        "COACHING RULES:",
    ]
    lines += [f"  - {r}" for r in COACHING_RULES]
    return "\n".join(lines)
