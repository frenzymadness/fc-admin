/*
 * Copyright (C) 2014 Red Hat, Inc.
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the licence, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this program; if not, see <http://www.gnu.org/licenses/>.
 *
 * Authors: Alberto Ruiz <aruiz@redhat.com>
 *          Oliver Gutiérrez <ogutierrez@redhat.com>
 */

var DEBUG = 0;
var _ = cockpit.gettext
var fc = null;
var currentuid = null;
var currentprofile = null;
var state = {
  debuglevel: 'info',
  defaults: {
    profilepriority : 50
  }
};
/*******************************************************************************
 * Hypervisor configuration
 ******************************************************************************/

function checkHypervisorConfig(cb) {
  // Show hypervisor dialog if not configured
  fc.GetHypervisorConfig(function(data) {
    if (data.needcfg) {
      showHypervisorConfig();
    } else {
      if (cb) cb(data)
    }
  });
}

function showHypervisorConfig() {
  fc.GetHypervisorConfig(function(resp) {
    clearModalFormErrors('hypervisor-config-modal')
    $('#host').val(resp.host);
    $('#username').val(resp.username);
    $('#mode option[value="' + resp.mode + '"]').prop('selected', true);
    $('#pubkey').html(resp.pubkey);
    $('#hypervisor-config-modal').modal('show');
  });
}

function checkKnownHost(hostname, cb, data) {
  data = data || {};
  fc.CheckKnownHost(hostname, function(resp){
    if (resp.status) {
      cb(data);
    } else if (resp.error != undefined) {
      // We have an error
      showMessageDialog(resp.error, _('Error'));
    } else if (resp.fprint != undefined) {
      showQuestionDialog(
        _('Do you want to add this host to known hosts?') +
          '<p>' + _('Fingerprint data') + ':</p>' +
          '<p>' + resp.fprint + '</p>',
        _('Hypervisor host verification'),
        function(event, dialog) {
          // Add host to known hosts
          $('#message-dialog-modal').modal('hide');
          addToKnownHosts(hostname, cb, data);
        }
      );
    }
  });
}

function addToKnownHosts(hostname, cb, data) {
  fc.AddKnownHost(hostname, function(resp){
    if (resp.status) {
      cb(data);
    } else {
      showMessageDialog(resp.error, _('Error'))
    }
  });
}

function saveHypervisorConfig(cb) {
  DEBUG > 0 && console.log('FC: Saving hypervisor configuration');

  clearModalFormErrors('hypervisor-config-modal');

  var data = {
    host: $('#host').val(),
    username: $('#username').val(),
    mode: $('#mode').val(),
    domains: {}
  }

  function saveHypervisorFinal(data) {
    fc.SetHypervisorConfig(data, function(resp) {
      if (resp.status) {
        $('#hypervisor-config-modal').modal('hide');
        if (typeof(cb) == 'function') cb();
      } else {
        showMessageDialog(resp.error, _('Error'))
      }
    });
  }

  fc.CheckHypervisorConfig(data, function(resp) {
    if (resp.status) {
      checkKnownHost(data.host, saveHypervisorFinal, data);
    } else {
      $.each(resp.errors, function( key, value ) {
        addFormError(key, value);
      });
    }
  });
}

function showPubkeyInstall() {
  saveHypervisorConfig(function(){
    $('#pubkey-install-password').val('');
    $('#hypervisor-config-modal').modal('hide');
    $('#pubkey-install-modal').modal('show');
  });
}

function cancelPubkeyInstall() {
  $('#message-dialog-modal').modal('hide');
  $('#pubkey-install-modal').modal('hide');
  $('#hypervisor-config-modal').modal('show');
}

function installPubkey() {
  DEBUG > 0 && console.log('FC: Install public key');

  $('#pubkey-install-modal').modal('hide');
  var host = $('#host').val();
  var user = $('#username').val();
  var pass = $('#pubkey-install-password').val();
  $('#pubkey-install-password').val('');

  showSpinnerDialog(
    _('Fleet Commander is installing the public key. Please wait'),
    _('Installing public key'));

  fc.InstallPubkey(host, user, pass, function(resp) {
    DEBUG > 0 && console.log('FC: Calling dbus for public key install')

    $('#spinner-dialog-modal').modal('hide');

    if (resp.status) {
      showMessageDialog(
        _('Public key has been installed succesfuly'),
        _('Public key installed'),
        cancelPubkeyInstall);
    } else {
      showMessageDialog(resp.error, _('Error'), cancelPubkeyInstall);
    }
  })
}

