"""Azure OpenAI function-calling agent that drives Q2E.

  pip install openai httpx
  export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com AZURE_OPENAI_API_KEY=... AZURE_OPENAI_DEPLOYMENT=<deployment>
  export Q2E_URL=http://127.0.0.1:8000      # or your Codespaces/Azure Container Apps URL
  python integrations/examples/azure_openai_agent.py "Is abdominal obesity associated with HbA1c at similar BMI?"
"""
import json
import os
import sys

from openai import AzureOpenAI

from _q2e_client import SYSTEM, call_tool, tool_specs

client = AzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], api_key=os.environ["AZURE_OPENAI_API_KEY"],
                     api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"))
deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
tools = tool_specs()
messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": " ".join(sys.argv[1:]) or "Prevalence of functional iron deficiency in US adults"}]

while True:
    resp = client.chat.completions.create(model=deployment, messages=messages, tools=tools)
    msg = resp.choices[0].message
    messages.append(msg.model_dump(exclude_none=True))
    if not msg.tool_calls:
        print(msg.content)
        user = input("\nYou (type 'approved' after approving in Q2E, or blank to quit): ").strip()
        if not user:
            break
        messages.append({"role": "user", "content": user})
        continue
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments or "{}")
        print(f"-> {tc.function.name}({args})")
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": call_tool(tc.function.name, args)})
