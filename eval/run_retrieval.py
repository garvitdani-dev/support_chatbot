"""Report document recall for local hybrid retrieval without calling an LLM."""
import json
import os
os.environ['OPENAI_API_KEY'] = ''  # local benchmark only
from pathlib import Path
from app import retrieval

cases=json.loads(Path(__file__).with_name('retrieval_cases.json').read_text())
by_category={}
for case in cases:
    results=retrieval.hybrid(case['tenant_id'],case['question'],5)
    hit=case['expected_document'] in [r['filename'] for r in results]
    by_category.setdefault(case['category'],[]).append(hit)
    if not hit: print('MISS',case['id'],case['question'])
for name,values in by_category.items(): print(name,f'{sum(values)}/{len(values)}')
print('overall',f'{sum(map(sum,by_category.values()))}/{len(cases)}')
