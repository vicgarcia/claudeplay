import asyncio
import socket

import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.middleware import AuthMiddleware

from claudeplay import auth, config, gateway

from conftest import fake

ME = 4242
STRANGER = 9999
KEY = 'k' * 40


class StubGithub(TokenVerifier):
    ''' stands in for github: token 'gh-<id>' is a valid github login for that numeric id '''

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith('gh-'):
            return None
        uid = token[3:]
        return AccessToken(token=token, client_id=uid, scopes=['read:user'], subject=uid, claims={'sub': uid})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def token(uid: int) -> AccessToken:
    return AccessToken(token='t', client_id=str(uid), scopes=[], subject=str(uid), claims={'sub': str(uid)})


def test_is_allowed_matches_numeric_id_exactly():
    allowed = frozenset({ME})
    assert auth.is_allowed(token(ME), allowed)
    assert not auth.is_allowed(token(STRANGER), allowed)
    assert not auth.is_allowed(None, allowed)
    assert not auth.is_allowed(AccessToken(token='t', client_id='x', scopes=[], subject=None, claims={}), allowed)
    assert not auth.is_allowed(AccessToken(token='t', client_id='x', scopes=[], subject='octocat', claims={}), allowed)
    assert not auth.is_allowed(token(ME), frozenset())


def test_allow_list_verifier_rejects_strangers_and_invalid_tokens():
    verifier = auth.AllowListVerifier(StubGithub(), {ME})

    async def go():
        return (
            await verifier.verify_token(f'gh-{ME}'),
            await verifier.verify_token(f'gh-{STRANGER}'),
            await verifier.verify_token('garbage'),
        )

    mine, stranger, garbage = asyncio.run(go())
    assert mine is not None and mine.subject == str(ME)
    assert stranger is None
    assert garbage is None


def test_build_requires_complete_auth_config():
    good = config.AuthConfig(client_id='id', client_secret='secret', jwt_signing_key=KEY, allowed_user_ids=(ME,))
    url = 'http://localhost:1'
    for bad in (
        config.AuthConfig(client_id='', client_secret='s', jwt_signing_key=KEY, allowed_user_ids=(ME,)),
        config.AuthConfig(client_id='i', client_secret='', jwt_signing_key=KEY, allowed_user_ids=(ME,)),
        config.AuthConfig(client_id='i', client_secret='s', jwt_signing_key='short', allowed_user_ids=(ME,)),
        config.AuthConfig(client_id='i', client_secret='s', jwt_signing_key=KEY, allowed_user_ids=()),
        config.AuthConfig(client_id='i', client_secret='s', jwt_signing_key=KEY, allowed_user_ids=(0,)),
    ):
        with pytest.raises(config.ConfigError):
            auth.build(bad, url)
    provider, _ = auth.build(good, url, store_dir=config.home_dir() / 'oauth')
    assert provider is not None


def test_build_unset_env_var_names_only_the_variable():
    cfg = config.AuthConfig(client_id='${GH_ID_X}', client_secret='s', jwt_signing_key=KEY, allowed_user_ids=(ME,))
    with pytest.raises(config.ConfigError, match='GH_ID_X is not set'):
        auth.build(cfg, 'http://localhost:1', environ={})


def test_token_store_is_encrypted_on_disk(tmp_path):
    store = auth.token_store(tmp_path / 'oauth', KEY)
    plaintext = 'refresh-token-plaintext-marker'

    async def go():
        await store.put(key='k1', value={'secret': plaintext}, collection='test')
        return await store.get(key='k1', collection='test')

    assert asyncio.run(go()) == {'secret': plaintext}
    blobs = [p.read_bytes() for p in (tmp_path / 'oauth').rglob('*') if p.is_file()]
    assert blobs and not any(plaintext.encode() in b for b in blobs)


def test_token_store_survives_restart(tmp_path):
    ''' a new store object with the same key reads what the old one wrote, so a restart keeps sessions '''
    async def write():
        await auth.token_store(tmp_path / 'oauth', KEY).put(key='k', value={'v': 1}, collection='c')

    async def read(key):
        return await auth.token_store(tmp_path / 'oauth', key).get(key='k', collection='c')

    asyncio.run(write())
    assert asyncio.run(read(KEY)) == {'v': 1}
    # a different key must not be able to read it
    assert asyncio.run(read('z' * 40)) is None


async def serve_gateway(gw, port):
    task = asyncio.create_task(gw.run_http_async(
        show_banner=False, host='127.0.0.1', port=port, uvicorn_config={'access_log': False, 'log_level': 'warning'},
    ))
    async with httpx2.AsyncClient() as http:
        for _ in range(100):
            try:
                await http.get(f'http://127.0.0.1:{port}/mcp')
                return task
            except httpx2.TransportError:
                await asyncio.sleep(0.1)
    raise RuntimeError('gateway did not start')


def test_http_endpoint_enforces_allow_list():
    cfg = config.GatewayConfig(servers=(fake('a'),))
    verifier = auth.AllowListVerifier(StubGithub(), {ME})

    async def attempt(port, bearer):
        headers = {'Authorization': f'Bearer {bearer}'} if bearer else {}
        transport = StreamableHttpTransport(f'http://127.0.0.1:{port}/mcp', headers=headers)
        async with Client(transport, mode='legacy') as client:
            return sorted(t.name for t in await client.list_tools())

    async def go():
        gw, _ = gateway.build(cfg, raw=True, auth=verifier, extra_middleware=(
            AuthMiddleware(auth=auth.allow_list_check({ME})),
        ))
        port = free_port()
        task = await serve_gateway(gw, port)
        try:
            outcomes = {}
            for label, bearer in (('mine', f'gh-{ME}'), ('stranger', f'gh-{STRANGER}'), ('none', None), ('junk', 'junk')):
                try:
                    outcomes[label] = await attempt(port, bearer)
                except Exception as e:
                    outcomes[label] = type(e).__name__
            return outcomes
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    outcomes = asyncio.run(go())
    assert outcomes['mine'] == ['a_echo', 'a_ping']
    for label in ('stranger', 'none', 'junk'):
        assert isinstance(outcomes[label], str), f'{label} got in: {outcomes[label]}'


def test_real_oauth_endpoints_are_published_and_mcp_requires_auth():
    port = free_port()
    base = f'http://127.0.0.1:{port}'
    acfg = config.AuthConfig(client_id='id', client_secret='secret', jwt_signing_key=KEY, allowed_user_ids=(ME,))
    provider, allow_list = auth.build(acfg, base, store_dir=config.home_dir() / 'oauth')
    gw, _ = gateway.build(config.GatewayConfig(servers=(fake('a'),)), raw=True, auth=provider, extra_middleware=(allow_list,))

    async def go():
        task = await serve_gateway(gw, port)
        try:
            async with httpx2.AsyncClient() as http:
                meta = await http.get(f'{base}/.well-known/oauth-authorization-server')
                resource = await http.get(f'{base}/.well-known/oauth-protected-resource/mcp')
                unauth = await http.post(f'{base}/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                                         headers={'Accept': 'application/json, text/event-stream'})
                callback = await http.get(f'{base}/auth/callback', follow_redirects=False)
                return meta, resource, unauth, callback
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    meta, resource, unauth, callback = asyncio.run(go())
    assert meta.status_code == 200
    body = meta.json()
    assert body['authorization_endpoint'].startswith(base)
    assert body['registration_endpoint'].startswith(base)
    assert resource.status_code == 200
    assert unauth.status_code == 401
    # the callback route exists (it rejects a request with no code rather than 404ing)
    assert callback.status_code == 400
