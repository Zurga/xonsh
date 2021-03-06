# -*- coding: utf-8 -*-
"""Directory stack and associated utilities for the xonsh shell."""
import os
import glob
import argparse
import builtins

from xonsh.lazyasd import lazyobject
from xonsh.tools import get_sep
from xonsh.events import events

DIRSTACK = []
"""A list containing the currently remembered directories."""


events.doc('on_chdir', """
on_chdir(olddir: str, newdir: str) -> None

Fires when the current directory is changed for any reason.
""")


def _get_cwd():
    try:
        return os.getcwd()
    except (OSError, FileNotFoundError):
        return None


def _change_working_directory(newdir):
    env = builtins.__xonsh_env__
    old = env['PWD']
    new = os.path.join(old, newdir)
    absnew = os.path.abspath(new)
    try:
        os.chdir(absnew)
    except (OSError, FileNotFoundError):
        if new.endswith(get_sep()):
            new = new[:-1]
        if os.path.basename(new) == '..':
            env['PWD'] = new
    else:
        if old is not None:
            env['OLDPWD'] = old
        if new is not None:
            env['PWD'] = absnew

    # Fire event if the path actually changed
    if old != env['PWD']:
        events.on_chdir.fire(old, env['PWD'])


def _try_cdpath(apath):
    # NOTE: this CDPATH implementation differs from the bash one.
    # In bash if a CDPATH is set, an unqualified local folder
    # is considered after all CDPATHs, example:
    # CDPATH=$HOME/src (with src/xonsh/ inside)
    # $ cd xonsh -> src/xonsh (whith xonsh/xonsh)
    # a second $ cd xonsh has no effects, to move in the nested xonsh
    # in bash a full $ cd ./xonsh is needed.
    # In xonsh a relative folder is allways preferred.
    env = builtins.__xonsh_env__
    cdpaths = env.get('CDPATH')
    for cdp in cdpaths:
        globber = builtins.__xonsh_expand_path__(os.path.join(cdp, apath))
        for cdpath_prefixed_path in glob.iglob(globber):
            return cdpath_prefixed_path
    return apath


def cd(args, stdin=None):
    """Changes the directory.

    If no directory is specified (i.e. if `args` is None) then this
    changes to the current user's home directory.
    """
    env = builtins.__xonsh_env__
    oldpwd = env.get('OLDPWD', None)
    cwd = env['PWD']

    if len(args) == 0:
        d = os.path.expanduser('~')
    elif len(args) == 1:
        d = os.path.expanduser(args[0])
        if not os.path.isdir(d):
            if d == '-':
                if oldpwd is not None:
                    d = oldpwd
                else:
                    return '', 'cd: no previous directory stored\n', 1
            elif d.startswith('-'):
                try:
                    num = int(d[1:])
                except ValueError:
                    return '', 'cd: Invalid destination: {0}\n'.format(d), 1
                if num == 0:
                    return None, None, 0
                elif num < 0:
                    return '', 'cd: Invalid destination: {0}\n'.format(d), 1
                elif num > len(DIRSTACK):
                    e = 'cd: Too few elements in dirstack ({0} elements)\n'
                    return '', e.format(len(DIRSTACK)), 1
                else:
                    d = DIRSTACK[num - 1]
            else:
                d = _try_cdpath(d)
    else:
        return '', 'cd takes 0 or 1 arguments, not {0}\n'.format(len(args)), 1
    if not os.path.exists(d):
        return '', 'cd: no such file or directory: {0}\n'.format(d), 1
    if not os.path.isdir(d):
        return '', 'cd: {0} is not a directory\n'.format(d), 1
    if not os.access(d, os.X_OK):
        return '', 'cd: permission denied: {0}\n'.format(d), 1
    # now, push the directory onto the dirstack if AUTO_PUSHD is set
    if cwd is not None and env.get('AUTO_PUSHD'):
        pushd(['-n', '-q', cwd])
    _change_working_directory(d)
    return None, None, 0


