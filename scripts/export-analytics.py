"""Load the selected environment before importing the analytics exporter."""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--action', choices=('migrate', 'prepare', 'run'), default='run')
    parser.add_argument('--max-batches', type=int, default=5)
    args = parser.parse_args()
    if not args.env_file.is_file() or not args.config.is_file():
        parser.error('Required private configuration is missing')
    load_dotenv(args.env_file, override=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.analytics_export import main as export
    sys.argv = [sys.argv[0], args.action, '--config', str(args.config), '--max-batches', str(args.max_batches)]
    return export()


if __name__ == '__main__':
    raise SystemExit(main())
