from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
    paths = sorted(root.rglob('AUTO_run_summary.json'))
    if not paths:
        print(f'No AUTO_run_summary.json files found under {root}')
        return 1

    rows: list[dict[str, object]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            print(f'Skip {path}: {exc}')
            continue
        passes = data.get('passes') or []
        first_outcome = ''
        if isinstance(passes, list) and passes and isinstance(passes[0], dict):
            first_outcome = str(passes[0].get('outcome') or '')
        final_success = data.get('full_code_success_posthoc')
        rows.append(
            {
                'session_id': data.get('session_id') or path.parent.name,
                'true_code': data.get('evaluation_true_code_posthoc') or '',
                'detected_code': data.get('detected_code') or '',
                'operator_unlock': int(bool(data.get('operator_confirmed_unlock'))),
                'full_code_success': '' if final_success is None else int(bool(final_success)),
                'first_pass_unlock': int(first_outcome.startswith('UNLOCKED')),
                'first_pass_top1_unlock': int(first_outcome == 'UNLOCKED_TOP1'),
                'passes_used': int(data.get('passes_used') or len(passes) or 0),
                'fresh_retry_used': int(int(data.get('passes_used') or len(passes) or 0) > 1),
                'summary_path': str(path),
            }
        )

    if not rows:
        print('No readable run summaries found.')
        return 1

    out = root / 'AUTO_test_campaign_summary.csv'
    with out.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    n = len(rows)
    labelled = [r for r in rows if r['full_code_success'] != '']
    first_pass = sum(int(r['first_pass_unlock']) for r in rows)
    first_top1 = sum(int(r['first_pass_top1_unlock']) for r in rows)
    operator_unlock = sum(int(r['operator_unlock']) for r in rows)
    retried = [r for r in rows if int(r['fresh_retry_used']) == 1]
    recovered = sum(int(r['operator_unlock']) for r in retried)

    print(f'Runs: {n}')
    print(f'First-pass Top-1 unlock: {first_top1}/{n} = {100*first_top1/n:.1f}%')
    print(f'First-pass any-prefix unlock: {first_pass}/{n} = {100*first_pass/n:.1f}%')
    print(f'Final operator-confirmed unlock: {operator_unlock}/{n} = {100*operator_unlock/n:.1f}%')
    if labelled:
        successes = sum(int(r['full_code_success']) for r in labelled)
        print(f'Post-hoc labelled full-code success: {successes}/{len(labelled)} = {100*successes/len(labelled):.1f}%')
    else:
        print('Post-hoc labelled full-code success: unavailable (no true codes entered).')
    print(f'Fresh retries used: {len(retried)}/{n}')
    if retried:
        print(f'Retried runs eventually unlocked: {recovered}/{len(retried)} = {100*recovered/len(retried):.1f}%')
    print(f'CSV written: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
