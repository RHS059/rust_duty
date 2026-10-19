"""One-time, exact-branch publication of the reopened metadata-only repair."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

BRANCH = 'recovery/canonical-runtime-integration-20261019'
BASE = 'd133ec0fb21aad521895d3f715c85382c088159c'
PATHS = ['assets/authoring/weapon_animations.blend',
         'assets/authoring/weapon_animations.verification.json']


def require(ok, message):
    if not ok: raise ValueError(message)


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def main():
    token = os.environ.pop('CANONICAL_PUSH_TOKEN')
    head = os.environ['GITHUB_SHA']
    require(os.environ['GITHUB_REF'] == 'refs/heads/' + BRANCH, 'wrong branch')
    require(git('rev-parse','HEAD') == head and git('rev-parse','HEAD^') == BASE, 'wrong head/base')
    require(git('remote','get-url','origin') == 'https://github.com/RHS059/rust_duty', 'wrong origin')
    require(git('ls-remote','origin','refs/heads/'+BRANCH).split()[0] == head, 'branch advanced')
    require(sorted(git('diff','--name-only').splitlines()) == PATHS, 'unexpected changed paths')
    require(not git('diff','--cached','--name-only') and not git('ls-files','--others','--exclude-standard'), 'unexpected staged/untracked paths')
    for name in PATHS:
        path=Path(name)
        require(path.is_file() and not path.is_symlink() and not any(p.is_symlink() for p in path.parents), 'unsafe output')
        require(0 < path.stat().st_size < 100*1024*1024, 'invalid output size')
    receipt=json.loads(Path(PATHS[1]).read_text())
    sha=hashlib.sha256(Path(PATHS[0]).read_bytes()).hexdigest()
    require(receipt['status']=='PASS' and receipt['canonical_sha256']==sha, 'verification mismatch')
    require(receipt['authoring_usability_repair']['input_sha256']=='d86fcb25ef625922c4cce4dcec1ec9fb228d4ea6fd769647e424f2b6eec43d2e', 'wrong source')
    git('add','--',*PATHS)
    require(sorted(git('diff','--cached','--name-only').splitlines()) == PATHS, 'staged allowlist differs')
    subprocess.run(['git','-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com','commit','-m','Enable canonical source NLA playback and descriptive Action labels'],check=True)
    require(git('rev-parse','HEAD^')==head, 'wrong commit parent')
    require(git('ls-remote','origin','refs/heads/'+BRANCH).split()[0] == head, 'branch advanced before push')
    env=dict(os.environ)
    env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
               GIT_CONFIG_VALUE_0='AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode(), GIT_TERMINAL_PROMPT='0')
    subprocess.run(['git','push','origin','HEAD:refs/heads/'+BRANCH],check=True,env=env)
    require(git('ls-remote','origin','refs/heads/'+BRANCH).split()[0]==git('rev-parse','HEAD'), 'readback differs')
    print(json.dumps({'commit':git('rev-parse','HEAD'),'canonical_sha256':sha,'files':PATHS}))

if __name__ == '__main__': main()
