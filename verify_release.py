"""Verify actual release artifacts, including startup from both Linux packages."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def digest(path):
    checksum=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): checksum.update(block)
    return checksum.hexdigest()


def verify(directory):
    root=Path(directory).resolve()
    version=Path(__file__).with_name('VERSION').read_text().strip()
    manifest=json.loads((root/'updates.json').read_text())
    assert manifest['product']=='Framecut' and manifest['version']==version
    assert set(manifest['artifacts'])=={'deb','appimage'}
    artifacts={}
    for kind,item in manifest['artifacts'].items():
        name=item['filename']; assert Path(name).name==name
        path=root/name; assert path.is_file() and path.stat().st_size>0
        assert digest(path)==item['sha256'], f'{kind}: manifest checksum'
        assert item['url']==f'https://github.com/mehdi-ki/framecut/releases/download/v{version}/{name}'
        artifacts[kind]=path
    sums={}
    for line in (root/'SHA256SUMS').read_text().splitlines():
        expected,name=line.split(maxsplit=1)
        assert Path(name).name==name and digest(root/name)==expected, name
        sums[name]=expected
    zip_path=root/f'Framecut-{version}-Linux.zip'
    assert set(sums)=={zip_path.name,'updates.json',*(p.name for p in artifacts.values())}
    modules=('app.py','core.py','preview.py','timeline.py','ux.py','workbench.py','SMOOTH_WORKFLOW.md')
    with zipfile.ZipFile(zip_path) as source:
        assert source.testzip() is None
        for name in modules: assert f'Framecut-{version}/{name}' in source.namelist()
    assert subprocess.check_output(['dpkg-deb','-f',str(artifacts['deb']),'Version'],text=True).strip()==version+'-1'
    with artifacts['appimage'].open('rb') as stream: header=stream.read(12)
    assert header[:4]==b'\x7fELF' and header[8:11]==b'AI\x02', 'Expected a real Type-2 AppImage'
    smoke="""
import tempfile
from PySide6.QtWidgets import QApplication
from app import Editor, APP_VERSION
a=QApplication([])
with tempfile.TemporaryDirectory() as state:
    w=Editor(state,recovery=False); w.show(); a.processEvents()
    assert w.inline_name is not None and w.performance_combo.count()==3
    w.dirty=False; w.close(); a.processEvents()
print('Package starts:',APP_VERSION)
"""
    with tempfile.TemporaryDirectory(prefix='framecut-verify-') as folder:
        stage=Path(folder); deb=stage/'deb'
        subprocess.run(['dpkg-deb','-x',str(artifacts['deb']),str(deb)],check=True)
        artifacts['appimage'].chmod(0o755)
        subprocess.run([str(artifacts['appimage']),'--appimage-extract'],cwd=stage,check=True,stdout=subprocess.DEVNULL)
        for package in (deb,stage/'squashfs-root'):
            application=package/'usr/lib/framecut'/version
            for name in modules: assert (application/name).is_file(),f'Missing {name} in {package.name}'
            subprocess.run([sys.executable,'-c',smoke],cwd=application,
                env={**os.environ,'QT_QPA_PLATFORM':'offscreen','FRAMECUT_DISABLE_UPDATE_CHECK':'1'},check=True,timeout=30)
    print(f'Framecut {version}: package contents, startup, manifest and all checksums verified.')


if __name__=='__main__':
    verify(sys.argv[1])
