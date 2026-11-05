#!/usr/bin/env python3
"""Run Ocarina with the recovered Mac settings; --print-command changes no files.

Usage: python3 scripts/play_oot.py /path/to/0400486024DEC000_build
Build first with build_ipa_from_nsp.py --platform mac --env-file <profile>/mac.env.
Game data and saves stay beside the NUP, outside the source checkout.
"""
import argparse
import os
from pathlib import Path
import shlex
import sys

GAME = '0400486024DEC000'
REPO = Path(__file__).resolve().parents[1]
PRESET = REPO / 'dm/games' / GAME / 'mac.env'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path, help='the Mac build folder beside the NUP')
    parser.add_argument('--save', type=Path, help='existing committed save folder (never moved or overwritten)')
    parser.add_argument('--print-command', action='store_true', help='show the settings and command without launching or writing files')
    args = parser.parse_args()
    build = args.build.expanduser().resolve()
    if build.name != f'{GAME}_build':
        parser.error(f'expected {GAME}_build, got {build.name}')
    settings = {}
    for line in PRESET.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            key, value = line.split('=', 1)
            settings[key] = value
    # Pick one version for both rewritten modules and RomFS, never independent globs.
    versions = [p for p in build.glob('patched_v*') if p.is_dir() and p.name[9:].isdigit()]
    patched = max(versions, key=lambda p: int(p.name[9:])) if versions else build / 'patched_v131072'
    extracted = build / 'extract' / patched.name.removeprefix('patched_')
    romfs = extracted / 'RomFS.img'
    if not romfs.is_file() and (extracted / 'RomFS').is_dir():
        romfs = extracted / 'RomFS'
    profile = build / 'profile' / GAME
    if not profile.is_dir():
        profile = REPO / 'dm/games' / GAME
    saved = build.parent / f'{GAME}_saves' / 'save'
    save = args.save.expanduser().resolve() if args.save else saved if saved.is_dir() else build / 'run/save'
    settings.update(DM_ROOT=str(build), DM_ROMFS=str(romfs), DM_SAVE=str(save),
                    DM_TEMP=str(build / 'run/temp'), DM_MSL_DIR=str(build / 'shader/cache'),
                    DM_FONT_DIR=str(build / 'font'), DM_NVN_SHMAP=str(profile / 'shader_map.tsv'),
                    DM_CTL=str(build / 'run/ctl.txt'))
    host = build / 'tools/dmhost'
    if args.print_command:
        print(f'cd {shlex.quote(str(build / "run"))} && ' + ' '.join(f'{k}={shlex.quote(v)}' for k, v in settings.items())
              + ' ' + shlex.join([str(host), str(patched)]))
        return 0
    required = [host, patched, romfs, build / 'font', profile / 'shader_map.tsv']
    if args.save and not save.is_dir():
        parser.error(f'save folder does not exist: {save}')
    missing = [str(p) for p in required if not p.exists()]
    if not any((build / 'shader/cache').glob('b-*')):
        missing.append(str(build / 'shader/cache/b-<chain>'))
    if missing:
        print('Mac build is incomplete; missing:\n' + '\n'.join(missing), file=sys.stderr)
        print('Rebuild with the tool venv and the saved preset:\n' + shlex.join([
            sys.executable, str(REPO / 'scripts/build_ipa_from_nsp.py'), str(build.parent),
            '--platform', 'mac', '--env-file', str(PRESET)]), file=sys.stderr)
        return 1
    for path in (save, build / 'run/temp'):
        path.mkdir(parents=True, exist_ok=True)
    ctl = Path(settings['DM_CTL'])
    ctl.write_text('')   # old diagnostic commands must not replay at the next start
    os.chdir(build / 'run')
    os.execve(host, [str(host), str(patched)], dict(os.environ, **settings))


if __name__ == '__main__':
    sys.exit(main())
