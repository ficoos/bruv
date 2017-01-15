#!/bin/env python3

import ast
import cmd
import sys
import os
import re
import json
import fcntl
import termios
import time
import struct
import argparse
import getpass

import paramiko
from jinja2 import Template

from gerrit import (
    QueryOptions,
    Gerrit,
    GerritError,
)

import pickle
try:
    import anydbm as dbm
except ImportError:
    import dbm


def arg2lambda(arg):
    mod = ast.parse('target = lambda change: change')
    user = ast.parse(arg)
    mod.body[0].value.body = user.body[0].value
    comp_filter = compile(mod, '<string>', 'exec')
    ctx = {}
    exec(comp_filter, {}, ctx)
    return ctx['target']

def arg2mapfunc(arg):
    mod = ast.parse('def target(change): pass')
    user = ast.parse(arg)
    mod.body[0].body = user.body
    mod.body[0].body.append(ast.Return(ast.Name("change", ast.Load())))
    ast.fix_missing_locations(mod)
    comp_filter = compile(mod, '<string>', 'exec')
    ctx = {}
    exec(comp_filter, {}, ctx)
    return ctx['target']


class BruvShell(cmd.Cmd):
    intro = 'Welcome to the bruv shell.   Type help or ? to list commands.\n'
    prompt = '(bruv) '

    def __init__(self, completekey='tab', stdin=None, stdout=None):
        if stdin is not None:
            self.intro = None
            self.prompt = ''
            self.use_rawinput = False

        super(BruvShell, self).__init__(completekey, stdin, stdout)
        self.data = []
        self.query = ''
        self.host = 'review.openstack.org'
        self.port = 29418
        self.username = getpass.getuser()
        self.pkey_path = os.path.expanduser('~/.ssh/id_rsa')

    def _get_private_key(self):
        agent = paramiko.agent.Agent()
        keys_by_path = {key.get_name(): key for key in agent.get_keys()}
        if self.pkey_path in keys_by_path:
            return keys_by_path[self.pkey_path]

        pkey = paramiko.RSAKey(filename=self.pkey_path)
        return pkey

    def default(self, line):
        # Handle CTRL+D
        if line == "EOF":
            print()
            return self.do_exit(None)

        cmd, arg, line = self.parseline(line)
        if cmd == "q":
            cmd == "query"

        if cmd == "r":
            cmd == "refresh"

        if cmd == "p":
            cmd == "print"

        func = [getattr(self, n)
                for n in self.get_names() if n.startswith('do_' + cmd)]
        if func:
            func[0](arg)

    def do_query(self, arg):
        'Gather data for a query'
        self.query = arg
        self.do_refresh(None)

    def do_set(self, arg):
        "Set a configuration value"
        args = arg.split()
        if len(args) != 2:
            print("Could not parse command")
            print("usage: set <key> <value>")
            return

        if args[0] in ("user"):
            self.username = args[1]
        elif args[0] in ("pkey",):
            self.pkey_path = os.path.expanduser(args[1])
        elif args[0] in ("host",):
            self.host = arg[1]
        elif args[0] in ("port",):
            try:
                self.port = int(arg[1])
            except:
                print("Invalid port number")
        else:
            print("No such configuration")

    def complete_set(self, text, line, begidx, endidx):
        # We add '@' as a hack to accurately count words
        args = (line + '@').split()
        if len(args) > 2:
            return

        return [entry
                for entry in ("user", "host", "port", "pkey")
                if entry.startswith(text)]

    def do_filter(self, arg):
        'Create a simple filter for current data set'
        user_filter = arg2lambda(arg)
        self.data = filter(user_filter, self.data)

    def do_map(self, arg):
        'Create a simpler mapper for current data set'
        user_mapper = arg2mapfunc(arg)
        self.data = map(user_mapper, self.data)

    def do_refresh(self, arg):
        'Refresh data for last query'
        pkey = self._get_private_key()
        try:
            g = Gerrit(self.host, self.port, self.username, pkey)
            changes = g.query(self.query,
                              options=[QueryOptions.Comments,
                                       QueryOptions.CurrentPatchSet,
                                       QueryOptions.CommitMessage])

            changes = map(remove_jenkins_comments, changes)
            changes = map(add_last_checked_information, changes)
            #changes = map(mark_is_read, changes)
            changes = map(extract_headers, changes)
            changes = map(does_relate_to_bug, changes)
            changes = map(is_spec, changes)

            self.data = list(changes)

            print("%d results" % (len(self.data),))
        except GerritError as e:
            print(e.message.strip())
        except Exception as e:
            print(e)

    def do_print(self, arg):
        'Print data from query'
        template = Template(open('list.j2').read())
        print(template.render(changes=self.data))

    def do_exit(self, arg):
        'Exit the bruv shell'
        self.close()
        return True

    def close(self):
        pass


