import argparse
import json
from .ingest import ingest_tenant

def main() -> None:
    parser = argparse.ArgumentParser(description='Index one tenant folder')
    parser.add_argument('tenant_id')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    for result in ingest_tenant(args.tenant_id, args.force):
        print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
