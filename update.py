#!/usr/bin/env python3
#
# Copyright (C) 2016 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Downloads simpleperf prebuilts from the build server."""
import argparse
import glob
import logging
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import textwrap
from typing import List, Union


THIS_DIR = os.path.realpath(os.path.dirname(__file__))


class InstallEntry(object):
    def __init__(self, target, name, install_path, need_strip=False):
        self.target = target
        self.name = name
        self.install_path = install_path
        self.need_strip = need_strip


MINGW = 'local:../../prebuilts/gcc/linux-x86/host/x86_64-w64-mingw32-4.8/x86_64-w64-mingw32/'
bin_install_list = [
    # simpleperf on device.
    InstallEntry('MODULES-IN-system-extras-simpleperf',
                 'simpleperf/android/arm64/simpleperf_ndk64',
                 'android/arm64/simpleperf'),
    InstallEntry('MODULES-IN-system-extras-simpleperf_arm',
                 'simpleperf/android/arm/simpleperf_ndk',
                 'android/arm/simpleperf'),
    InstallEntry('MODULES-IN-system-extras-simpleperf_x86',
                 'simpleperf/android/x86_64/simpleperf_ndk64',
                 'android/x86_64/simpleperf'),
    InstallEntry('MODULES-IN-system-extras-simpleperf_x86',
                 'simpleperf/android/x86/simpleperf_ndk',
                 'android/x86/simpleperf'),

    # simpleperf on host. Linux and macOS are 64-bit only these days.
    InstallEntry('MODULES-IN-system-extras-simpleperf',
                 'simpleperf/linux/x86_64/simpleperf_ndk64',
                 'linux/x86_64/simpleperf', True),
    InstallEntry('MODULES-IN-system-extras-simpleperf_mac',
                 'simpleperf/darwin/x86_64/simpleperf_ndk64',
                 'darwin/x86_64/simpleperf'),
    InstallEntry('MODULES-IN-system-extras-simpleperf',
                 'simpleperf/windows/x86_64/simpleperf_ndk64.exe',
                 'windows/x86_64/simpleperf.exe', True),

    # libsimpleperf_report.so on host
    InstallEntry('MODULES-IN-system-extras-simpleperf',
                 'simpleperf/linux/x86_64/libsimpleperf_report.so',
                 'linux/x86_64/libsimpleperf_report.so', True),
    InstallEntry('MODULES-IN-system-extras-simpleperf_mac',
                 'simpleperf/darwin/x86_64/libsimpleperf_report.dylib',
                 'darwin/x86_64/libsimpleperf_report.dylib'),
    InstallEntry('MODULES-IN-system-extras-simpleperf',
                 'simpleperf/windows/x86_64/libsimpleperf_report.dll',
                 'windows/x86_64/libsimpleperf_report.dll', True),

    # libwinpthread-1.dll on windows host
    InstallEntry(MINGW + '/bin/libwinpthread-1.dll', 'libwinpthread-1.dll',
                 'windows/x86_64/libwinpthread-1.dll', False),
]

script_install_entry = InstallEntry(
    'MODULES-IN-system-extras-simpleperf', 'simpleperf/simpleperf_script.zip',
    'simpleperf_script.zip')


def logger():
    """Returns the main logger for this module."""
    return logging.getLogger(__name__)


def check_call(cmd: Union[str, List[str]]):
    """Proxy for subprocess.check_call with logging."""
    if isinstance(cmd, list):
        cmd = shlex.join(cmd)
    logger().debug('check_call `%s`', cmd)
    subprocess.run(cmd, shell=True, check=True)


def remove(path: Union[str, Path]):
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path.as_posix())
    else:
        path.unlink()


def fetch_artifact(branch, build, target, pattern):
    """Fetches and artifact from the build server."""
    logger().info('Fetching %s from %s %s (artifacts matching %s)', build,
                  target, branch, pattern)
    if target.startswith('local:'):
        shutil.copyfile(target[6:], pattern)
        return
    fetch_artifact_path = '/google/data/ro/projects/android/fetch_artifact'
    cmd = [fetch_artifact_path, '--branch', branch, '--target', target,
           '--bid', build, pattern]
    check_call(cmd)


def start_branch(build):
    """Creates a new branch in the project."""
    branch_name = 'update-' + (build or 'latest')
    logger().info('Creating branch %s', branch_name)
    check_call(['repo', 'start', branch_name, '.'])


