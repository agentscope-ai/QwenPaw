"""Final findings: real HTTP, isolated PG and synthetic skill materials."""
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.integration.test_agent_skill_lifecycle import (
    lifecycle_fixture, skill_database, private_tree,
)
from qwenpaw.skills.lifecycle import SkillLifecycleService
from qwenpaw.skills.snapshots import directory_hash
from qwenpaw.agents.skill_system.workspace_service import SkillService
from qwenpaw.agents.skill_system.store import read_skill_manifest, mutate_json


@asynccontextmanager
async def http_fixture(database, tmp_path, monkeypatch):
    from qwenpaw.app.routers import skills, skill_governance
    from qwenpaw.access.dependencies import get_actor
    from qwenpaw.access.agent_repository import AgentResourceRole
    async with lifecycle_fixture(database, tmp_path) as fixture:
        governance, people, item, source, workspaces, sessions = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        async def resolve(request):
            return SimpleNamespace(agent_id='agentA', workspace_dir=str(workspaces['agentA']))
        monkeypatch.setenv('QWENPAW_MULTI_USER_ENABLED', 'true')
        monkeypatch.setattr('qwenpaw.app.agent_context.get_agent_for_request', resolve)
        monkeypatch.setattr('qwenpaw.app.agent_context.get_agent_access_state', lambda request: (AgentResourceRole.OWNER, None))
        monkeypatch.setattr('qwenpaw.skills.runtime.get_skill_lifecycle_service', lambda: lifecycle)
        monkeypatch.setattr(skill_governance, 'get_skill_lifecycle_service', lambda: lifecycle)
        monkeypatch.setattr(skills, '_workspace_dir_for_agent', workspaces.__getitem__)
        monkeypatch.setattr(skills, 'schedule_agent_reload', lambda *args: None)
        app = FastAPI()
        app.include_router(skills.router, prefix='/api')
        app.include_router(skills.router, prefix='/api/agents/agentA')
        app.include_router(skill_governance.router, prefix='/api')
        @app.middleware('http')
        async def actor_state(request, call_next):
            request.state.actor = people[0] if '/pool/' in request.url.path or '/skill-governance/' in request.url.path else people[1]
            return await call_next(request)
        app.dependency_overrides[get_actor] = lambda: people[0]
        async with AsyncClient(transport=ASGITransport(app), base_url='http://fixture') as client:
            yield client, lifecycle, fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix', ['/api', '/api/agents/agentA'])
@pytest.mark.parametrize('with_cache_artifacts', [False, True])
async def test_f1_old_upload_keeps_private_config_out_of_pool(skill_database, tmp_path, monkeypatch, prefix, with_cache_artifacts):
    from qwenpaw.agents.skill_system import pool_service, store
    async with http_fixture(skill_database, tmp_path, monkeypatch) as (client, lifecycle, fixture):
        governance, (_, owner, _, _), item, _, workspaces, _ = fixture
        monkeypatch.setenv('QWENPAW_SKILL_SCAN_MODE', 'off')
        pool = tmp_path / 'upload-pool'
        manifest_path = tmp_path / 'upload-pool.json'
        monkeypatch.setattr(pool_service, 'get_skill_pool_dir', lambda: pool)
        monkeypatch.setattr(pool_service, 'get_pool_skill_manifest_path', lambda: manifest_path)
        monkeypatch.setattr(pool_service, 'read_skill_pool_manifest', lambda: store.read_json(manifest_path, store.default_pool_manifest()))
        await lifecycle.install(owner, 'agentA', item['id'])
        ws = workspaces['agentA']
        artifacts = ['.DS_Store', 'Thumbs.db', 'scripts/__pycache__/run.cpython-312.pyc']
        if with_cache_artifacts:
            for name in artifacts:
                artifact = ws / 'skills/sample' / name
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(b'normal cache artifact')
        mutate_json(ws / 'skill.json', {}, lambda p: p['skills']['sample'].update(config={'api_key': 'SYNTHETIC_PRIVATE_ONLY'}))
        before = private_tree(ws)
        response = await client.post(prefix + '/skills/pool/upload', json={'workspace_id': 'agentA', 'skill_name': 'sample'})
        assert response.status_code == 200, response.text
        assert 'SYNTHETIC_PRIVATE_ONLY' not in manifest_path.read_text()
        assert private_tree(ws) == before
        assert all(not (pool / 'sample' / name).exists() for name in artifacts)
        snapshot = governance.snapshots.capture(pool / 'sample', 'sample')
        assert all(b'SYNTHETIC_PRIVATE_ONLY' not in value for value in private_tree(governance.snapshots.root / snapshot.snapshot_key).values() if value)
        (ws / 'skills/sample/references').mkdir(exist_ok=True)
        (ws / 'skills/sample/references/secret.txt').write_text('password = "real_synthetic_password_123"', encoding='utf-8')
        shared_before = private_tree(pool)
        response = await client.post(prefix + '/skills/pool/upload', json={'workspace_id': 'agentA', 'skill_name': 'sample', 'overwrite': True})
        assert response.status_code == 400
        assert response.json()['detail'] == 'shared_skill_credentials_detected'
        assert private_tree(pool) == shared_before


