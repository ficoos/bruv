#!/bin/env python

import sys
import os
import re
import json

from itertools import imap, ifilter

import paramiko
from Cheetah.Template import Template


from gerrit import (
    QueryOptions,
    Gerrit,
)

conf = json.load(open(os.path.expanduser("~/.bruvrc")))

pkey_path = os.path.expanduser(conf.get("private_key", "~/.ssh/id_rsa"))
pkey = paramiko.RSAKey(filename=pkey_path)
username = conf.get("username", "john")
host = conf.get("host", "review.openstack.org")
port = conf.get("port", 29418)
query = conf.get("query", "")

PATCH_SET_INFO_RE = re.compile(r"^(?:Patch Set|Uploaded patch set) ([\d]+)")


def is_me(user_dict):
    return user_dict['username'] == username


def find_last_comment_by(comments, username):
    for comment in reversed(comments):
        if comment["reviewer"]["username"] == username:
            return comment

    return None


def remove_jenkins_comments(change):
    change["comments"] = filter(
        lambda comment: comment["reviewer"]["username"] != "jenkins",
        change["comments"])
    return change


def not_mine(change):
    return not is_me(change['owner'])


def has_changed_since_comment(change):
    return not is_me(change["comments"][-1]["reviewer"])


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
            change["diff_url"] = "http://%s/#/c/%s/%d..%d//COMMIT_MSG" % (
                host, change["number"], last_patch_set, current_path_set
            )
    else:
        change["change_since_last_comment"] = True
        change["last_checked_patch_set"] = -1

    return change


def fit_width(s, n):
    if len(s) > n:
        return s[:n-3] + "..."
    else:
        return s + " " * (n - len(s))

g = Gerrit(host, port, username, pkey)
changes = g.query(query,
                  options=[QueryOptions.Comments,
                           QueryOptions.CurrentPatchSet])
changes = imap(remove_jenkins_comments, changes)
changes = imap(add_last_checked_information, changes)
changes = ifilter(not_mine, changes)
changes = ifilter(has_changed_since_comment, changes)
sys.stdout.write(str(Template(file="display.tmpl",
                              searchList=[{"changes": changes,
                                           "fit_width": fit_width}])))
