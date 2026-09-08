"""Report observed reviewer decisions, never a self-assigned quality score."""
import argparse
import json
from pathlib import Path


def outcomes(path):
    batches = []
    for line in path.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        reviews = record.get('reviews', {})
        selected = sum(r.get('status') == 'selected' for r in reviews.values())
        rejected = sum(r.get('status') == 'rejected' for r in reviews.values())
        written = sum(r.get('status') == 'selected' and any(t in r.get('note', '') for t in ('写过', '已经写', '做过')) for r in reviews.values())
        batches.append({'batch': record.get('generated_at'), 'reviewed': len(reviews),
                        'selected_button': selected, 'rejected_button': rejected,
                        'selected_already_covered': written})
    decided = sum(b['selected_button'] + b['rejected_button'] for b in batches)
    return {'batch_count': len(batches), 'decision_count': decided,
            'selected_button_rate': round(sum(b['selected_button'] for b in batches) / decided, 4) if decided else None,
            'recall': None, 'recall_reason': 'No independently sampled corpus of missed qualifying sources',
            'quality_target_verified': False,
            'note': 'Button rate is not publishable-topic yield; duplicates, covered topics and conflicting notes require review.',
            'recent_batches': batches[-10:]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('feedback', nargs='?', type=Path, default=Path(__file__).resolve().parents[1]/'.local/editorial_feedback.jsonl')
    args = parser.parse_args()
    print(json.dumps(outcomes(args.feedback), ensure_ascii=False, indent=2))
