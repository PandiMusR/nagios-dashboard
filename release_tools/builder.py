import argparse
import ast
import io
import os
from pathlib import Path
import subprocess
import tarfile

from .common import COHORT, MAX_FILE, ReleaseError, canonical, digest, hex_string


def git(repo, *arguments):
    result = subprocess.run(['git', '-C', str(repo), *arguments], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout


def build(repo, commit, output):
    hex_string(commit, 40)
    resolved = git(repo, 'rev-parse', '--verify', commit + '^{commit}').decode().strip()
    if resolved != commit:
        raise ReleaseError('an exact immutable commit is required')
    epoch = int(git(repo, 'show', '-s', '--format=%ct', commit))
    manifest = {'schema': 1, 'commit': commit, 'cohort': 'pr2-runtime', 'files': {}}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in COHORT:
            tree = git(repo, 'ls-tree', commit, '--', name).decode().strip()
            if not tree.startswith('100644 blob\t') and not tree.startswith('100644 blob '):
                raise ReleaseError('required source is missing or not a regular nonexecutable file')
            if int(git(repo, 'cat-file', '-s', commit + ':' + name)) > MAX_FILE:
                raise ReleaseError('source exceeds size limit')
            data = git(repo, 'show', commit + ':' + name)
            if len(data) > MAX_FILE:
                raise ReleaseError('source exceeds size limit')
            ast.parse(data, filename=name)
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mtime = epoch
            member.mode = 0o644
            member.uid = member.gid = 0
            archive.addfile(member, io.BytesIO(data))
            manifest['files'][name] = {'sha256': digest(data), 'size': len(data),
                                       'uid': 0, 'gid': 0, 'mode': 0o644}
    artifact = buffer.getvalue()
    manifest['artifact_sha256'] = digest(artifact)
    manifest['artifact_size'] = len(artifact)
    destination = Path(output)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in (('release.tar', artifact), ('manifest.json', canonical(manifest))):
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
    return manifest


def main():
    parser = argparse.ArgumentParser(description='Build the five-file PR #2 cohort from Git objects')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    manifest = build(args.repo, args.commit, args.output)
    print(manifest['artifact_sha256'])


if __name__ == '__main__':
    main()
