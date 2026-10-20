import os
from pathlib import Path

import pytest

from scripts.deploy import initialize


def test_init_creates_private_separate_keys_and_never_overwrites(tmp_path):
    env = tmp_path / '.env'
    initialize('blender.example.com', env)
    values = dict(line.split('=', 1) for line in env.read_text().splitlines() if line)
    assert len(values['API_TOKEN']) >= 32 and len(values['PROXY_SHARED_KEY']) >= 32
    assert values['API_TOKEN'] != values['PROXY_SHARED_KEY']
    assert values['PUBLIC_ORIGIN'] == 'https://blender.example.com'
    assert values['COOKIE_SECURE'] == 'true' and values['ALLOW_PAID_AI'] == 'false'
    assert os.stat(env).st_mode & 0o777 == 0o600
    original = env.read_bytes()
    with pytest.raises(FileExistsError):
        initialize('other.example.com', env)
    assert env.read_bytes() == original


@pytest.mark.parametrize('host', ['https://example.com', 'example.com/path', 'example.com:443',
                                 'localhost', 'example.com\n{ tls internal }', '127.0.0.1'])
def test_init_refuses_non_public_host_configuration(tmp_path, host):
    with pytest.raises(ValueError):
        initialize(host, tmp_path / '.env')
    assert not Path(tmp_path / '.env').exists()
