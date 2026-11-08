"""Offline checks against the real server's declarations, without importing it."""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPO=Path(os.environ.get('BOT4VPS_REPO','/opt/bot4vps'))

class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract=json.loads((ROOT/'app/src/main/assets/native_contract.json').read_text())
        cls.ops={op['id']:op for op in cls.contract['operations']}

    def test_every_native_action_targets_an_existing_route(self):
        routes=[]
        for path in [REPO/'ui/web/app.py',*(REPO/'ui/web/routers').glob('*.py')]:
            tree=ast.parse(path.read_text())
            prefix=''
            for node in tree.body:
                if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call) and ast.unparse(node.value.func).endswith('APIRouter'):
                    prefix=next((ast.literal_eval(k.value) for k in node.value.keywords if k.arg=='prefix'),'')
                if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
                for d in node.decorator_list:
                    if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr in ('get','post','put','patch','delete') and d.args and isinstance(d.args[0],ast.Constant):
                        route=prefix+d.args[0].value
                        pattern='^'+re.sub(r'\\\{[^}]+\\\}',r'[^/]+',re.escape(route))+'$'
                        routes.append((d.func.attr.upper(),re.compile(pattern)))
        for op in self.ops.values():
            concrete=re.sub(r'\{[^}]+\}','example',op['path'])
            self.assertTrue(any(method==op['method'] and pattern.fullmatch(concrete) for method,pattern in routes),op['id'])

    def test_all_sections_are_reachable_and_actions_unique(self):
        self.assertEqual(len(self.ops),len(self.contract['operations']))
        for op in self.ops.values():self.assertIn(op['section'],self.contract['sections'],op['id'])

    def test_restore_never_exposes_apply_as_a_form_toggle(self):
        for op in self.ops.values():
            if (op.get('body') or {}).get('model')=='RestoreBody':
                props=op['body']['properties']
                self.assertFalse({'apply','confirm','prepared_operation_id','request_id'} & props.keys())
                self.assertEqual(props['restore_mode']['enum'],['merge','clean'])

    def test_backup_workflows_preserve_archive_namespace_and_upload_transport(self):
        for base in ('/api/backups/{backup_id}', '/api/backups/imported/{entry_key}'):
            for method,suffix in [('GET','/preview'),('GET','/download'),('PATCH','/filename'),('DELETE',''),
                                  ('POST','/restore'),('POST','/restore/plan'),('POST','/restore/inventory/prepare'),
                                  ('GET','/restore/inventory/status'),('POST','/restore/tree/children')]:
                op=self.ops[f'{method} {base}{suffix}']
                self.assertTrue(any(f['name']=='server_id' and f['location']=='query' for f in op['fields']),op['id'])
        fields={f['name']:f for f in self.ops['POST /api/backups/import']['fields']}
        self.assertEqual(fields['file']['location'],'form')
        self.assertEqual(fields['file']['type'],'file')
        self.assertEqual(fields['destination_server_id']['location'],'query')
        pattern=self.ops['POST /api/backups/create']['body']['properties']['target']['pattern']
        self.assertIsNotNone(re.fullmatch(pattern,'server'))
        self.assertIsNotNone(re.fullmatch(pattern,'bot4vps'))
        self.assertIsNone(re.fullmatch(pattern,'all'))

    def test_inherited_security_fields_survive_generation(self):
        op=self.ops['POST /api/servers/{server_id}/quick-setup/firewall/switch']
        self.assertIn('continuation',op['body']['properties'])
        op=self.ops['PUT /api/servers/{server_id}/quick-setup/fail2ban/configuration/content']
        self.assertTrue({'filename','kind','content'} <= op['body']['properties'].keys())

    def test_certificates_upload_as_two_file_parts(self):
        fields={f['name']:f for f in self.ops['POST /api/settings/web/tls/upload']['fields']}
        self.assertEqual(fields['cert']['type'],'file')
        self.assertEqual(fields['key']['type'],'file')
        self.assertEqual(fields['key']['location'],'form')

    def test_native_service_actions_have_typed_required_parameters(self):
        op=self.ops['POST /api/services/docker/{server_id}/enqueue/container_run']
        self.assertEqual(set(op['body']['properties']['params']['required']),{'name','image'})
        op=self.ops['POST /api/services/3x-ui/{server_id}/action/set_autostart']
        self.assertEqual(op['body']['properties']['params']['properties']['enabled']['type'],'boolean')

    def test_compose_actions_identify_deployment_and_source(self):
        for action in ('compose_up','compose_down','compose_restart'):
            params=self.ops[f'POST /api/services/docker/{{server_id}}/enqueue/{action}']['body']['properties']['params']
            self.assertEqual(set(params['required']),{'stack','source'})
            self.assertEqual(params['properties']['source']['enum'],['library','server'])
            self.assertTrue(params['properties']['key']['nullable'])
        files=self.ops['GET /api/services/docker/{server_id}/stacks/{name}/files']['fields']
        self.assertTrue({'name','remote','key'} <= {field['name'] for field in files})

    def test_additional_service_actions_are_scoped_to_a_server(self):
        choices=json.loads((ROOT/'app/src/main/assets/service_actions.json').read_text())
        ids=[]
        for choice in choices:
            key=f"{choice['method']} /api/services/{choice['serviceId']}/{{server_id}}/{choice['suffix']}"
            self.assertIn(key,self.ops)
            op=self.ops[key]
            self.assertTrue(any(field['name']=='server_id' and field['location']=='path' for field in op['fields']),key)
            self.assertFalse(op['path'].endswith('/status'))
            ids.append(key)
        self.assertEqual(len(ids),len(set(ids)))

    def test_export_download_is_distinct_from_compose_upload(self):
        export=self.ops['POST /api/services/wireguard/{server_id}/export-zip']
        self.assertTrue(export['download'])
        self.assertIn('names',export['body']['required'])
        self.assertEqual(export['body']['properties']['names']['minItems'],1)
        upload=self.ops['POST /api/services/docker/{server_id}/stacks/{name}/zip']
        self.assertFalse(upload['download'])
        self.assertTrue(any(field['type']=='file' and field['required'] for field in upload['fields']))

    def test_native_server_settings_use_existing_scoped_operations(self):
        source=(ROOT/'app/src/main/java/com/bot4vps/mobile/ui/servers/ServerSettingsScreen.kt').read_text()
        for action,suffix in re.findall(r'viewModel\.(action|list)\("([^"$]+)"',source):
            method='POST' if action=='action' else 'GET'
            methods=('GET',) if action=='list' else ('POST','PUT','DELETE')
            self.assertTrue(any(f'{item} /api/servers/{{server_id}}/quick-setup/{suffix}' in self.ops for item in methods),suffix)
        for suffix in ('firewall/install','firewall/enable','firewall/remove'):
            self.assertIn('backend',self.ops[f'POST /api/servers/{{server_id}}/quick-setup/{suffix}']['body']['required'])
        self.assertIn('target',self.ops['POST /api/servers/{server_id}/quick-setup/firewall/switch']['body']['required'])
        for suffix in ('fail2ban/start','fail2ban/stop','firewall/switch'):
            self.assertIn(f'POST /api/servers/{{server_id}}/quick-setup/{suffix}',self.ops)

    def test_regeneration_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'contract.json'
            subprocess.run([sys.executable,str(ROOT/'tools/generate_contract.py'),'--repo',str(REPO),'--output',str(output)],check=True,capture_output=True)
            self.assertEqual(json.loads(output.read_text()),self.contract)

if __name__=='__main__':unittest.main(verbosity=2)
