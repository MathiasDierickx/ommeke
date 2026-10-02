"""Offline releasepoort voor een wijziging van het Terraform-chatmodel."""
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from . import model_evals, mcp_evals

ROOT = Path(__file__).resolve().parents[1]
VARIABLES = 'infra/terraform/variables.tf'


def configured_model(text):
    match = re.search(r'variable\s+"bedrock_model_id"\s*\{(.*?)\n\}', text, re.S)
    value = re.search(r'^\s*default\s*=\s*"([^"\n]+)"', match[1], re.M) if match else None
    if not value: raise ValueError('Geen eenduidig standaardmodel in Terraform gevonden.')
    return value[1]


def verify(report, model, cases, system, tools, *, now=None):
    now = now or datetime.now(timezone.utc)
    if report.get('model') != model: raise ValueError('Evalrapport hoort bij een ander model.')
    if report.get('suite_sha256') != model_evals.fingerprint(cases,system,tools):
        raise ValueError('Evalrapport hoort niet bij de huidige suite, prompt en toolschemas.')
    created = datetime.fromisoformat(report['created_at'].replace('Z','+00:00'))
    if created.tzinfo is None or not timedelta(0) <= now-created <= timedelta(days=30):
        raise ValueError('Evalrapport is verlopen of heeft een ongeldige datum.')
    ids = {c['id'] for c in cases}
    if len(ids) < 10 or len(ids) != len(cases): raise ValueError('Minstens tien unieke cases zijn vereist.')
    for field in ('calls','measurements'):
        rows = report.get(field,[])
        if len(rows) != len(ids) or {r['id'] for r in rows} != ids:
            raise ValueError(f'Evalrapport mist cases of bevat duplicaten in {field}.')
    if any('error' in row for row in report['measurements']): raise ValueError('Eval bevat providerfouten.')
    actual = model_evals.score(cases,report['calls'],tools)
    if actual['geslaagd'] != actual['totaal']:
        raise ValueError(f"Modelwissel geweigerd: {actual['geslaagd']}/{actual['totaal']} intentcases geslaagd.")
    return {'ok':True,'model':model,'score':actual['score_pct'],'cases':actual['totaal']}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',required=True)
    parser.add_argument('--report',default='evals/approved-model.json')
    args=parser.parse_args()
    try:
        if not re.fullmatch(r'[0-9a-f]{40}',args.base) or set(args.base)=={'0'}:
            raise ValueError('Een geldige bestaande base-commit is vereist.')
        previous=subprocess.run(['git','show',f'{args.base}:{VARIABLES}'],cwd=ROOT,text=True,capture_output=True,check=True).stdout
        model=configured_model((ROOT/VARIABLES).read_text())
        if model == configured_model(previous):
            result={'ok':True,'model':model,'reason':'Productiemodel is niet gewijzigd.'}
        else:
            from .aws_chat import SYSTEM_PROMPT, TOOL_CONFIG
            cases=mcp_evals.load(ROOT/'evals/hosted_intents.json')
            result=verify(json.loads((ROOT/args.report).read_text()),model,cases,SYSTEM_PROMPT,TOOL_CONFIG)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError,subprocess.CalledProcessError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False,indent=2))
        raise SystemExit(1)


if __name__=='__main__': main()
