"""Opt-in Bedrock-intentproef; voert nooit route-tools uit."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from . import mcp_evals


def fingerprint(cases, system, tool_config):
    return hashlib.sha256(json.dumps([cases, system, tool_config], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def run(cases, client, model, *, system, tool_config, input_rate=None, output_rate=None, clock=time.monotonic):
    calls, measurements = [], []
    for case in cases:
        start = clock()
        try:
            response = client.converse(modelId=model, system=[{'text': system}],
                messages=[{'role':'user','content':[{'text':case['prompt']}]}],
                toolConfig=tool_config, inferenceConfig={'maxTokens':1400,'temperature':0.2})
            uses = [b['toolUse'] for b in response.get('output',{}).get('message',{}).get('content',[]) if 'toolUse' in b]
            # Score the first decision. Do not skip mistaken lookups to find a later match.
            call = uses[0] if uses else {}
            calls.append({'id':case['id'],'tool':call.get('name'),'arguments':call.get('input',{})})
            usage = response.get('usage',{})
            cost = None if input_rate is None or output_rate is None else (usage.get('inputTokens',0)*input_rate+usage.get('outputTokens',0)*output_rate)/1_000_000
            measurements.append({'id':case['id'],'seconds':round(clock()-start,3),'usage':usage,'estimated_usd':cost})
        except Exception as exc:
            measurements.append({'id':case['id'],'seconds':round(clock()-start,3),'error':type(exc).__name__})
    # request_id and profiel_naam are supplied by the hosted executor, not exposed to the model.
    hosted_cases = [{**c, 'expected_arguments':{k:v for k,v in c.get('expected_arguments',{}).items() if k not in ('request_id','profiel_naam')},
                     'required_arguments':[k for k in c.get('required_arguments',[]) if k not in ('request_id','profiel_naam')]} for c in cases]
    scored = mcp_evals.score(hosted_cases, calls)
    times = sorted(m['seconds'] for m in measurements)
    return {'model':model,'suite_sha256':fingerprint(cases,system,tool_config),
            'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'scope':'eerste toolkeuze; geen route-uitvoering of gesprekskwaliteit',
            'score':scored,'calls':calls,'measurements':measurements,
            'latency':{'p50_s':times[len(times)//2] if times else None,'p95_s':times[min(len(times)-1,int(len(times)*.95))] if times else None},
            'estimated_total_usd':sum(m.get('estimated_usd') or 0 for m in measurements) if input_rate is not None and output_rate is not None else None}


def command(args):
    import boto3
    from .aws_chat import SYSTEM_PROMPT, TOOL_CONFIG
    cases = mcp_evals.load(args.cases)
    if args.limit: cases = cases[:args.limit]
    client = boto3.Session(profile_name=args.aws_profile,region_name=args.aws_region).client('bedrock-runtime')
    result = run(cases,client,args.model,system=SYSTEM_PROMPT,tool_config=TOOL_CONFIG,input_rate=args.input_per_million,output_rate=args.output_per_million)
    if args.output: Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result