@pytest.mark.asyncio
async def test_f2_rename_confirmation_rechecks_full_target_and_disappearance(skill_database, tmp_path, monkeypatch):
    async with http_fixture(skill_database, tmp_path, monkeypatch) as (client, lifecycle, fixture):
        governance, (_, owner, _, _), item, source, workspaces, _ = fixture
        await lifecycle.install(owner, 'agentA', item['id'])
        ws = workspaces['agentA']
        content = (source / 'SKILL.md').read_text()
        SkillService(ws).create_skill('target', content, references={'note.txt': 'H1'}, enable=True)
        body = dict(name='target', source_name='sample', content=content)
        conflict = await client.put('/api/skills/save', json=body)
        assert conflict.status_code == 409
        h1 = directory_hash(ws / 'skills/target', shared=False)
        assert conflict.json()['detail']['expected_content_hash'] == h1
        bindings = await governance.repository.installed('agentA')
        before = private_tree(ws)
        missing = await client.put('/api/skills/save', json={**body, 'overwrite': True})
        assert missing.status_code == 409 and missing.json()['detail'] == 'content_conflict'
        assert private_tree(ws) == before
        (ws / 'skills/target/references/note.txt').write_text('H2', encoding='utf-8')
        before = private_tree(ws)
        stale = await client.put('/api/skills/save', json={**body, 'overwrite': True, 'expected_content_hash': h1})
        assert stale.status_code == 409
        assert private_tree(ws) == before
        assert await governance.repository.installed('agentA') == bindings
        target = ws / 'skills/target'
        h2 = directory_hash(target, shared=False)
        target.rename(ws / 'held-target')
        before = private_tree(ws)
        gone = await client.put('/api/skills/save', json={**body, 'overwrite': True, 'expected_content_hash': h2})
        assert gone.status_code == 409
        assert private_tree(ws) == before
        (ws / 'held-target').rename(target)
        fresh = await client.put('/api/skills/save', json={**body, 'overwrite': True, 'expected_content_hash': h2})
        assert fresh.status_code == 200
        assert not (ws / 'skills/sample').exists()
        assert (await governance.repository.installed('agentA'))['target']['source_pool_version_id'] == item['version_id']


@pytest.mark.asyncio
async def test_f4_preview_and_confirm_existing_fixed_version_mixed_results(skill_database, tmp_path, monkeypatch):
    async with http_fixture(skill_database, tmp_path, monkeypatch) as (client, lifecycle, fixture):
        governance, (admin, owner, _, _), item, source, workspaces, _ = fixture
        await lifecycle.install(owner, 'agentA', item['id'])
        (source / 'scripts/run.py').write_text("print('B')\n", encoding='utf-8')
        await governance.import_existing(admin, await governance.preview_existing(admin))
        endpoint = f"/api/skill-governance/items/{item['id']}/broadcast"
        before = private_tree(workspaces['agentA'])
        body = {'agent_ids': ['agentA', 'agentB']}
        preview = await client.post(endpoint, json={**body, 'preview_only': True})
        assert preview.status_code == 200, preview.text
        ready, denied = preview.json()['results']
        assert ready['status'] == 'ready' and denied['reason'] == 'not_authorized'
        assert private_tree(workspaces['agentA']) == before
        assert not workspaces['agentB'].exists()
        confirmations = {'agentA': {key: ready[key] for key in ['expected_content_hash', 'expected_version_id']}}
        missing = await client.post(endpoint, json={**body, 'overwrite': True})
        assert missing.json()['results'][0]['status'] == 'failed'
        assert private_tree(workspaces['agentA']) == before
        result = await client.post(endpoint, json={**body, 'overwrite': True, 'confirmations': confirmations})
        assert result.json()['results'][0]['status'] == 'updated'
        assert (workspaces['agentA'] / 'skills/sample/scripts/run.py').read_text() == "print('B')\n"
        unchanged = await client.post(endpoint, json={**body, 'preview_only': True})
        assert unchanged.json()['results'][0]['status'] == 'unchanged'


