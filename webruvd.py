#!/bin/env python

import collections
import json

import bottle
import bruv


ALLOWED_JS_FILES = {
    'angular.min.js',
    'isteven-multi-select.js',
    'ngprogress.min.js',
}

ALLOWED_CSS_FILES = {
    'isteven-multi-select.css',
    'ngProgress.css',
}

@bottle.route('/js/<jsfile>')
def index(jsfile):
    if jsfile not in ALLOWED_JS_FILES:
        raise bottle.HTTPError(status=404)
    return bottle.static_file('js/' + jsfile, root='.')

@bottle.route('/css/<cssfile>')
def index(cssfile):
    if cssfile not in ALLOWED_CSS_FILES:
        raise bottle.HTTPError(status=404)
    return bottle.static_file('css/' + cssfile, root='.')

@bottle.route('/')
def index():
    return bottle.static_file('html/index.html', root='.')

# Taken from the json documentation
def json_bruv_defaults(o):
   try:
       iterable = iter(o)
   except TypeError:
       pass
   else:
       return list(iterable)
   # Let the base class default method raise the TypeError
   return json.JSONEncoder.default(self, o)

@bottle.route('/list/<query>')
def list_by_query(query):
    try:
        queries = bruv.conf['queries']
        query_string = queries[query]
    except KeyError:
        raise bottle.HTTPError(status=500)
    changes = bruv.get_changes(query_string)
    result = json.dumps(changes, default=json_bruv_defaults)
    return result

@bottle.route('/read/<number>')
def read(number):
    bruv.mark_as_read(number)
    bottle.response.status = 204

bottle.run(host='localhost', port=8080)
