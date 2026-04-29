import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

# Uses Bedrock via AWS SSO — model ARN comes from ANTHROPIC_DEFAULT_SONNET_MODEL in .env
# Run `aws sso login --profile prod-eng-ai-sandbox` if you get auth errors
client = anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"))
model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "us.anthropic.claude-sonnet-4-5-v1:0")

messages = [{"role": "user", "content": "explain what a CI pipeline does in 2 sentences."}]

response = client.messages.create(
    model=model,
    max_tokens=1024,
    system="You are a DevOps expert.",
    messages=messages
)
print(response.content[0].text)

# Key thing to internalize: The model has no memory between calls. You, the developer, are responsible for maintaining state.