def get_terminal_size():
    env = os.environ

    def ioctl_GWINSZ(fd):
        try:
            cr = struct.unpack(
                'hh',
                fcntl.ioctl(fd, termios.TIOCGWINSZ, '1234')
            )
        except:
            return

        return cr

    cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not cr:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            cr = ioctl_GWINSZ(fd)
            os.close(fd)
        except:
            pass

    if not cr:
        cr = (env.get('LINES', 25), env.get('COLUMNS', 80))

    return int(cr[1]), int(cr[0])


conf = json.load(open(os.path.expanduser("~/.bruvrc")))

pkey_path = os.path.expanduser(conf.get("private_key", "~/.ssh/id_rsa"))
username = conf.get("username", "john")
host = conf.get("host", "review.openstack.org")
port = conf.get("port", 29418)
query = conf.get("query", "")
template_path = str(conf.get("template_file", "display.tmpl"))
db_path = str(conf.get("db_file", "bruv.db"))

PATCH_SET_INFO_RE = re.compile(r"^(?:Patch Set|Uploaded patch set) ([\d]+)")
COMMIT_HEADER_RE = re.compile(r"\n(?P<key>[^:\n]+):\s*(?P<value>[^\n]+)", re.MULTILINE)


class DBMDataStore(object):
    def __init__(self, db_path):
        self.dbm = dbm.open(db_path, 'c')

    def _encode(self, data):
        return pickle.dumps(data)

    def _decode(self, data):
        if not data:
            return None
        return pickle.loads(data)

    def set(self, change_number, data):
        data['number'] = change_number
        self.dbm[str(change_number)] = self._encode(data)

    def get(self, change_number):
        saved_record = self.dbm.get(str(change_number))
        return self._decode(saved_record)

    def get_all(self):
        keys = self.dbm.keys()
        values = [self._decode(self.dbm[key]) for key in keys]
        return values


def get_data_store():
    return DBMDataStore(db_path)




def is_me(user_dict):
    return user_dict.get('username') == username


def find_last_comment_by(comments, username):
    for comment in reversed(comments):
        if comment["reviewer"].get("username") == username:
            return comment

    return None


def remove_jenkins_comments(change):
    change["comments"] = list(filter(
        lambda comment: comment["reviewer"].get("username") != "jenkins",
        change["comments"]))
    return change


def extract_headers(change):
    msg = change["commitMessage"]
    headers = COMMIT_HEADER_RE.findall(msg)
    change['headers'] = headers
    return change


def does_relate_to_bug(change):
    BUG_REALTED_HEADERS = {'Closes-Bug', 'Partial-Bug', 'Related-Bug'}
    change['related_bugs'] = set()
    for key, value in change['headers']:
        if key in BUG_REALTED_HEADERS:
            change['related_bugs'].add(value)

    return change


def not_mine(change):
    return not is_me(change['owner'])


def has_changed_since_comment(change):
    return not is_me(change["comments"][-1]["reviewer"])


def is_spec(change):
    is_blueprint = False
    for key, value in change['headers']:
        if key == "Implements":
            if value.startswith('blueprint'):
                is_blueprint = True

    change['is_blueprint'] = is_blueprint
    return change