function copyPubkeyToClipboard() {
  $('#pubkey').select();
  document.execCommand('copy')
  if (window.getSelection) {
    if (window.getSelection().empty) {
      window.getSelection().empty();
    } else if (window.getSelection().removeAllRanges) {
      window.getSelection().removeAllRanges();
    }
  } else if (document.selection) {
    document.selection.empty();
  }
}

/*******************************************************************************
 * Profiles
 ******************************************************************************/

function refreshProfileList() {
 // Populate profiles list
 fc.GetProfiles(function(resp) {
   if (resp.status) {
     var data = resp.data;
     // Clear profile list HTML
     $('#profile-list').html('');
     // Populate profile list
     $.each (data, function (i, val) {
       var tr = $('<tr ></tr>');
       // $('<td></td>', { text: val.displayName }).appendTo(tr);
       $('<td></td>', { text: val[0] }).appendTo(tr);
       $('<td></td>', { text: val[1] }).appendTo(tr);

       var actions_col = $('<td></td>');
       actions_col.appendTo(tr);

       var actions_container = $('<span></span>', { class: 'pull-right' });
       actions_container.appendTo(actions_col)

       // var uid = val.url.slice(0, val.url.length - 5);
       var uid = val[0]

       $('<button></button>', {"class": "btn btn-default", text: _('Edit')})
         .click(function () { editProfile(uid); })
         .appendTo(actions_container);

       $('<button></button>', {"class": "btn btn-danger", text: _('Delete')})
         .click(function () { removeProfile (uid, val.displayName); })
         .appendTo(actions_container);

       tr.appendTo('#profile-list');
     });
   } else {
     showMessageDialog(resp.error, 'Error');
   }
 });
}

function showAddProfile() {
  // Clear current profile
  currentprofile = null;
  // Clear form data before show
  $('#profile-name').val('');
  $('#profile-desc').val('');
  $('#profile-priority').val(state.defaults.profilepriority);
  $('#profile-users').val('');
  $('#profile-groups').val('');
  $('#profile-hosts').val('');
  $('#profile-hostgroups').val('');
  // Hide settings adding buttons
  $('#edit-profile-further-group').hide()
  // Show profile modal dialog
  $('#profile-modal').modal('show');
}

function editProfile(uid) {
  fc.GetProfile(uid, function(resp) {
    if (resp.status) {
      currentuid = uid;
      currentprofile = resp.data

      $('#profile-name').val(resp.data.name);
      $('#profile-desc').val(resp.data.description || '');
      $('#profile-priority').val(resp.data.priority || '');
      $('#profile-users').val(resp.data.users || '');
      $('#profile-groups').val(resp.data.groups || '');
      $('#profile-hosts').val(resp.data.hosts || '');
      $('#profile-hostgroups').val(resp.data.hostgroups || '');
      // Dhow settings adding buttons
      $('#edit-profile-further-group').show()
      // Show profile modal dialog
      $('#profile-modal').modal('show');
    } else {
      showMessageDialog(_('Error getting profile data'), _('Error'));
    }
  });
}

function saveProfile() {
  clearModalFormErrors('profile-modal');

  if (!$('#profile-name').val()) {
    addFormError('profile-name', _('Profile name is required'));
    return
  }

  if (!$('#profile-priority').val()) {
    addFormError('profile-priority', _('Priority is required'));
    return
  }

  var data = {
    'name': $('#profile-name').val(),
    'description': $('#profile-desc').val(),
    'priority': $('#profile-priority').val(),
    'users': $('#profile-users').val(),
    'groups': $('#profile-groups').val(),
    'hosts': $('#profile-hosts').val(),
    'hostgroups': $('#profile-hostgroups').val(),
  }

  if (currentprofile && currentprofile.settings) {
    data.settings = currentprofile.settings
  } else {
    data.settings = {}
  }

  fc.SaveProfile(data, function(resp) {
    if (resp.status) {
      $('#profile-modal').modal('hide');
      // Refresh profiles
      refreshProfileList();
    } else {
      showMessageDialog(_('Error saving profile'), _('Error'));
    }
  });
}

