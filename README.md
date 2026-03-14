# QA AI Agent Framework

An AI-driven web QA testing framework that reads test flows from Markdown files and executes them through an intelligent agent loop with Playwright browser automation.

## Architecture

```
┌─────────────────────────────────────────────────┐
│              QA Agent Orchestrator               │
├─────────────────────────────────────────────────┤
│                  Web QA Agent                    │
│  ┌─────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  Flow    │→ │   AI     │→ │  Guardrails   │  │
│  │  Parser  │  │  Planner │  │  (Validation) │  │
│  └─────────┘  └──────────┘  └───────┬───────┘  │
│                                      │          │
│  ┌──────────────┐  ┌────────────────▼────────┐  │
│  │  Page State   │← │     Executor           │  │
│  │  Extractor    │  │  (BrowserDriver)       │  │
│  └──────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browsers
playwright install chromium

# 4. Run smoke tests (deterministic, no AI)
pytest tests/test_smoke.py -m smoke -v

# 5. Run agent-driven tests (uses rule-based planner by default)
pytest tests/test_agent_flows.py -m agent -v

# 6. Run everything
pytest -v
```

## Flows

Test flows live in the `flows/` directory as Markdown files. Each file defines:

- **Target Application** — URL and description
- **Credentials** — Login credentials (if needed)
- **Steps** — Ordered list of actions to perform
- **Expected Outcome** — What success looks like
- **Error Scenarios** — Known failure conditions

### Example: `flows/Login.md`

```markdown
# Login Flow

## Target Application
- **URL**: https://example.com/login
- **Description**: Main app login page

## Credentials
- **Username**: testuser
- **Password**: testpass123

## Steps
1. Navigate to the login page
2. Enter the username into the "Username" field
3. Enter the password into the "Password" field
4. Click the "Sign In" button
5. Verify the page navigates to the dashboard

## Expected Outcome
- URL changes to contain "dashboard"
- Welcome message is displayed
```

### Creating New Flows

1. Create a new `.md` file in `flows/` (e.g., `flows/Checkout.md`)
2. Follow the section format above
3. Add a fixture in `conftest.py` if you want a named shortcut
4. Write a test in `tests/test_agent_flows.py` that uses it

## AI Planner Modes

### Rule-Based (Default, No API Key)
The framework ships with a keyword-matching planner that maps flow steps to browser actions. Works out of the box for straightforward flows.

### OpenAI-Backed (Set `OPENAI_API_KEY`)
For complex flows requiring reasoning, set your API key:
```bash
export OPENAI_API_KEY=sk-your-key-here
pytest tests/test_agent_flows.py -m agent -v
```

The framework auto-detects which planner to use.

## Project Structure

```
qa-ai-agent/
├── agent/
│   ├── flow_parser.py     # Reads .md flows into structured data
│   ├── planner.py         # AI/rule-based action planning
│   ├── executor.py        # Runs actions through browser
│   ├── guardrails.py      # Validates actions before execution
│   ├── runner.py          # Orchestrates the full agent loop
│   └── schemas.py         # Pydantic models (PageState, Actions)
├── browser/
│   ├── driver.py          # Playwright wrapper with helpers
│   └── extractors.py      # Page state extraction
├── flows/
│   ├── Login.md           # Login test flow
│   ├── Navigation.md      # Navigation test flow
│   └── FormValidation.md  # Form validation test flow
├── tests/
│   ├── test_smoke.py      # Deterministic browser tests
│   ├── test_flow_parser.py # Flow parsing tests
│   └── test_agent_flows.py # AI agent-driven tests
├── artifacts/             # Screenshots, logs, traces
├── conftest.py            # Shared pytest fixtures
├── pytest.ini             # Pytest configuration
├── requirements.txt       # Python dependencies
└── .env.example           # Environment variables template
```

## Execution Cycle

For each flow step, the agent:
1. **Extracts** structured page state (URL, labels, buttons, inputs, errors)
2. **Plans** the next action(s) via AI or rules
3. **Validates** through guardrails (target exists? visible? enabled?)
4. **Executes** via Playwright
5. **Records** the result and captures artifacts
6. **Repeats** until flow completes or max steps reached

## Configuration

Copy `.env.example` to `.env` and customize:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Enables LLM planner |
| `HEADLESS` | `true` | Run browser headless |
| `BROWSER` | `chromium` | Browser engine |
| `CAPTURE_SCREENSHOTS` | `true` | Save screenshots |