def add_last_checked_information(change):
    last_comment = find_last_comment_by(change["comments"], username)
    change["diff_url"] = change["url"]
    if last_comment is not None:
        last_patch_set = PATCH_SET_INFO_RE.findall(last_comment["message"])
        last_patch_set = int(last_patch_set[0])
        change["last_checked_patch_set"] = last_patch_set
        current_path_set = int(change["currentPatchSet"]["number"])
        change["change_since_last_comment"] = (
            current_path_set != last_patch_set)
        if last_patch_set != current_path_set:
            change["diff_url"] = "http://%s/#/c/%s/%d..%d/" % (
                host, change["number"], last_patch_set, current_path_set
            )
    else:
        change["change_since_last_comment"] = True
        change["last_checked_patch_set"] = -1

    return change


def mark_is_read(change):
    db = get_data_store()
    saved_record = db.get(change['number'])
    if saved_record:
        change['lastRead'] = saved_record['lastRead']
        change['is_read'] = (int(change['lastRead']) > int(change['lastUpdated']))
    else:
        change['is_read'] = False

    return change


def unread(change):
    return not change['is_read']


def fit_width(s, n):
    if len(s) > n:
        return s[:n-3] + "..."
    else:
        return s + " " * (n - len(s))



def handle_list(args=None):
    pkey = get_private_key()
    g = Gerrit(host, port, username, pkey)
    changes = g.query(query,
                      options=[QueryOptions.Comments,
                               QueryOptions.CurrentPatchSet,
                               QueryOptions.CommitMessage])

    changes = map(remove_jenkins_comments, changes)
    changes = map(add_last_checked_information, changes)
    changes = map(mark_is_read, changes)
    changes = map(extract_headers, changes)
    changes = map(does_relate_to_bug, changes)
    changes = map(is_spec, changes)
    #changes = filter(not_mine, changes)
    changes = filter(has_changed_since_comment, changes)
    changes = filter(unread, changes)
    sys.stdout.write(str(Template(
        file=template_path,
        searchList=[{"changes": changes,
                     "fit_width": fit_width,
                     "terminal_size": get_terminal_size(),
                     }])))


def handle_read(args):
    db = get_data_store()
    number = args.review
    record = db.get(number)
    if not record:
        record = {}
    record['lastRead'] = time.time()
    db.set(number, record)


def handle_unread(args):
    db = get_data_store()
    number = args.review
    record = db.get(number)
    if not record:
        record = {}
    record['lastRead'] = 0
    db.set(number, record)


def handle_showrecord(args):
    db = get_data_store()
    number = args.review
    record = db.get(number)
    print(number, record)


def handle_showdb(args):
    db = get_data_store()
    print(db.get_all())


def create_argument_parser():
    parser = argparse.ArgumentParser(description='Gerrit review helper tool')
    parser.set_defaults(func=handle_list)

    subparsers = parser.add_subparsers(title='subcommands')

    list_subparser = subparsers.add_parser('list',
                                           help='List all (unread) reviews')
    list_subparser.set_defaults(func=handle_list)

    read_subparser = subparsers.add_parser('read', help='Mark a review as read')
    read_subparser.set_defaults(func=handle_read)
    read_subparser.add_argument('review', help='The review to mark as read')

    unread_subparser = subparsers.add_parser(
        'unread',
        help='Mark a review as unread'
    )
    unread_subparser.set_defaults(func=handle_unread)
    unread_subparser.add_argument('review', help='The review to mark as unread')

    showrecord_subparser = subparsers.add_parser(
        'showrecord',
        help='Show DB record for a review',
    )
    showrecord_subparser.set_defaults(func=handle_showrecord)
    showrecord_subparser.add_argument('review', help='The review to show')

    showdb_subparser = subparsers.add_parser('showdb', help='Show bruv DB')
    showdb_subparser.set_defaults(func=handle_showdb)

    return parser


def main():
    stdin = None
    if len(sys.argv) > 1:
        stdin = open(sys.argv[1])

    BruvShell(stdin=stdin).cmdloop()
    return
    parser = create_argument_parser()

    if len(sys.argv) == 1:
        handle_list()
    else:
        args = parser.parse_args()
        args.func(args)

if __name__ == "__main__":
    main()
