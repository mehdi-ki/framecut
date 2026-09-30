"""Tests for Linux packaging metadata and the opt-in update client."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from update_system import (DEFAULT_UPDATE_MANIFEST_URL, UPDATE_DISABLE_ENV,
                           UPDATE_MANIFEST_ENV, configured_manifest_url,
                           download_verified, fetch_manifest, is_newer,
                           select_artifact, sha256_file, update_checks_disabled,
                           version_key)


class DeliveryTest(unittest.TestCase):
    def test_default_update_manifest_and_disable_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            clean_env={
                "XDG_CONFIG_HOME": directory,
                UPDATE_MANIFEST_ENV: "",
                UPDATE_DISABLE_ENV: "",
            }
            with patch.dict(os.environ, clean_env, clear=False):
                self.assertEqual(configured_manifest_url(), DEFAULT_UPDATE_MANIFEST_URL)
                self.assertFalse(update_checks_disabled())
            with patch.dict(os.environ, {**clean_env, UPDATE_DISABLE_ENV: "1"}, clear=False):
                self.assertTrue(update_checks_disabled())
                self.assertEqual(configured_manifest_url(), "")

    def test_versions_are_numeric_and_padded(self):
        self.assertEqual(version_key('3.10.0'), (3, 10, 0))
        self.assertTrue(is_newer('3.10', '3.9'))
        self.assertFalse(is_newer('3.6.0', '3.6'))

    def test_manifest_selects_checksum_pinned_artifact(self):
        manifest={
            'product':'Framecut',
            'version':'3.7',
            'artifacts':{
                'deb':{'url':'https://example.invalid/framecut.deb','sha256':'a'*64},
                'appimage':{'url':'https://example.invalid/framecut.AppImage','sha256':'b'*64},
            },
        }
        chosen=select_artifact(manifest,'3.6',('deb','appimage'))
        self.assertEqual(chosen['kind'],'deb')
        self.assertIsNone(select_artifact(manifest,'3.7'))

    def test_local_manifest_and_verified_download_are_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'payload.bin'; source.write_bytes(b'framecut release payload')
            digest=sha256_file(source)
            manifest=root/'updates.json'
            manifest.write_text(json.dumps({'product':'Framecut','version':'3.7','artifacts':{
                'deb':{'filename':'framecut_3.7_amd64.deb','url':source.as_uri(),'sha256':digest}
            }}),encoding='utf-8')
            loaded=fetch_manifest(str(manifest))
            artifact=select_artifact(loaded,'3.6',('deb',))
            target=root/'cache'/'framecut.deb'
            result=download_verified(artifact['url'],artifact['sha256'],target)
            self.assertEqual(result,target)
            self.assertEqual(target.read_bytes(),source.read_bytes())

            with self.assertRaisesRegex(ValueError,'Prüfsumme'):
                download_verified(artifact['url'],'0'*64,root/'cache'/'bad.deb')
            self.assertFalse((root/'cache'/'bad.deb').exists())

    def test_packaging_metadata_has_icon_and_framecut_mime(self):
        root=Path(__file__).parent
        self.assertTrue((root/'framecut.svg').is_file())
        self.assertIn('application/x-framecut', (root/'application-x-framecut.xml').read_text(encoding='utf-8'))
        desktop=(root/'framecut.desktop').read_text(encoding='utf-8')
        self.assertIn('Icon=framecut',desktop)
        self.assertIn('MimeType=application/x-framecut;',desktop)


if __name__=='__main__':
    unittest.main()
