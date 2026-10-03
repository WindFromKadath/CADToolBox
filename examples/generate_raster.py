"""Generate synthetic pixels and matching hashed configs; never use source assets."""
from pathlib import Path
import argparse
import hashlib
import json
import cadtoolbox.geometry  # keeps backend caches local
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        parser.error('output must be a new directory inside project root')
    output.mkdir(parents=True)
    for mode in ['single', 'three-regions']:
        image = Image.new('RGB', (101, 101), 'white')
        draw = ImageDraw.Draw(image)
        if mode == 'single':
            draw.rectangle((10, 20, 90, 80), fill='black')
        else:
            for box, color in [((10, 10, 30, 90), (0, 102, 204)),
                               ((31, 10, 69, 90), (0, 176, 80)),
                               ((70, 10, 90, 90), (220, 60, 60))]:
                draw.rectangle(box, fill=color)
        path = output / (mode + '.png')
        image.save(path)
        config = json.loads((ROOT / 'examples' / ('raster-' + mode + '-case.json')).read_text(encoding='utf-8'))
        config['image_input'] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        (output / (mode + '.json')).write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'generated_configs': ['single.json', 'three-regions.json'], 'synthetic': True}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
