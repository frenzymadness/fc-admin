#!/usr/bin/python
# -*- coding: utf-8 -*-
# vi:ts=4 sw=4 sts=4

# Copyright (C) 2014 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the licence, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, see <http://www.gnu.org/licenses/>.
#
# Authors: Alberto Ruiz <aruiz@redhat.com>
#          Oliver Gutiérrez <ogutierrez@redhat.com>

# Python imports
import os
import re
import signal
import json
import uuid
import logging
import subprocess

# Fleet commander imports
from collectors import GoaCollector, GSettingsCollector, LibreOfficeCollector
from flaskless import Flaskless, HttpResponse, JSONResponse, HTTP_RESPONSE_CODES
import libvirtcontroller
from database import DBManager

SYSTEM_USER_REGEX = re.compile(r'[a-z_][a-z0-9_]{0,30}')
IPADDRESS_AND_PORT_REGEX = re.compile(r'^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])(\:[0-9]{1,5})*$')
HOSTNAME_AND_PORT_REGEX = re.compile(r'^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])(\:[0-9]{1,5})*$')


class AdminService(Flaskless):

    def __init__(self, name, config, *args, **kwargs):

        kwargs['routes'] = [
            (r'^clientdata/(?P<path>.+)$',          ['GET'],            self.serve_clientdata),
            (r'^static/(?P<path>.+)$',              ['GET'],            self.serve_static),
            ('^profiles/$',                         ['GET'],            self.profiles),
            ('^profiles/applies$',                  ['GET'],    self.profiles_applies),
            ('^profiles/save/(?P<id>[-\w\.]+)$',    ['POST'],           self.profiles_save),
            ('^profiles/add$',                      ['GET'],            self.profiles_add),
            ('^profiles/delete/(?P<uid>[-\w\.]+)$', ['GET'],            self.profiles_delete),
            ('^profiles/discard/(?P<id>[-\w\.]+)$', ['GET'],            self.profiles_discard),
            ('^profiles/(?P<profile_id>[-\w\.]+)$', ['GET'],            self.profiles_id),
            ('^profiles/apps/(?P<uid>[-\w\.]+)$',   ['GET', 'POST'],    self.profiles_apps),
            ('^changes/submit/(?P<name>[-\w\.]+)$', ['POST'],           self.changes_submit_name),
            ('^changes/select',                     ['POST'],           self.changes_select),
            ('^changes',                            ['GET'],            self.changes),
            ('^deploy/(?P<uid>[-\w\.]+)$',          ['GET'],            self.deploy),
            ('^session/start$',                     ['POST'],           self.session_start),
            ('^session/stop$',                      ['GET'],            self.session_stop),
            ('^hypervisor/domains/list/$',          ['GET'],            self.domains_list),
            ('^hypervisor/$',                       ['GET', 'POST'],    self.hypervisor_config),
            ('^init/$',                             ['GET'],            self.webapp_init),
            ('^$',                                  ['GET'],            self.index),
        ]
        super(AdminService, self).__init__(name, config, *args, **kwargs)

        self.DNULL = open('/dev/null', 'w')
        self.websockify_command_template = 'websockify %s:%d %s:%d'

        # Initialize database
        self.db = DBManager(config['database_path'])

        # Initialize collectors
        self.collectors_by_name = {
            'org.gnome.gsettings': GSettingsCollector(self.db),
            'org.gnome.online-accounts': GoaCollector(),
            'org.libreoffice.registry': LibreOfficeCollector(self.db),
        }

        self.current_session = self.db.config
        self.custom_args = config

        self.static_dir = config['data_dir']

        # TODO: Change data dir
        self.state_dir = config['state_dir']

        # TODO: Change path for templates outside of static dir
        self.templates_dir = os.path.join(config['data_dir'], 'templates')

    def check_for_profile_index(self):
        INDEX_FILE = os.path.join(self.custom_args['profiles_dir'], 'index.json')
        self.test_and_create_file (INDEX_FILE, [])

    def check_for_applies(self):
        APPLIES_FILE = os.path.join(self.custom_args['profiles_dir'], 'applies.json')
        self.test_and_create_file (APPLIES_FILE, {})

    def test_and_create_file (self, filename, content):
        if os.path.isfile(filename):
            return

        try:
            open(filename, 'w+').write(json.dumps(content))
        except OSError:
            logging.error('There was an error attempting to write on %s' % filename)

    def get_libvirt_controller(self, admin_host=None, admin_port=None):
        if 'hypervisor' not in self.current_session:
            raise Exception('hypervisor is not configured yet')

        hypervisor = self.current_session['hypervisor']
        return libvirtcontroller.LibVirtController(self.state_dir, hypervisor['username'], hypervisor['host'], hypervisor['mode'], admin_host, admin_port)

    # Views
    def index(self, request):
        return self.serve_html_template('index.html')

    def webapp_init(self, request):
        if 'hypervisor' not in self.current_session:
            return JSONResponse({'needcfg': True})
        else:
            return JSONResponse({'needcfg': False})

    def hypervisor_config(self, request):
        if request.method == 'GET':
            # Initialize LibVirtController to create keypair if needed
            ctrlr = libvirtcontroller.LibVirtController(self.state_dir, None, None, 'system', None, None)
            with open(ctrlr.public_key_file, 'r') as fd:
                public_key = fd.read().strip()
                fd.close()
            # Check hypervisor configuration
            data = {
                'pubkey': public_key,
            }
            if 'hypervisor' not in self.current_session:
                data.update({
                    'host': '',
                    'username': '',
                    'mode': 'system',
                    'needcfg': True,
                    'adminhost': '',
                })
            else:
                data.update(self.current_session['hypervisor'])
            return JSONResponse(data)
        elif request.method == 'POST':
            data = request.get_json()
            errors = {}
            # Check username
            if not re.match(SYSTEM_USER_REGEX, data['username']):
                errors['username'] = 'Invalid username specified'
            # Check hostname
            if not re.match(HOSTNAME_AND_PORT_REGEX, data['host']) and not re.match(IPADDRESS_AND_PORT_REGEX, data['host']):
                errors['host'] = 'Invalid hostname specified'
            # Check libvirt mode
            if data['mode'] not in ('system', 'session'):
                errors['mode'] = 'Invalid session type'
            # Check admin host
            if 'adminhost' in data and data['adminhost'] != '':
                if not re.match(HOSTNAME_AND_PORT_REGEX, data['adminhost']) and not re.match(IPADDRESS_AND_PORT_REGEX, data['adminhost']):
                    errors['adminhost'] = 'Invalid hostname specified'
            if errors:
                return JSONResponse({'errors': errors})
            # Save hypervisor configuration
            self.current_session['hypervisor'] = data
            return JSONResponse({})
        else:
            # This should never happen because flaskless should did this before us
            return HttpResponse(HTTP_RESPONSE_CODES[405], status_code=405)

    def domains_list(self, request):
        if 'domains' not in self.current_session:
            try:
                domains = self.get_libvirt_controller().list_domains()
            except Exception as e:
                return JSONResponse({'status': False, 'error': 'Error retrieving domains'})
                logging.debug(e)
        else:
            domains = self.current_session['domains']
        return JSONResponse({'status': True, 'domains': domains})

    def serve_clientdata(self, request, path):
        """
        Serve client data
        """
        return self.serve_static(request, path, basedir=self.custom_args['profiles_dir'])

    def profiles(self, request):
        self.check_for_profile_index()
        return self.serve_static(request, 'index.json', basedir=self.custom_args['profiles_dir'])

    def profiles_applies(self, request):
        self.check_for_applies()
        return self.serve_static(request, 'applies.json', basedir=self.custom_args['profiles_dir'])

    def profiles_id(self, request, profile_id):
        return self.serve_static(request, profile_id + '.json', basedir=self.custom_args['profiles_dir'])

    def profiles_apps(self, request, uid):
        INDEX_FILE = os.path.join(self.custom_args['profiles_dir'], 'index.json')
        PROFILE_FILE = os.path.join(self.custom_args['profiles_dir'], uid+'.json')

        if request.method == 'GET':
            return self.serve_html_template('profile.favourites.html')

        payload = request.get_json()

        if not isinstance(payload, list) or \
           len(set(map(lambda x: x is unicode, payload))) > 1:
            return JSONResponse({'status': 'application list is not a list of strings'}, 420)

        if not os.path.isfile (INDEX_FILE) or not os.path.isfile (PROFILE_FILE):
            return JSONResponse({'status': 'there are no profiles in the database'}, 500)

        profile = None
        try:
            profile = json.loads(open(PROFILE_FILE).read())
        except:
            return JSONResponse({'status': 'could not read profile data'}, 500)

        if not isinstance(profile, dict):
            return JSONResponse({'status': 'profile object %s is not a dictionary' % uid}, 500)

        if not profile.get('settings', False):
            profile['settings'] = {}

        if not isinstance(profile['settings'], dict):
            return JSONResponse({'status': 'settings value in %s is not a list' % uid}, 500)

        if not profile['settings'].get('org.gnome.gsettings', False):
            profile['settings']['org.gnome.gsettings'] = []

        gsettings = profile['settings']['org.gnome.gsettings']

        if not isinstance(gsettings, list):
            return JSONResponse({'status': 'settings/org.gnome.gsettings value in %s is not a list' % uid}, 500)

        existing_change = None
        for change in gsettings:
            if 'key' not in change:
                continue

            if change['key'] != '/org/gnome/software/popular-overrides':
                continue

            existing_change = change

        if existing_change and payload == []:
            gsettings.remove (existing_change)
        elif not existing_change:
            existing_change = {'key': '/org/gnome/software/popular-overrides',
                               'signature': 'as'}
            gsettings.append(existing_change)

        existing_change['value'] = json.dumps(payload)

        try:
            open(PROFILE_FILE, 'w+').write(json.dumps(profile))
        except:
            return JSONResponse({'status': 'could not write profile %s' % uid}, 500)

        return JSONResponse({'status': 'ok'})


    def profiles_save(self, request, id):

        def write_and_close(path, load):
            f = open(path, 'w+')
            f.write(load)
            f.close()

        uid = self.current_session.get('uid', None)

        if not uid or uid != id:
            return JSONResponse({"status": "nonexistinguid"}, 403)

        INDEX_FILE = os.path.join(self.custom_args['profiles_dir'], 'index.json')
        APPLIES_FILE = os.path.join(self.custom_args['profiles_dir'], 'applies.json')
        PROFILE_FILE = os.path.join(self.custom_args['profiles_dir'], id+'.json')

        data = request.get_json()

        if not isinstance(data, dict):
            return JSONResponse({"status": "JSON request is not an object"}, 403)
        if not all([key in data for key in ['profile-name', 'profile-desc', 'groups', 'users']]):
            return JSONResponse({"status": "missing key(s) in profile settings request JSON object"}, 403)

        profile = {}
        settings = {}
        groups = []
        users = []

        for name, collector in self.collectors_by_name.items():
            settings[name] = collector.get_settings()

        groups = [g.strip() for g in data['groups'].split(",")]
        users = [u.strip() for u in data['users'].split(",")]
        groups = filter(None, groups)
        users = filter(None, users)

        profile["uid"] = uid
        profile["name"] = data["profile-name"]
        profile["description"] = data["profile-desc"]
        profile["settings"] = settings
        profile["etag"] = "placeholder"

        self.check_for_profile_index()
        index = json.loads(open(INDEX_FILE).read())
        if not isinstance(index, list):
            return JSONResponse({"status": "%s does not contain a JSON list as root element" % INDEX_FILE}, 403)
        index.append({"url": id + ".json", "displayName": data["profile-name"]})

        self.check_for_applies()
        applies = json.loads(open(APPLIES_FILE).read())
        if not isinstance(applies, dict):
            return JSONResponse({"status": "%s does not contain a JSON object as root element" % APPLIES_FILE})
        applies[uid] = {"users": users, "groups": groups}

        del(self.current_session["uid"])

        write_and_close(PROFILE_FILE, json.dumps(profile))
        write_and_close(APPLIES_FILE, json.dumps(applies))
        write_and_close(INDEX_FILE, json.dumps(index))

        return JSONResponse({'status': 'ok'})

    def profiles_add(self, request):
        return self.serve_html_template('profile.add.html')

    def profiles_delete(self, request, uid):
        INDEX_FILE = os.path.join(self.custom_args['profiles_dir'], 'index.json')
        PROFILE_FILE = os.path.join(self.custom_args['profiles_dir'], uid+'.json')

        try:
            os.remove(PROFILE_FILE)
        except:
            pass

        index = json.loads(open(INDEX_FILE).read())
        for profile in index:
            if (profile["url"] == uid + ".json"):
                index.remove(profile)

        open(INDEX_FILE, 'w+').write(json.dumps(index))
        return JSONResponse({'status': 'ok'})

    def profiles_discard(self, request, id):
        if self.current_session.get('uid', None) == id:
            del(self.current_session["uid"])
            # del(self.current_session["changeset"])
            return JSONResponse({'status': 'ok'})

        return JSONResponse({'status': 'profile %s not found' % id}, 403)

    def changes(self, request):
        response = {}

        for db in ['org.gnome.gsettings', 'org.libreoffice.registry']:
            collector = self.collectors_by_name.get(db, None)
            if not collector:
                continue

            changes = collector.dump_changes()
            if not changes:
                continue

            response[db] = changes

        return JSONResponse(response)

    def changes_select(self, request):
        data = request.get_json()

        if not isinstance(data, dict):
            return JSONResponse({"status": "bad JSON data"}, 403)

        if self.current_session.get('port', None) is None:
            return JSONResponse({"status": "session was not started"}, 403)

        for key in data:
            selection = data[key]

            if not isinstance(selection, list):
                return JSONResponse({"status": "bad JSON format for " + key}, 403)

            self.collectors_by_name[key].remember_selected(selection)

        uid = str(uuid.uuid1().int)
        self.current_session['uid'] = uid

        return JSONResponse({"status": "ok", "uuid": uid})

    # Add a configuration change to a session
    def changes_submit_name(self, request, name):
        if name in self.collectors_by_name:
            self.collectors_by_name[name].handle_change(request)
            return JSONResponse({"status": "ok"})
        else:
            return JSONResponse({"status": "namespace %s not supported or session not started"} % name, 403)

    def deploy(self, request, uid):
        return self.serve_html_template('deploy.html')

    def session_start(self, request):
        data = request.get_json()

        if self.current_session.get('port', None) is not None:
            return JSONResponse({"status": "Session already started"}, 400)

        if not data or 'domain' not in data or 'admin_host' not in data or 'admin_port' not in data:
            return JSONResponse({"status": "Invalid data received"}, 400)

        self.db.sessionsettings.clear_settings()

        hypervisor = self.current_session['hypervisor']
        forcedadminhost = hypervisor.get('adminhost', None)
        if forcedadminhost:
            forcedadminhostdata = forcedadminhost.split(':')
            if len(forcedadminhostdata) < 2:
                forcedadminhostdata.append(data['admin_port'])
            admin_host, admin_port = forcedadminhostdata
        else:
            admin_host = data['admin_host']
            admin_port = data['admin_port']

        try:
            uuid, port, tunnel_pid = self.get_libvirt_controller(admin_host, admin_port).session_start(data['domain'])
        except Exception as e:
            return JSONResponse({'status': 'Error starting session'}, 520)
            logging.debug(e)
        self.current_session['uuid'] = uuid
        self.current_session['port'] = port
        self.current_session['tunnel_pid'] = tunnel_pid

        self.websocket_stop()
        self.current_session['websocket_listen_host'] = data['admin_host']
        self.current_session['websocket_target_host'] = 'localhost'
        self.current_session['websocket_target_port'] = port
        self.websocket_start()

        # TODO: Randomize port on websocket creation for more security
        return JSONResponse({'port': 8989})

    def session_stop(self, request):

        if 'uuid' not in self.current_session or 'tunnel_pid' not in self.current_session or 'port' not in self.current_session:
            return JSONResponse({'status': 'There was no session started'}, 520)

        uuid = self.current_session['uuid']
        tunnel_pid = self.current_session['tunnel_pid']

        del(self.current_session['uuid'])
        del(self.current_session['tunnel_pid'])
        del(self.current_session['port'])

        self.websocket_stop()

        try:
            self.get_libvirt_controller().session_stop(uuid, tunnel_pid)
        except Exception as e:
            return JSONResponse({'status': 'Error stopping session'}, 520)
            logging.debug(e)
        return JSONResponse({'status': True})

    def websocket_start(self, listen_host='localhost', listen_port=8989, target_host='localhost', target_port=5900):
        if 'websockify_pid' in self.current_session and self.current_session['websockify_pid']:
            return

        self.current_session.setdefault('websocket_listen_host', listen_host)
        self.current_session.setdefault('websocket_listen_port', listen_port)
        self.current_session.setdefault('websocket_target_host', target_host)
        self.current_session.setdefault('websocket_target_port', target_port)

        command = self.websockify_command_template % (
            self.current_session['websocket_listen_host'],
            self.current_session['websocket_listen_port'],
            self.current_session['websocket_target_host'],
            self.current_session['websocket_target_port'])

        process = subprocess.Popen(
            command, shell=True,
            stdin=self.DNULL, stdout=self.DNULL, stderr=self.DNULL)

        self.current_session['websockify_pid'] = process.pid

    def websocket_stop(self):
        if 'websockify_pid' in self.current_session and self.current_session['websockify_pid']:
            # Kill websockify command
            try:
                os.kill(self.current_session['websockify_pid'], signal.SIGKILL)
            except:
                pass
            del(self.current_session['websockify_pid'])

if __name__ == '__main__':

    # Python import
    from argparse import ArgumentParser

    # Fleet commander imports
    from utils import parse_config

    parser = ArgumentParser(description='Admin interface server')
    parser.add_argument(
        '--configuration', action='store', metavar='CONFIGFILE', default=None,
        help='Provide a configuration file path for the web service')

    args = parser.parse_args()
    config = parse_config(args.configuration)
    app = AdminService(__name__, config)
    app.run(host=config['host'], port=config['port'], debug=True)
