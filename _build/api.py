"""Helper minimo para a API publica do n8n."""
import json, os, sys, urllib.request, urllib.error

ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')
ENV = dict(l.strip().split('=', 1) for l in open(ENV_PATH, encoding='utf-8') if '=' in l and not l.strip().startswith('#'))
BASE, KEY = ENV['N8N_API_URL'], ENV['N8N_API_KEY']

def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'X-N8N-API-KEY': KEY, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            t = r.read().decode()
            return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f'{method} {path} -> {e.code}: {e.read().decode()[:2000]}')

if __name__ == '__main__':
    m, p = sys.argv[1], sys.argv[2]
    b = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    print(json.dumps(call(m, p, b), indent=1, ensure_ascii=False))
