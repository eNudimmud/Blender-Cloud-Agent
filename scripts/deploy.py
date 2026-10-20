"""Configure/start HTTPS on an existing Linux server. Never provisions cloud resources."""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTNAME = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def initialize(hostname, env_file):
    hostname = hostname.lower()
    if not HOSTNAME.fullmatch(hostname):
        raise ValueError('Supply a DNS hostname, without a scheme, port, or path.')
    contents = '\n'.join([
        f'API_TOKEN={secrets.token_urlsafe(36)}',
        f'PROXY_SHARED_KEY={secrets.token_urlsafe(36)}',
        f'BCA_HOSTNAME={hostname}', f'PUBLIC_ORIGIN=https://{hostname}',
        'COOKIE_SECURE=true', 'AGENT_MODE=rules', 'ALLOW_PAID_AI=false', '',
    ])
    # Exclusive creation protects existing keys and data configuration on a rerun.
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(contents)


def command(env_file):
    return ['docker', 'compose', '--env-file', str(env_file), '-f', str(ROOT / 'compose.yml'),
            '-f', str(ROOT / 'compose.https.yml')]


def preflight(env_file):
    version = subprocess.run(['docker', 'compose', 'version', '--short'], check=True, capture_output=True, text=True).stdout
    numbers = re.match(r'v?(\d+)\.(\d+)', version.strip())
    if not numbers or tuple(map(int, numbers.groups())) < (2, 24):
        raise ValueError('Docker Compose 2.24 or newer is required.')
    config = json.loads(subprocess.run(command(env_file) + ['config', '--format', 'json'],
                                       check=True, capture_output=True, text=True).stdout)
    services = config['services']
    api, worker, proxy = (services[name] for name in ('api', 'worker', 'proxy'))
    env = api['environment']
    host = proxy['environment']['BCA_HOSTNAME']
    if not HOSTNAME.fullmatch(host) or env['PUBLIC_ORIGIN'] != 'https://' + host:
        raise ValueError('PUBLIC_ORIGIN must match the configured public hostname.')
    if env.get('COOKIE_SECURE') != 'true' or api.get('ports'):
        raise ValueError('HTTPS requires secure cookies and an unpublished API port.')
    if len(env.get('API_TOKEN', '')) < 32 or len(env.get('PROXY_SHARED_KEY', '')) < 32:
        raise ValueError('Both private keys must contain at least 32 characters.')
    if env['API_TOKEN'] == env['PROXY_SHARED_KEY']:
        raise ValueError('Use separate workspace and proxy keys.')
    if env['PROXY_SHARED_KEY'] != proxy['environment']['PROXY_SHARED_KEY']:
        raise ValueError('Proxy and API keys do not match.')
    if env.get('AGENT_MODE') != 'rules' or env.get('ALLOW_PAID_AI') != 'false':
        raise ValueError('This deployment helper keeps external AI and spending disabled.')
    if worker.get('network_mode') != 'none' or not worker.get('read_only'):
        raise ValueError('Worker isolation is missing.')
    if any(key in worker.get('environment', {}) for key in ('API_TOKEN', 'LLM_API_KEY', 'PROXY_SHARED_KEY')):
        raise ValueError('Worker must not receive service credentials.')
    return host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['init', 'check', 'up'])
    parser.add_argument('--hostname')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    args = parser.parse_args()
    try:
        if args.operation == 'init':
            initialize(args.hostname or '', args.env_file)
            print('Private configuration created. Existing configuration was not overwritten.')
            return
        host = preflight(args.env_file)
        print(f'HTTPS configuration validated for {host}. External AI is disabled.')
        if args.operation == 'up':
            subprocess.run(command(args.env_file) + ['up', '-d', '--build', '--wait'], check=True)
    except (ValueError, FileExistsError, FileNotFoundError, subprocess.CalledProcessError, KeyError, json.JSONDecodeError) as exc:
        # Never print resolved Compose configuration or a captured error that might contain keys.
        detail = str(exc) if isinstance(exc, (ValueError, FileExistsError)) else 'Docker/configuration check failed.'
        print(detail, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
