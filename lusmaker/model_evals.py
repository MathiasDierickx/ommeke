"""Opt-in Bedrock-intentproef; voert nooit route-tools uit."""
from __future__ import annotations
import hashlib
import json
import math
import time
from pathlib import Path
from . import mcp_evals
from .chat_contracts import validate_arguments


def fingerprint(cases, system, tool_config):
    return hashlib.sha256(json.dumps([cases, system, tool_config], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def score(cases, calls, tool_config):
    """Beoordeel echte schemas én intentie, inclusief expliciete uitvoerderdefaults."""
    schemas = {t['toolSpec']['name']: t['toolSpec']['inputSchema']['json'] for t in tool_config.get('tools', [])}
    normalized, invalid = [], {}
    for call in calls:
        arguments = call.get('arguments', {})
        try:
            if schemas:
                if call.get('tool') not in schemas:
                    raise ValueError('geen beschikbare tool gekozen')
                validate_arguments(arguments, schemas[call['tool']])
            if call.get('tool') == 'plan_route' and isinstance(arguments, dict):
                arguments = {'activiteit':'toerfiets', 'doel':'toeren', 'tolerance_km':2.5, **arguments}
        except ValueError as exc:
            invalid[call['id']] = str(exc)
        normalized.append({**call, 'arguments':arguments})
    by_id = {c['id']: c for c in normalized}
    accepted_cases = []
    for case in cases:
        expected = dict(case.get('expected_arguments', {}))
        actual = by_id.get(case['id'], {}).get('arguments', {})
        for key, aliases in case.get('argument_aliases', {}).items():
            if isinstance(actual,dict) and actual.get(key) in aliases:
                expected[key] = actual[key]
        accepted_cases.append({**case, 'expected_arguments':expected})
    result = mcp_evals.score(accepted_cases, normalized)
    for case in result['cases']:
        if case['id'] in invalid:
            case['geslaagd'] = False
            case['fouten'].append(invalid[case['id']])
    result['geslaagd'] = sum(c['geslaagd'] for c in result['cases'])
    result['score_pct'] = round(result['geslaagd'] / max(1,result['totaal']) * 100, 1)
    return result


def validate_cases(cases, tool_config):
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('De evalsuite moet niet-leeg zijn en unieke case-id’s bevatten.')
    available = {t['toolSpec']['name'] for t in tool_config.get('tools', [])}
    for case in cases:
        for message in case.get('history', []):
            if message.get('role') not in ('user', 'assistant') or not isinstance(message.get('content'), str) or not message['content'].strip():
                raise ValueError(f"Case {case['id']}: ongeldige gesprekscontext.")
        if available and case['expected_tool'] not in available:
            raise ValueError(f"Case {case['id']}: {case['expected_tool']} bestaat niet in deze toolset. Gebruik de hosted suite voor Bedrock.")


def run(cases, client, model, *, system, tool_config, input_rate=None, output_rate=None, clock=time.monotonic):
    validate_cases(cases, tool_config)
    for rate in (input_rate, output_rate):
        if rate is not None and (not math.isfinite(rate) or rate < 0):
            raise ValueError('Tokenprijzen moeten eindig en niet-negatief zijn.')
    calls, measurements = [], []
    for case in cases:
        start = clock()
        try:
            response = client.converse(modelId=model, system=[{'text': system}],
                messages=[{'role':m['role'],'content':[{'text':m['content']}]} for m in case.get('history', [])] + [{'role':'user','content':[{'text':case['prompt']}]}],
                toolConfig=tool_config, inferenceConfig={'maxTokens':1400,'temperature':0.2})
            uses = [b['toolUse'] for b in response.get('output',{}).get('message',{}).get('content',[]) if 'toolUse' in b]
            call = uses[0] if uses else {}
            calls.append({'id':case['id'],'tool':call.get('name'),'arguments':call.get('input',{}),
                          'answer': '\n'.join(b['text'] for b in response.get('output',{}).get('message',{}).get('content',[]) if 'text' in b)})
            usage = response.get('usage',{})
            cost = None if input_rate is None or output_rate is None else (usage.get('inputTokens',0)*input_rate+usage.get('outputTokens',0)*output_rate)/1_000_000
            measurements.append({'id':case['id'],'seconds':round(clock()-start,3),'usage':usage,'estimated_usd':cost})
        except Exception as exc:
            measurements.append({'id':case['id'],'seconds':round(clock()-start,3),'error':type(exc).__name__})
    times = sorted(m['seconds'] for m in measurements if 'error' not in m)
    return {'model':model,'suite_sha256':fingerprint(cases,system,tool_config),
            'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'scope':'eerste toolkeuze en geldige argumenten; geen route-uitvoering of gesprekskwaliteit',
            'score':score(cases,calls,tool_config),'calls':calls,'measurements':measurements,
            'latency':{'p50_s':times[len(times)//2] if times else None,'p95_s':times[min(len(times)-1,int(len(times)*.95))] if times else None},
            'estimated_total_usd':sum(m.get('estimated_usd') or 0 for m in measurements) if input_rate is not None and output_rate is not None else None}


def command(args):
    import boto3
    from .aws_chat import SYSTEM_PROMPT, TOOL_CONFIG
    cases = mcp_evals.load(args.cases)
    if args.limit is not None:
        if args.limit < 1: raise ValueError('--limit moet minstens 1 zijn.')
        cases = cases[:args.limit]
    client = boto3.Session(profile_name=args.aws_profile,region_name=args.aws_region).client('bedrock-runtime')
    result = run(cases,client,args.model,system=SYSTEM_PROMPT,tool_config=TOOL_CONFIG,input_rate=args.input_per_million,output_rate=args.output_per_million)
    if args.output: Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result
