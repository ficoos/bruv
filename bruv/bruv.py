#!/bin/env python3

import sys
import os
import re
import json
import fcntl
import termios
import time
import struct

from functools import partial

import paramiko

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
db_path = str(conf.get("db_file", "bruv.db"))
bug_base_urls = conf.get("bug_base_urls", {})

PATCH_SET_INFO_RE = re.compile(r"^(?:Patch Set|Uploaded patch set) ([\d]+)")
COMMIT_HEADER_RE = re.compile(r"\n(?P<key>[^:\n]+):\s*(?P<value>[^\n]+)",
                              re.MULTILINE)

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
    if not pkey_path:
        return None
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
    BUG_REALTED_HEADERS = {'Closes-Bug', 'Partial-Bug', 'Related-Bug',
                           'Related', 'Closes'}
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


def add_bug_base_url(change):
    change['bug_base_url'] = bug_base_urls.get(change['project'],
                                               'https://launchpad.net/bugs')
    return change


def add_last_checked_information(change):
    last_comment = find_last_comment_by(change["comments"], username)
    change["diff_url"] = change["url"]
    if last_comment is not None:
        last_patch_set = PATCH_SET_INFO_RE.findall(last_comment["message"])
        if not last_patch_set:
            change["change_since_last_comment"] = True
            change["last_checked_patch_set"] = -1
            return change
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


def _process_flow(flow, changes):
    for item in flow:
        changes = item(changes)

    return changes


class FlowBuilder(object):
    def __init__(self):
        self._flow = []

    def add_mapper(self, mapper_func):
        self._flow.append(partial(map, mapper_func))
        return self

    def add_filter(self, filter_func):
        self._flow.append(partial(filter, filter_func))
        return self

    def add_subflow(self, flow):
        self._flow.append(flow)
        return self

    def build(self):
        return partial(_process_flow, self._flow[:])


def _IDENTITY_FLOW(changes):
    return changes


class ChangesFetcher(object):
    def __init__(self, host, port, username, pkey):
        self._gerrit = Gerrit(host, port, username, pkey)
        self._flow = _IDENTITY_FLOW

    def set_flow(self, flow):
        self._flow = flow

    def get_changes(self, query):
        changes = self._gerrit.query(query,
                                     options=[QueryOptions.Comments,
                                              QueryOptions.CurrentPatchSet,
                                              QueryOptions.CommitMessage])
        return self._flow(changes)

_DEFAULT_FLOW = (FlowBuilder()
    .add_mapper(remove_jenkins_comments)
    .add_mapper(add_last_checked_information)
    .add_mapper(mark_is_read)
    .add_mapper(extract_headers)
    .add_mapper(does_relate_to_bug)
    .add_mapper(is_spec)
    .add_mapper(add_bug_base_url)
    .add_filter(has_changed_since_comment)
    .add_filter(unread)
    .build())


def get_changes(query):
    pkey = get_private_key()
    cf = ChangesFetcher(host, port, username, pkey)
    cf.set_flow(_DEFAULT_FLOW)
    return cf.get_changes(query)

def mark_as_read(number):
    db = get_data_store()
    record = db.get(number)
    if not record:
        record = {}
    record['lastRead'] = time.time()
    db.set(number, record)

def mark_as_unread(number):
    db = get_data_store()
    record = db.get(number)
    if not record:
        record = {}
    record['lastRead'] = 0
    db.set(number, record)
