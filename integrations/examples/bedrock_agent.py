"""AWS Bedrock (Converse API) tool-use agent that drives Q2E.

  pip install boto3 httpx
  export AWS_REGION=us-east-1 BEDROCK_MODEL_ID=<a tool-use capable model id enabled in your account>
  export Q2E_URL=http://127.0.0.1:8000
  python integrations/examples/bedrock_agent.py "Is sodium intake associated with hypertension in US adults?"
"""
import json
import os
import sys

import boto3

from _q2e_client import SYSTEM, call_tool, tool_specs

brt = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
model = os.environ["BEDROCK_MODEL_ID"]
tool_config = {"tools": [{"toolSpec": {"name": t["function"]["name"], "description": t["function"]["description"],
                                       "inputSchema": {"json": t["function"]["parameters"]}}} for t in tool_specs()]}
messages = [{"role": "user", "content": [{"text": " ".join(sys.argv[1:]) or "Prevalence of functional iron deficiency in US adults"}]}]

while True:
    out = brt.converse(modelId=model, system=[{"text": SYSTEM}], messages=messages, toolConfig=tool_config)
    msg = out["output"]["message"]
    messages.append(msg)
    uses = [c["toolUse"] for c in msg["content"] if "toolUse" in c]
    if not uses:
        print("".join(c.get("text", "") for c in msg["content"]))
        user = input("\nYou (type 'approved' after approving in Q2E, or blank to quit): ").strip()
        if not user:
            break
        messages.append({"role": "user", "content": [{"text": user}]})
        continue
    results = []
    for u in uses:
        print(f"-> {u['name']}({u['input']})")
        results.append({"toolResult": {"toolUseId": u["toolUseId"], "content": [{"text": call_tool(u["name"], u["input"])}]}})
    messages.append({"role": "user", "content": results})