@lazyobject
def pushd_parser():
    parser = argparse.ArgumentParser(prog="pushd")
    parser.add_argument('dir', nargs='?')
    parser.add_argument('-n',
                        dest='cd',
                        help='Suppresses the normal change of directory when'
                        ' adding directories to the stack, so that only the'
                        ' stack is manipulated.',
                        action='store_false')
    parser.add_argument('-q',
                        dest='quiet',
                        help='Do not call dirs, regardless of $PUSHD_SILENT',
                        action='store_true')
    return parser


def pushd(args, stdin=None):
    """xonsh command: pushd

    Adds a directory to the top of the directory stack, or rotates the stack,
    making the new top of the stack the current working directory.
    """
    global DIRSTACK

    try:
        args = pushd_parser.parse_args(args)
    except SystemExit:
        return None, None, 1

    env = builtins.__xonsh_env__

    pwd = env['PWD']

    if env.get('PUSHD_MINUS', False):
        BACKWARD = '-'
        FORWARD = '+'
    else:
        BACKWARD = '+'
        FORWARD = '-'

    if args.dir is None:
        try:
            new_pwd = DIRSTACK.pop(0)
        except IndexError:
            e = 'pushd: Directory stack is empty\n'
            return None, e, 1
    elif os.path.isdir(args.dir):
        new_pwd = args.dir
    else:
        try:
            num = int(args.dir[1:])
        except ValueError:
            e = 'Invalid argument to pushd: {0}\n'
            return None, e.format(args.dir), 1

        if num < 0:
            e = 'Invalid argument to pushd: {0}\n'
            return None, e.format(args.dir), 1

        if num > len(DIRSTACK):
            e = 'Too few elements in dirstack ({0} elements)\n'
            return None, e.format(len(DIRSTACK)), 1
        elif args.dir.startswith(FORWARD):
            if num == len(DIRSTACK):
                new_pwd = None
            else:
                new_pwd = DIRSTACK.pop(len(DIRSTACK) - 1 - num)
        elif args.dir.startswith(BACKWARD):
            if num == 0:
                new_pwd = None
            else:
                new_pwd = DIRSTACK.pop(num - 1)
        else:
            e = 'Invalid argument to pushd: {0}\n'
            return None, e.format(args.dir), 1
    if new_pwd is not None:
        if args.cd:
            DIRSTACK.insert(0, os.path.expanduser(pwd))
            _change_working_directory(new_pwd)
        else:
            DIRSTACK.insert(0, os.path.expanduser(new_pwd))

    maxsize = env.get('DIRSTACK_SIZE')
    if len(DIRSTACK) > maxsize:
        DIRSTACK = DIRSTACK[:maxsize]

    if not args.quiet and not env.get('PUSHD_SILENT'):
        return dirs([], None)

    return None, None, 0


@lazyobject
def popd_parser():
    parser = argparse.ArgumentParser(prog="popd")
    parser.add_argument('dir', nargs='?')
    parser.add_argument('-n',
                        dest='cd',
                        help='Suppresses the normal change of directory when'
                        ' adding directories to the stack, so that only the'
                        ' stack is manipulated.',
                        action='store_false')
    parser.add_argument('-q',
                        dest='quiet',
                        help='Do not call dirs, regardless of $PUSHD_SILENT',
                        action='store_true')
    return parser


