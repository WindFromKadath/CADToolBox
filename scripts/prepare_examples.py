"""Install portable fixtures only where private local cases are absent."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'configs'
    target.mkdir(exist_ok=True)
    copied, retained = [], []
    for source in sorted((ROOT / 'examples').glob('*-case.json')):
        dest = target / source.name
        if dest.exists():
            retained.append(source.name)
            continue
        # Exclusive creation protects existing local provenance, including races.
        with dest.open('xb') as stream:
            stream.write(source.read_bytes())
        copied.append(source.name)
    print(json.dumps({'copied': copied, 'retained_without_changes': retained,
                      'scope': 'synthetic regression fixtures; no private catalogs or verification proofs fabricated'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
