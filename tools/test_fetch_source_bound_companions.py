import hashlib
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import fetch_source_bound_companions as fetcher


class FetchTests(unittest.TestCase):
    def test_credentials_stay_at_api_and_not_redirect(self):
        request = fetcher.api_request('/repos/RHS059/rust_duty/actions/artifacts/1/zip', 'test-placeholder')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-placeholder')
        redirect = fetcher.redirected_request('https://example.blob.core.windows.net/path?sig=fixture')
        self.assertIsNone(redirect.get_header('Authorization'))
        for bad in ('http://example/path', 'https://user:password@example/path', 'file:///tmp/a', 'https://example:8443/a'):
            with self.assertRaises(ValueError):
                fetcher.redirected_request(bad)
        with self.assertRaises(ValueError):
            fetcher.api_request('/repos/other/repository/actions/artifacts/1', 'test-placeholder')

    def test_exact_origin_identity_and_digest_required(self):
        expected = {'artifact_id': 1, 'name': 'pack', 'size_bytes': 3, 'zip_sha256': 'a' * 64}
        origin = {'run_id': 2, 'head_sha': 'b' * 40}
        metadata = {'id': 1, 'name': 'pack', 'size_in_bytes': 3, 'expired': False,
                    'digest': 'sha256:' + 'a' * 64, 'workflow_run': {'id': 2, 'head_sha': 'b' * 40}}
        fetcher.check_artifact(metadata, expected, origin)
        for key, value in [('id', 3), ('name', 'other'), ('size_in_bytes', 4), ('expired', True), ('digest', 'sha256:' + 'c' * 64)]:
            changed = dict(metadata, **{key: value})
            with self.assertRaises(ValueError):
                fetcher.check_artifact(changed, expected, origin)
        with self.assertRaises(ValueError):
            fetcher.check_artifact(dict(metadata, workflow_run={'id': 3, 'head_sha': 'b' * 40}), expected, origin)

    def test_download_bounds_digest_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'download.zip'
            with patch.object(fetcher, 'open_api', return_value=io.BytesIO(b'abc')):
                fetcher.download('/repos/RHS059/rust_duty/test', 'fixture', output, 3, hashlib.sha256(b'abc').hexdigest())
            self.assertEqual(output.read_bytes(), b'abc')
            with patch.object(fetcher, 'open_api', return_value=io.BytesIO(b'abc')):
                with self.assertRaises(FileExistsError):
                    fetcher.download('/repos/RHS059/rust_duty/test', 'fixture', output, 3, hashlib.sha256(b'abc').hexdigest())
            for data, size, sha in [(b'abcd', 3, hashlib.sha256(b'abc').hexdigest()), (b'ab', 3, hashlib.sha256(b'abc').hexdigest()), (b'abc', 3, '0'*64)]:
                output.unlink(missing_ok=True)
                with patch.object(fetcher, 'open_api', return_value=io.BytesIO(data)):
                    with self.assertRaises(ValueError):
                        fetcher.download('/repos/RHS059/rust_duty/test', 'fixture', output, size, sha)


if __name__ == '__main__':
    unittest.main()
