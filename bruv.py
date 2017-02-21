#!/bin/env python

import sys
import os
import re
import json
import fcntl
import termios
import time
import struct
import argparse

from itertools import imap, ifilter

import paramiko
from Cheetah.Template import Template


from gerrit import (
    QueryOptions,
    Gerrit,
)

import pickle
try:
    import anydbm as dbm
except ImportError:
    import dbm

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

def get_private_key():
    agent = paramiko.agent.Agent()
    keys_by_path = {key.get_name(): key for key in agent.get_keys()}
    if pkey_path in keys_by_path:
        return keys_by_path[pkey_path]
    pkey = paramiko.RSAKey(filename=pkey_path)
    return pkey


def is_me(user_dict):
    return user_dict.get('username') == username


def find_last_comment_by(comments, username):
    for comment in reversed(comments):
        if comment["reviewer"].get("username") == username:
            return comment

    return None


def remove_jenkins_comments(change):
    change["comments"] = filter(
        lambda comment: comment["reviewer"].get("username") != "jenkins",
        change["comments"])
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
            change["diff_url"] = "http://%s/#/c/%s/%d..%d" % (
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

    changes = imap(remove_jenkins_comments, changes)
    changes = imap(add_last_checked_information, changes)
    changes = imap(mark_is_read, changes)
    changes = imap(extract_headers, changes)
    changes = imap(does_relate_to_bug, changes)
    changes = imap(is_spec, changes)
    #changes = ifilter(not_mine, changes)
    changes = ifilter(has_changed_since_comment, changes)
    changes = ifilter(unread, changes)
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


if len(sys.argv) == 1:
    handle_list()
else:
    args = parser.parse_args()
    args.func(args)