@pytest.mark.asyncio
@pytest.mark.parametrize('batch', [False, True])
@pytest.mark.parametrize('history', [False, True])
@pytest.mark.parametrize('recreate', ['create', 'zip', 'hub'])
async def test_f5_explicit_delete_unbinds_preserving_request_and_private_recreation(skill_database, tmp_path, monkeypatch, batch, history, recreate):
    async with http_fixture(skill_database, tmp_path, monkeypatch) as (client, lifecycle, fixture):
        governance, (admin, owner, _, _), item, source, workspaces, _ = fixture
        ws = workspaces['agentA']
        SkillService(ws).create_skill('sample', (source / 'SKILL.md').read_text(), enable=True)
        publication = await governance.submit_request(owner, 'agentA', 'sample', ws / 'skills/sample') if history else None
        await lifecycle.install(owner, 'agentA', item['id'], overwrite=True, expected_content_hash=directory_hash(ws / 'skills/sample', shared=False))
        old = (await governance.repository.installed('agentA'))['sample']
        if batch:
            deleted = await client.post('/api/skills/batch-delete', json=['sample'])
            assert deleted.json()['results']['sample']['success'] is True
        else:
            deleted = await client.delete('/api/skills/sample')
            assert deleted.status_code == 200
        row = (await governance.repository.installed('agentA'))['sample']
        assert row['id'] == old['id'] and row['source_pool_version_id'] is None
        content = (source / 'SKILL.md').read_text()
        if recreate == 'create':
            response = await client.post('/api/skills', json={'name': 'sample', 'content': content, 'scripts': {'run.py': "print('A')\n"}, 'enable': True})
            assert response.status_code == 200, response.text
        elif recreate == 'zip':
            import io
            import zipfile
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as archive:
                archive.writestr('sample/SKILL.md', content)
                archive.writestr('sample/scripts/run.py', "print('A')\n")
            result = SkillService(ws).import_from_zip(data.getvalue(), enable=True)
            assert result['imported'] == ['sample']
        else:
            from qwenpaw.agents.skill_system import hub
            async def payload(*args):
                return SimpleNamespace(name='sample', content=content, references=None, scripts={'run.py': "print('A')\n"}, extra_files=None, installed_from='url', source_url='https://fixture.invalid/skill')
            monkeypatch.setattr(hub, '_prepare_install_payload', payload)
            result = await hub.install_skill_from_hub(workspace_dir=ws, bundle_url='https://fixture.invalid/skill', enable=True)
            assert result.name == 'sample'
        state = (await lifecycle.list_installed(owner, 'agentA'))['items'][0]
        assert state['source_pool_version_id'] is None and state['detached'] is False
        before = private_tree(ws)
        assert (await lifecycle.auto_update(item['id'], ['agentA']))['results'][0]['reason'] == 'skill_source_required'
        assert private_tree(ws) == before
        await governance.submit_request(owner, 'agentA', 'sample', ws / 'skills/sample')
        if publication:
            reviewed = await governance.review_request(admin, publication['id'], 'approve', 0, '')
            assert reviewed


