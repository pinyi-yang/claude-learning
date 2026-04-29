# claude-learning

Personal journey learning Claude agent development — tool use, ReAct loops, multi-agent orchestration, and DevOps automation.

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install 'anthropic[bedrock]' python-dotenv
```

### 2. Configure credentials

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

---

#### Option A — Anthropic API key (direct)

Get a key from [console.anthropic.com](https://console.anthropic.com) and set it in `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Update any agent script to use the standard client:

```python
import anthropic
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
```

---

#### Option B — AWS Bedrock via SSO (recommended for AWS orgs)

Set your profile and region in `.env`:

```
AWS_PROFILE=your-sso-profile
AWS_REGION=us-west-2
ANTHROPIC_DEFAULT_SONNET_MODEL=<bedrock-inference-profile-arn>
ANTHROPIC_DEFAULT_OPUS_MODEL=<bedrock-inference-profile-arn>
ANTHROPIC_DEFAULT_HAIKU_MODEL=<bedrock-inference-profile-arn>
```

Log in before running agents:

```bash
aws sso login --profile your-sso-profile
```

Agent scripts use `AnthropicBedrock`:

```python
import os, anthropic
client = anthropic.AnthropicBedrock(aws_region=os.environ["AWS_REGION"])
model  = os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"]
```

---

### 3. Run an agent

```bash
source .venv/bin/activate
python agents/first_agent.py
```

## Project structure

```
agents/       one folder per agent project
tools/        reusable tool definitions
evals/        evaluation harnesses
docs/         reference docs and architecture notes
notes/        learning notes, gotchas, open questions
```