function removeProfile(uid, displayName) {
  showQuestionDialog(
    _('Are you sure you want to delete profile') + ' "' + displayName + '"?',
    _('Delete profile confirmation'),
    function(){
      fc.DeleteProfile(uid, function(resp){
        refreshProfileList();
        $('#message-dialog-modal').modal('hide');
      });
    })
}


/*******************************************************************************
 * Live session management
 ******************************************************************************/

function selectDomain() {
  // Once selected the domain, set it's uuid in sessionStorage and redirect
  $('#domain-selection-modal').modal('hide');
  sessionStorage.setItem("fc.session.domain", $(this).attr('data-uuid'));
  sessionStorage.setItem("fc.session.profile_uid", currentuid);
  showSpinnerDialog(
    _('Starting live session. Please wait...'))
  setTimeout(function(){
    location.href = "livesession.html";
  }, 500)
}

function showDomainSelection() {

  checkHypervisorConfig(function(data) {

    checkKnownHost(data.host, function(){

      $('#profile-modal').modal('hide');
      $('#domain-selection-modal').modal('show');

      // Show loading clock
      spinner = $('#domain-selection-modal .spinner');
      list = $('#domain-selection-list');
      spinner.show();

      // Generate domain list
      list.html('');

      fc.ListDomains(function(resp) {
        if (resp.status) {
          $('#domain-selection-modal .spinner').hide();
          $.each(resp.domains, function() {
            if (!this.temporary) {
              var wrapper = $('<div></div>', {'class': 'list-group-item'});
              var text = this.name;
              if (this.active) {
                text = this.name + ' (' + _('running') + ')';
                wrapper.addClass('grayed')
              }
              domain = $('<a></a>', { text: text, href: '#', 'data-uuid': this.uuid});
              domain.click(selectDomain);
              domain.appendTo(wrapper);
              wrapper.appendTo(list);
            }
          });
        } else {
          $('#domain-selection-modal').modal('hide');
          showMessageDialog(_('Error getting domain list'), _('Error'));
        }
      });

    });

  });
}

/*******************************************************************************
 * Initialization
 ******************************************************************************/
$(document).ready (function () {
  // Bind events
  $('#show-hypervisor-config').click(showHypervisorConfig);
  $('#save-hypervisor-config').click(saveHypervisorConfig);
  $('#show-add-profile').click(showAddProfile);
  $('#save-new-profile').click(saveProfile);
  $('#save-existing-profile').click(saveProfile);
  $('#show-highlighted-apps').click(showHighlightedApps);
  $('#add-highlighted-app').click(addHighlightedAppFromEntry);
  $('#save-highlighted-apps').click(saveHighlightedApps);
  $('#show-domain-selection').click(showDomainSelection);
  $('#show-pubkey-install').click(showPubkeyInstall);
  $('#cancel-pubkey-install').click(cancelPubkeyInstall);
  $('#install-pubkey').click(installPubkey);
  $('#copy-pubkey-to-clipboard').click(copyPubkeyToClipboard);

  $('#pubkey-install-password').keypress(function(e){
    var code = (e.keyCode ? e.keyCode : e.which);
    if(code == 13) installPubkey();
  });

  $("#hypervisor-config-modal").on('shown.bs.modal', function () {
    $('#host').focus();
  });

  $("#profile-modal").on('shown.bs.modal', function () {
    $('#profile-name').focus();
  });

  $("#pubkey-install-modal").on('shown.bs.modal', function () {
    $('#pubkey-install-password').focus();
  });

  // Create a Fleet Commander dbus client instance
  fc = new FleetCommanderDbusClient(function(){

    fc.GetInitialValues(function(resp) {
      state.debuglevel = resp.debuglevel
      state.defaults = resp.defaults

      setDebugLevel(resp.debugLevel);
    });

    $('#main-container').show();
    refreshProfileList();
    checkHypervisorConfig();
    initialize_goa();
  }, function(){
    $('#main-container').hide()
    showCurtain(
      _('Can not connect with Fleet Commander dbus service'),
      _('Can\'t connect to Fleet Commander'),
      null,
      {
        'dbus-retry': {
          text: 'Retry connection',
          class: 'btn-primary',
          callback: function(){ location.reload() }},
      });
  });
});