@pytest.mark.asyncio
@pytest.mark.parametrize('change,reason', [('content', 'content_conflict'), ('source', 'source_version_changed'), ('missing', 'content_conflict')])
async def test_f4_stale_preview_is_per_target_failure_even_when_now_detached(skill_database, tmp_path, monkeypatch, change, reason):
    async with http_fixture(skill_database, tmp_path, monkeypatch) as (client, lifecycle, fixture):
        governance, (admin, owner, _, user), item, source, workspaces, _ = fixture
        await lifecycle.install(owner, 'agentA', item['id'])
        await governance.set_agent_grant(admin, item['id'], 'agentB', True)
        await lifecycle.install(user, 'agentB', item['id'])
        (source / 'scripts/run.py').write_text("print('B')\n", encoding='utf-8')
        await governance.import_existing(admin, await governance.preview_existing(admin))
        endpoint = f"/api/skill-governance/items/{item['id']}/broadcast"
        body = {'agent_ids': ['agentA', 'agentB']}
        preview = (await client.post(endpoint, json={**body, 'preview_only': True})).json()['results']
        confirmations = {row['agent_id']: {key: row[key] for key in ['expected_content_hash', 'expected_version_id']} for row in preview}
        if change == 'content':
            (workspaces['agentA'] / 'skills/sample/SKILL.md').write_text('Edited after preview', encoding='utf-8')
        elif change == 'missing':
            (workspaces['agentA'] / 'skills/sample').rename(workspaces['agentA'] / 'held')
        else:
            (source / 'scripts/run.py').write_text("print('C')\n", encoding='utf-8')
            await governance.import_existing(admin, await governance.preview_existing(admin))
        before = private_tree(workspaces['agentA'])
        result = await client.post(endpoint, json={**body, 'overwrite': True, 'confirmations': confirmations})
        assert result.status_code == 200
        rows = result.json()['results']
        assert rows[0]['status'] == 'failed' and rows[0]['reason'] == reason
        assert private_tree(workspaces['agentA']) == before
        assert rows[1]['status'] == ('failed' if change == 'source' else 'updated')


@pytest.mark.asyncio
async def test_f4_alias_preview_missing_confirmation_and_detached_are_read_only(skill_database, tmp_path, monkeypatch):
    async with http_fixture(skill_database, tmp_path, monkeypatch) as (client, lifecycle, fixture):
        governance, (admin, owner, _, _), item, source, workspaces, _ = fixture
        await lifecycle.install(owner, 'agentA', item['id'])
        (source / 'scripts/run.py').write_text("print('B')\n", encoding='utf-8')
        await governance.import_existing(admin, await governance.preview_existing(admin))
        endpoint = '/api/agents/agentA/skills/pool/download'
        body = {'skill_name': 'sample', 'targets': [{'workspace_id': 'agentA'}]}
        before = private_tree(workspaces['agentA'])
        response = await client.post(endpoint, json={**body, 'preview_only': True})
        assert response.status_code == 200, response.text
        ready = response.json()['results'][0]
        assert ready['status'] == 'ready'
        result = await client.post(endpoint, json={**body, 'overwrite': True})
        assert result.json()['results'][0]['reason'] == 'confirmation_required'
        assert private_tree(workspaces['agentA']) == before
        confirmations = {'agentA': {key: ready[key] for key in ['expected_content_hash', 'expected_version_id']}}
        result = await client.post(endpoint, json={**body, 'overwrite': True, 'confirmations': confirmations})
        assert result.json()['results'][0]['status'] == 'updated'
        (workspaces['agentA'] / 'skills/sample/SKILL.md').write_text('Local', encoding='utf-8')
        before = private_tree(workspaces['agentA'])
        bindings = await governance.repository.installed('agentA')
        response = await client.post(endpoint, json={**body, 'preview_only': True})
        assert response.json()['results'][0]['reason'] == 'detached'
        assert private_tree(workspaces['agentA']) == before
        assert await governance.repository.installed('agentA') == bindings
        skipped = await client.post(endpoint, json={**body, 'overwrite': True, 'confirmations': {}})
        assert skipped.json()['results'][0]['reason'] == 'detached'
        assert private_tree(workspaces['agentA']) == before


@pytest.mark.asyncio
async def test_f5_delete_commit_failure_compensates_files_runtime_and_binding(skill_database, tmp_path, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    async with http_fixture(skill_database, tmp_path, monkeypatch) as (_, lifecycle, fixture):
        governance, (_, owner, _, _), item, _, workspaces, sessions = fixture
        await lifecycle.install(owner, 'agentA', item['id'])
        before = private_tree(workspaces['agentA'])
        bindings = await governance.repository.installed('agentA')
        async with sessions() as session:
            await session.execute(text(f'''CREATE FUNCTION "{skill_database.name}".fail_delete() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''fixture delete commit''; END' '''))
            await session.execute(text(f'''CREATE CONSTRAINT TRIGGER fail_delete AFTER UPDATE ON {governance.repository.table('agent_skills')} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "{skill_database.name}".fail_delete()'''))
        with pytest.raises(SQLAlchemyError, match='fixture delete commit'):
            await lifecycle.delete(owner, 'agentA', 'sample')
        assert private_tree(workspaces['agentA']) == before
        assert await governance.repository.installed('agentA') == bindings
