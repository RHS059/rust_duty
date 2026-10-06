"""Synthetic fixed-artifact retrieval controls; no network or game execution."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import fetch_legacy_facade_reference as fetcher


class LegacyReferenceFetchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root = Path(temp.name)
        ref = fetcher.REFERENCE
        self.run = {'id':ref['run_id'],'run_attempt':ref['run_attempt'],'run_number':ref['run_number'],
            'head_sha':ref['source_commit'],'head_branch':'main','event':'push','status':'completed',
            'conclusion':'success','path':'.github/workflows/build.yml',
            'repository':{'full_name':ref['repository']},'head_repository':{'full_name':ref['repository']}}
        self.artifact = {'id':ref['artifact_id'],
            'name':f"Rust-Duty-{fetcher.REFERENCE_IDENTITY['display_version']}-Windows-x64",
            'size_in_bytes':ref['zip_bytes'],'expired':False,'digest':'sha256:'+ref['zip_sha256'],
            'workflow_run':{'id':ref['run_id'],'head_sha':ref['source_commit'],'head_branch':'main'}}

    def test_fixed_metadata_control_omits_unvalidated_urls(self):
        self.run['url'] = 'https://example.invalid/run'
        self.artifact['archive_download_url'] = 'https://example.invalid/signed?token=never-retain'
        result = fetcher.metadata_identity(self.run,self.artifact)
        self.assertNotIn('https://',json.dumps(result));self.assertNotIn('never-retain',json.dumps(result))

    def test_wrong_run_source_attempt_status_repository_or_numeric_type_fails(self):
        for field,value in [('id',1),('head_sha','a'*40),('run_attempt',2),('run_attempt',True),
                            ('run_number',240),('head_branch','other'),('event','pull_request'),
                            ('status','in_progress'),('conclusion','failure'),('path','other.yml')]:
            run = copy.deepcopy(self.run);run[field] = value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                fetcher.metadata_identity(run,self.artifact)
        for field in ('repository','head_repository'):
            run = copy.deepcopy(self.run);run[field]['full_name'] = 'other/repo'
            with self.assertRaises(ValueError):fetcher.metadata_identity(run,self.artifact)

    def test_wrong_artifact_id_digest_size_name_or_expiry_fails(self):
        for field,value in [('id',1),('digest','sha256:'+'0'*64),('size_in_bytes',1),
                            ('name','another artifact'),('expired',True),('expired',0)]:
            artifact = copy.deepcopy(self.artifact);artifact[field] = value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                fetcher.metadata_identity(self.run,artifact)
        for field,value in [('id',1),('head_sha','b'*40),('head_branch','other')]:
            artifact = copy.deepcopy(self.artifact);artifact['workflow_run'][field] = value
            with self.assertRaises(ValueError):fetcher.metadata_identity(self.run,artifact)

    def test_fixed_api_calls_and_download_share_only_the_ephemeral_token(self):
        output = self.root/'reference';token = 'job-token-sentinel'
        with patch.object(fetcher.retrieval,'api_json',side_effect=[self.run,self.artifact]) as api, \
             patch.object(fetcher.retrieval,'download') as download:
            result = fetcher.fetch(output,token)
        ref = fetcher.REFERENCE;prefix = '/repos/RHS059/rust_duty'
        self.assertEqual([call.args for call in api.call_args_list],[
            (f"{prefix}/actions/runs/{ref['run_id']}/attempts/{ref['run_attempt']}",token),
            (f"{prefix}/actions/artifacts/{ref['artifact_id']}",token)])
        download.assert_called_once_with(f"{prefix}/actions/artifacts/{ref['artifact_id']}/zip",token,
            output/f"{ref['artifact_id']}.zip",ref['zip_bytes'],ref['zip_sha256'])
        self.assertTrue(result['passed']);self.assertTrue(result['zip_digest_verified'])
        self.assertFalse(result['extracted']);self.assertFalse(result['executed'])
        saved = (output/'reference-metadata.json').read_text()
        self.assertNotIn(token,saved);self.assertNotIn('https://',saved)

    def test_metadata_failure_never_downloads_or_selects_another_artifact(self):
        self.artifact['expired'] = True
        with patch.object(fetcher.retrieval,'api_json',side_effect=[self.run,self.artifact]), \
             patch.object(fetcher.retrieval,'download') as download:
            with self.assertRaisesRegex(ValueError,'no alternate retrieval'):
                fetcher.fetch(self.root/'reference','job-token')
            download.assert_not_called()
        report = json.loads((self.root/'reference/reference-metadata.json').read_text())
        self.assertFalse(report['passed']);self.assertFalse(report['zip_digest_verified'])

    def test_http_or_digest_failure_has_no_retry_and_no_secret_in_report(self):
        output = self.root/'reference'
        with patch.object(fetcher.retrieval,'api_json',side_effect=[self.run,self.artifact]), \
             patch.object(fetcher.retrieval,'download',side_effect=ValueError('https://blob.invalid/signed?token=secret')) as download:
            with self.assertRaisesRegex(ValueError,'Pinned historical'):
                fetcher.fetch(output,'job-token')
            self.assertEqual(download.call_count,1)
        saved = (output/'reference-metadata.json').read_text()
        self.assertNotIn('https://',saved);self.assertNotIn('secret',saved);self.assertNotIn('job-token',saved)

    def test_missing_token_or_existing_output_fails_before_api(self):
        with patch.object(fetcher.retrieval,'api_json') as api:
            with self.assertRaises(ValueError):fetcher.fetch(self.root/'new',None)
            with self.assertRaises(ValueError):fetcher.fetch(self.root,'job-token')
            api.assert_not_called()

    def test_main_sanitizes_retrieval_exception(self):
        stream = io.StringIO()
        with patch.dict(os.environ,{'GITHUB_TOKEN':'secret'}), \
             patch.object(fetcher,'fetch',side_effect=OSError('https://private.invalid/?secret')),redirect_stdout(stream):
            result = fetcher.main(['--output',str(self.root/'reference')])
        self.assertEqual(result,1);self.assertNotIn('https://',stream.getvalue());self.assertNotIn('secret',stream.getvalue())


if __name__ == '__main__':unittest.main()