def commit(branch, build, add_paths):
    """Commits the new prebuilts."""
    logger().info('Making commit')
    check_call(['git', 'add'] + add_paths)
    message = textwrap.dedent("""\
        Update NDK prebuilts to build {build}.

        Taken from branch {branch}.""").format(branch=branch, build=build)
    check_call(['git', 'commit', '-m', message])


def list_prebuilts() -> List[str]:
    """List all prebuilts in current directory."""
    result = []
    for d in ['app_api', 'bin', 'doc', 'inferno', 'proto', 'purgatorio', 'test', 'testdata']:
        if os.path.isdir(d):
            result.append(d)
    result += glob.glob('*.py') + glob.glob('*.js')
    result.remove('update.py')
    result += ['inferno.sh', 'inferno.bat']
    return result


def remove_old_release():
    """Removes the old prebuilts."""
    old_prebuilts = list_prebuilts()
    if not old_prebuilts:
        return
    logger().info('Removing old prebuilts %s', old_prebuilts)
    check_call(['git', 'rm', '-rf', '--ignore-unmatch'] + old_prebuilts)

    # Need to check again because git won't remove directories if they have
    # non-git files in them.
    for prebuilt in old_prebuilts:
        remove(prebuilt)


def install_new_release(branch, build):
    """Installs the new release."""
    for entry in bin_install_list:
        install_entry(branch, build, 'bin', entry)
    install_entry(branch, build, '.', script_install_entry)
    unzip_simpleperf_scripts(script_install_entry.install_path)
    install_repo_prop(branch, build)


def install_entry(branch, build, install_dir, entry):
    """Installs one prebuilt file specified by entry."""
    target = entry.target
    name = entry.name
    install_path = os.path.join(install_dir, entry.install_path)
    need_strip = entry.need_strip

    fetch_artifact(branch, build, target, name)
    name = os.path.basename(name)
    exe_stat = os.stat(name)
    os.chmod(name, exe_stat.st_mode | stat.S_IEXEC)
    if need_strip:
        check_call(['strip', name])
    dir = os.path.dirname(install_path)
    if not os.path.isdir(dir):
        os.makedirs(dir)
    shutil.move(name, install_path)


def unzip_simpleperf_scripts(zip_path: str):
    check_call('unzip %s' % zip_path)
    remove(zip_path)

    # Move scripts.
    for sub_path in Path('scripts').iterdir():
        if sub_path.name not in ['bin', 'pylintrc', 'update.py']:
            shutil.move(sub_path, '.')
    remove('scripts')
    remove('inferno/Android.bp')
    remove('CONTRIBUTING.md')

    # Move proto files.
    proto_dir = Path('proto')
    proto_dir.mkdir()
    for sub_path in Path.cwd().iterdir():
        if sub_path.suffix == '.proto':
            shutil.move(sub_path, proto_dir)

    # Build testdata.
    testdata_dir = Path('test/testdata')
    testdata_dir.mkdir()
    for source_dir in ['demo', 'runtest', 'testdata', 'test/script_testdata']:
        for sub_path in Path(source_dir).iterdir():
            shutil.move(sub_path, testdata_dir)
        remove(source_dir)
    remove(testdata_dir / 'Android.bp')


def install_repo_prop(branch, build):
    """Installs the repo.prop from the build for auditing."""
    # We took everything from the same build number, so we only need the
    # repo.prop from one of our targets.
    fetch_artifact(branch, build, 'MODULES-IN-system-extras-simpleperf', 'repo.prop')


def get_args():
    """Parses and returns command line arguments."""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        '-b', '--branch', default='aosp-simpleperf-release',
        help='Branch to pull build from.')
    parser.add_argument('--build', required=True, help='Build number to pull.')
    parser.add_argument(
        '--use-current-branch', action='store_true',
        help='Perform the update in the current branch. Do not repo start.')
    parser.add_argument(
        '-v', '--verbose', action='count', default=0,
        help='Increase output verbosity.')

    return parser.parse_args()


def main():
    """Program entry point."""
    os.chdir(THIS_DIR)

    args = get_args()
    verbose_map = (logging.WARNING, logging.INFO, logging.DEBUG)
    verbosity = args.verbose
    if verbosity > 2:
        verbosity = 2
    logging.basicConfig(level=verbose_map[verbosity])

    if not args.use_current_branch:
        start_branch(args.build)
    remove_old_release()
    install_new_release(args.branch, args.build)
    artifacts = ['repo.prop'] + list_prebuilts()
    commit(args.branch, args.build, artifacts)


if __name__ == '__main__':
    main()
