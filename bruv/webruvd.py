#!/bin/env python

import collections
import json

import bottle
import pkg_resources

try:
    from bruv import bruv
except ImportError:
    #  Possibly, we are not installed
    import bruv


ALLOWED_JS_FILES = {
    'angular.min.js',
    'isteven-multi-select.js',
    'ngprogress.min.js',
    'angular-toastr.tpls.min.js',
    'd3-array.v2.min.js',
    'd3.v4.js',
}

ALLOWED_CSS_FILES = {
    'isteven-multi-select.css',
    'ngProgress.css',
    'angular-toastr.min.css',
}

def _get_root(path):
    try:
        return pkg_resources.resource_filename(
            pkg_resources.Requirement('bruv'), path)
    except pkg_resources.DistributionNotFound:
        return '../{}/'.format(path)

@bottle.route('/js/<jsfile>')
def index(jsfile):
    if jsfile not in ALLOWED_JS_FILES:
        raise bottle.HTTPError(status=404)
    root = _get_root('js')
    return bottle.static_file(jsfile, root=root)

@bottle.route('/css/<cssfile>')
def index(cssfile):
    if cssfile not in ALLOWED_CSS_FILES:
        raise bottle.HTTPError(status=404)
    root = _get_root('css')
    return bottle.static_file(cssfile, root=root)

@bottle.route('/')
def index():
    root = _get_root('html')
    return bottle.static_file('index.html', root=root)

@bottle.route('/favicon.ico')
def favicon():
    root = _get_root('images')
    return bottle.static_file('gerrit.png', root=root)

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

@bottle.route('/queries')
def queries():
    queries = bruv.conf['queries']
    queries_string = json.dumps(queries, default=json_bruv_defaults)
    return queries_string

@bottle.route('/default_queries')
def queries():
    try:
        defaults = bruv.conf['default-queries']
    except KeyError:
        return []
    defaults_json = json.dumps(defaults, default=json_bruv_defaults)
    return defaults_json

def main():
    bottle.run(host='0.0.0.0', port=8080)

if __name__ == '__main__':
    main()
