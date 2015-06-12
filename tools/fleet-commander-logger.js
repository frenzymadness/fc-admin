#!/usr/bin/gjs
/*
 * Copyright (c) 2015 Red Hat, Inc.
 *
 * GNOME Maps is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by the
 * Free Software Foundation; either version 2 of the License, or (at your
 * option) any later version.
 *
 * GNOME Maps is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
 * or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
 * for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with GNOME Maps; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 *
 * Authors: Alberto Ruiz <aruiz@redhat.com>
 *          Matthew Barnes <mbarnes@redhat.com>
 */


const GLib = imports.gi.GLib;
const Gio  = imports.gi.Gio;
const Soup = imports.gi.Soup;

//Global constants
const RETRY_INTERVAL = 1000;
const SUBMIT_PATH    = '/submit_change/';

//Mainloop
const ml = imports.mainloop;

//Global application objects
var connmgr         = null;
var gsettingslogger = null;
var goalogger       = null;

//Global settings
var options = null;
var _debug = false;

function debug (msg) {
  if (!_debug)
      return;
  printerr("DEBUG: " + msg);
}

function parse_options () {
  let result = {
      'admin_server_host': 'localhost',
      'admin_server_port': 8181
  }

  let file = null;

  for(let i = 0; i < ARGV.length; i++) {
    switch(ARGV[i]) {
      case "--help":
      case "-h":
        printerr("--help/-h:               show this output message");
        printerr("--configuration/-c FILE: sets the configuration file");
        printerr("--debug/-d/-v:           enables debugging/verbose output");
        break;
      case "--debug":
      case "-d":
      case "-v":
        _debug = true;
        debug("Debugging output enabled");
        break;
      case "--configuration":
        i++;
        if (ARGV.length == i) {
          printerr("ERROR: No configuration value was provided");
          return null;
        }

        debug(ARGV[i] + " selected as configuration file");

        if (!GLib.file_test (ARGV[i], GLib.FileTest.EXISTS)) {
            printerr("ERROR: " + ARGV[i] + " does not exists");
            return null;
        }
        if (!GLib.file_test (ARGV[i], GLib.FileTest.IS_REGULAR)) {
            printerr("ERROR: " + ARGV[i] + " is not a regular file");
            return null;
        }

        let kf = new GLib.KeyFile();
        try {
            kf.load_from_file(ARGV[i], GLib.KeyFileFlags.NONE);
        } catch (e) {
            debug(e);
            printerr("ERROR: Could not parse configuration file " + ARGV[i]);
            return null;
        }

        if (!kf.has_group("logger")) {
            printerr("ERROR: "+ARGV[i]+" does not have [logger] section");
            return null;
        }
        try {
            result['admin_server_host'] = kf.get_value("logger", "admin_server_host");
        } catch (e) {
            debug (e);
        }
        try {
            result['admin_server_port'] = kf.get_value("logger", "admin_server_port");
        } catch (e) {
            debug (e);
        }
        break;
    }
  }

  debug ("admin_server_host: " + result['admin_server_host'] + " - admin_server_port: " + result['admin_server_port']);
  return result;
}

// ConnectionManager - This class manages
var ConnectionManager = function (host, port) {
    this.uri = new Soup.URI("http://" + host + ":" + port);
    this.session = new Soup.Session();
    this.queue = [];
    this.timeout = 0;
}
function perform_submits () {
    if (this.queue.length < 1)
        return false;

    for (let i = 0; i < this.queue.length ; i++) {
        debug("Submitting change " + this.queue[i].ns + ":")
        debug(this.queue[i].data);

        let payload = this.queue[i].data;
        let ns      = this.queue[i].ns;

        this.uri.set_path(SUBMIT_PATH+ns);
        let msg = Soup.Message.new_from_uri("POST", this.uri);
        msg.set_request('application/json', Soup.MemoryUse.STATIC, payload, payload.length);


        this.session.queue_message(msg, function (s, m) {
            debug("Response from server: returned code " + m.status_code);
            switch (m.status_code) {
                case 200:
                    debug ("Change submitted " + ns + " " + payload);
                    break;
                case 403:
                    printerr("ERROR: invalid change namespace " + ns);
                    printerr(m.response_body.data);
                    break;
                default:
                    printerr("ERROR: There was an error trying to contact the server");
                    return;
            }

            //Remove this item, if the queue is empty remove timeout
            this.queue = this.queue.splice(i, 1);
            if (this.queue.length < 1 && this.timeout > 0) {
                GLib.source_remove(this.timeout);
                this.timeout = 0;
            }
        }.bind(this));
    }
    return true;
}

ConnectionManager.prototype.submit_change = function (namespace, data) {
    this.queue.push({ns: namespace, data: data});

    if (this.queue.length > 0 && this.timeout < 1)
        this.timeout = GLib.timeout_add (GLib.PRIORITY_DEFAULT,
                                         RETRY_INTERVAL,
                                         perform_submits.bind(this));
}

//Something ugly to overcome the lack of exit()
options = parse_options ();

if (options != null) {
    connmgr = new ConnectionManager(options['admin_server_host'], options['admin_server_port']);
    ml.run();
}