def popd(args, stdin=None):
    """
    xonsh command: popd

    Removes entries from the directory stack.
    """
    global DIRSTACK

    try:
        args = pushd_parser.parse_args(args)
    except SystemExit:
        return None, None, 1

    env = builtins.__xonsh_env__

    if env.get('PUSHD_MINUS'):
        BACKWARD = '-'
        FORWARD = '+'
    else:
        BACKWARD = '-'
        FORWARD = '+'

    if args.dir is None:
        try:
            new_pwd = DIRSTACK.pop(0)
        except IndexError:
            e = 'popd: Directory stack is empty\n'
            return None, e, 1
    else:
        try:
            num = int(args.dir[1:])
        except ValueError:
            e = 'Invalid argument to popd: {0}\n'
            return None, e.format(args.dir), 1

        if num < 0:
            e = 'Invalid argument to popd: {0}\n'
            return None, e.format(args.dir), 1

        if num > len(DIRSTACK):
            e = 'Too few elements in dirstack ({0} elements)\n'
            return None, e.format(len(DIRSTACK)), 1
        elif args.dir.startswith(FORWARD):
            if num == len(DIRSTACK):
                new_pwd = DIRSTACK.pop(0)
            else:
                new_pwd = None
                DIRSTACK.pop(len(DIRSTACK) - 1 - num)
        elif args.dir.startswith(BACKWARD):
            if num == 0:
                new_pwd = DIRSTACK.pop(0)
            else:
                new_pwd = None
                DIRSTACK.pop(num - 1)
        else:
            e = 'Invalid argument to popd: {0}\n'
            return None, e.format(args.dir), 1

    if new_pwd is not None:
        e = None
        if args.cd:
            _change_working_directory(new_pwd)

    if not args.quiet and not env.get('PUSHD_SILENT'):
        return dirs([], None)

    return None, None, 0


@lazyobject
def dirs_parser():
    parser = argparse.ArgumentParser(prog="dirs")
    parser.add_argument('N', nargs='?')
    parser.add_argument('-c',
                        dest='clear',
                        help='Clears the directory stack by deleting all of'
                        ' the entries.',
                        action='store_true')
    parser.add_argument('-p',
                        dest='print_long',
                        help='Print the directory stack with one entry per'
                        ' line.',
                        action='store_true')
    parser.add_argument('-v',
                        dest='verbose',
                        help='Print the directory stack with one entry per'
                        ' line, prefixing each entry with its index in the'
                        ' stack.',
                        action='store_true')
    parser.add_argument('-l',
                        dest='long',
                        help='Produces a longer listing; the default listing'
                        ' format uses a tilde to denote the home directory.',
                        action='store_true')
    return parser


def dirs(args, stdin=None):
    """xonsh command: dirs

    Displays the list of currently remembered directories.  Can also be used
    to clear the directory stack.
    """
    global DIRSTACK
    try:
        args = dirs_parser.parse_args(args)
    except SystemExit:
        return None, None

    env = builtins.__xonsh_env__
    dirstack = [os.path.expanduser(env['PWD'])] + DIRSTACK

    if env.get('PUSHD_MINUS'):
        BACKWARD = '-'
        FORWARD = '+'
    else:
        BACKWARD = '-'
        FORWARD = '+'

    if args.clear:
        DIRSTACK = []
        return None, None, 0

    if args.long:
        o = dirstack
    else:
        d = os.path.expanduser('~')
        o = [i.replace(d, '~') for i in dirstack]

    if args.verbose:
        out = ''
        pad = len(str(len(o) - 1))
        for (ix, e) in enumerate(o):
            blanks = ' ' * (pad - len(str(ix)))
            out += '\n{0}{1} {2}'.format(blanks, ix, e)
        out = out[1:]
    elif args.print_long:
        out = '\n'.join(o)
    else:
        out = ' '.join(o)

    N = args.N
    if N is not None:
        try:
            num = int(N[1:])
        except ValueError:
            e = 'Invalid argument to dirs: {0}\n'
            return None, e.format(N), 1

        if num < 0:
            e = 'Invalid argument to dirs: {0}\n'
            return None, e.format(len(o)), 1

        if num >= len(o):
            e = 'Too few elements in dirstack ({0} elements)\n'
            return None, e.format(len(o)), 1

        if N.startswith(BACKWARD):
            idx = num
        elif N.startswith(FORWARD):
            idx = len(o) - 1 - num
        else:
            e = 'Invalid argument to dirs: {0}\n'
            return None, e.format(N), 1

        out = o[idx]

    return out + '\n', None, 0
