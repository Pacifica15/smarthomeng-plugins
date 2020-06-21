#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2020        René Frieß               rene.friess(a)gmail.com
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Sample plugin for new plugins to run with SmartHomeNG version 1.4 and
#  upwards.
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

from lib.module import Modules
from lib.model.mqttplugin import *
from .webif import WebInterface
from lib.item import Items
from requests.auth import HTTPBasicAuth
import math
import time
import requests


class Robonect(MqttPlugin):
    """
    Main class of the Plugin. Does all plugin specific stuff and provides
    the update functions for the items
    """
    PLUGIN_VERSION = '1.0.0'  # (must match the version specified in plugin.yaml)
    STATUS_TYPES = ['mower/status', 'mower/status/text', 'mower/distance', 'mower/status/duration',
                    'mower/statistic/hours',
                    'mower/stopped', 'mower/mode', 'mower/mode/text', 'mower/battery/charge', 'blades_quality',
                    'blades_hours', 'blades_days', 'mower/error/code', 'mower/error/message', 'error_date',
                    'error_time', 'error_unix']
    REMOTE_TYPES = ['remotestart_name', 'remotestart_visible', 'remotestart_path', 'remotestart_proportion',
                    'remotestart_distance']
    MODE_TYPES = ['home', 'eod', 'man', 'auto', 'job']

    def __init__(self, sh):
        """
        Initalizes the plugin.

        If you need the sh object at all, use the method self.get_sh() to get it. There should be almost no need for
        a reference to the sh object any more.

        Plugins have to use the new way of getting parameter values:
        use the SmartPlugin method get_parameter_value(parameter_name). Anywhere within the Plugin you can get
        the configured (and checked) value for a parameter by calling self.get_parameter_value(parameter_name). It
        returns the value in the datatype that is defined in the metadata.
        """
        super().__init__()
        self._ip = self.get_parameter_value('ip')
        self._user = self.get_parameter_value('user')
        self._password = self.get_parameter_value('password')
        self._base_url = 'http://%s/json?cmd=' % self.get_ip()
        self._cycle = self.get_parameter_value('cycle')
        self._mower_offline = False
        self._items = {}
        self._mode = self.get_parameter_value('mode')
        self._battery_items = {}
        self._status_items = {}
        self._remote_items = {}
        self._status = 0
        self._session = requests.Session()
        self.init_webinterface(WebInterface)
        return

    def run(self):
        """
        Run method for the plugin
        """
        self.logger.debug("Run method called")
        self._base_url = 'http://%s/json?cmd=' % self.get_ip()
        self.scheduler_add('poll_device', self.poll_device, cycle=self._cycle)
        self.alive = True
        if self._mode == 'mqtt':
            self.start_subscriptions()

    def stop(self):
        """
        Stop method for the plugin
        """
        self.logger.debug("Stop method called")
        self.scheduler_remove('poll_device')
        self.alive = False
        if self._mode == 'mqtt':
            self.stop_subscriptions()

    def parse_item(self, item):
        """
        Default plugin parse_item method. Is called when the plugin is initialized.
        The plugin can, corresponding to its attribute keywords, decide what to do with
        the item in future, like adding it to an internal array for future reference
        :param item:    The item to process.
        :return:        If the plugin needs to be informed of an items change you should return a call back function
                        like the function update_item down below. An example when this is needed is the knx plugin
                        where parse_item returns the update_item function when the attribute knx_send is found.
                        This means that when the items value is about to be updated, the call back function is called
                        with the item, caller, source and dest as arguments and in case of the knx plugin the value
                        can be sent to the knx with a knx write function within the knx plugin.
        """
        if self.has_iattr(item.conf, 'robonect_data_type'):
            self.logger.debug("parse item: {}".format(item))

            if self._mode == 'mqtt':
                bool_values = None
                callback = None
                mqtt_id = self.get_iattr_value(item.conf, 'robonect_data_type')
                payload_type = item.property.type
                topic = 'Robonect/' + mqtt_id
                # if mqtt_id == 'mower/stopped':
                #    bool_values = ['false','true']
                if mqtt_id in ['mower/status', 'mower/mode']:
                    callback = self.on_change
                self.add_subscription(topic, payload_type, item=item, bool_values=bool_values, callback=callback)

            if not self.get_iattr_value(item.conf, 'robonect_data_type') in self._battery_items and \
                    self.has_iattr(item.conf, 'robonect_battery_index'):
                self._battery_items[self.get_iattr_value(item.conf, 'robonect_data_type')] = []
            if not self.get_iattr_value(item.conf, 'robonect_data_type') in self._remote_items and \
                    self.has_iattr(item.conf, 'robonect_remote_index'):
                self._remote_items[self.get_iattr_value(item.conf, 'robonect_data_type')] = []

            if self.get_iattr_value(item.conf, 'robonect_data_type') in self._battery_items:
                self._battery_items[self.get_iattr_value(item.conf, 'robonect_data_type')].append(item)
            elif self.get_iattr_value(item.conf, 'robonect_data_type') in self.STATUS_TYPES:
                self._status_items[self.get_iattr_value(item.conf, 'robonect_data_type')] = item
            elif self.get_iattr_value(item.conf, 'robonect_data_type') in self.REMOTE_TYPES:
                self._remote_items[self.get_iattr_value(item.conf, 'robonect_data_type')].append(item)
            else:
                self._items[self.get_iattr_value(item.conf, 'robonect_data_type')] = item
        return

    def parse_logic(self, logic):
        """
        Default plugin parse_logic method
        """
        if 'xxx' in logic.conf:
            # self.function(logic['name'])
            pass

    def update_item(self, item, caller=None, source=None, dest=None):
        """
        Item has been updated

        This method is called, if the value of an item has been updated by SmartHomeNG.
        It should write the changed value out to the device (hardware/interface) that
        is managed by this plugin.

        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        """
        if self.alive and caller != self.get_shortname():
            # code to execute if the plugin is not stopped
            # and only, if the item has not been changed by this this plugin:
            self.logger.info("Update item: {}, item has been changed outside this plugin".format(item.id()))

            if self.has_iattr(item.conf, 'foo_itemtag'):
                self.logger.debug(
                    "update_item was called with item '{}' from caller '{}', source '{}' and dest '{}'".format(item,
                                                                                                               caller,
                                                                                                               source,
                                                                                                               dest))
            pass

    def poll_device(self):
        """
        Polls for updates of the device

        This method is only needed, if the device (hardware/interface) does not propagate
        changes on it's own, but has to be polled to get the actual status.
        It is called by the scheduler which is set within run() method.
        """
        self.get_status_from_api()
        if self._status != 17:
            self.get_mower_information_from_api()
            self.get_battery_data_from_api()
            self.get_remote_from_api()
        return

    def on_change(self, topic, payload, qos=None, retain=None):
        """
        Custom callback method for MQTT changes in items

        :param topic: MQTT topic taken from item, e.g. 'mower/status'
        :param payload: Payload received via MQTT
        """
        if payload is not None:
            if topic == 'mower/status':
                self.logger.debug(
                    "on_change: setting mode for topic %s via mqtt as %s: %s" % (
                    topic, payload, self.get_status_as_text(int(payload))))
                self._status_items['mower/status/text'](self.get_status_as_text(int(payload)))
            elif topic == 'mower/mode':
                self.logger.debug(
                    "on_change: setting mode for topic %s via mqtt as %s: %s" % (
                    topic, payload, self.get_mode_as_text(int(payload))))
                self._status_items['mower/mode/text'](self.get_mode_as_text(int(payload)))

    def get_api_error_code_as_text(self, error_code):
        """
        Returns the api error code as short english string.

        :param error_code: API error code as integer
        :return: API error code as string
        """
        if error_code == 0:
            return 'APIERROR_NO'
        elif error_code == 1:
            return 'APIERROR_INVALIDCMD'
        elif error_code == 2:
            return 'APIERROR_MISSINGPARAMETER'
        elif error_code == 3:
            return 'APIERROR_INVALIDPARAMETER'
        elif error_code == 4:
            return 'APIERROR_CMDFAILED'
        elif error_code == 5:
            return 'APIERROR_FAILURESTATE'
        elif error_code == 6:
            return 'APIERROR_ALREADYRUNNING'
        elif error_code == 7:
            return 'APIERROR_ALREADYSTOPPED'
        elif error_code == 8:
            return 'APIERROR_TIMEOUT'
        elif error_code == 9:
            return 'APIERROR_BUMPED'
        elif error_code == 10:
            return 'APIERROR_SHOCK'
        elif error_code == 11:
            return 'APIERROR_NOSIGNAL'
        elif error_code == 12:
            return 'APIERROR_NOTHINGCHANGED'
        elif error_code == 13:
            return 'APIERROR_NOTINFAILURESTATE'
        elif error_code == 254:
            return 'APIERROR_NOTIMPLEMENTED'
        elif error_code == 255:
            return 'APIERROR_UNSPECIFIED'
        else:
            return None

    def get_mode_as_text(self, mode):
        """
        Returns the mode as short english string.

        :param mode: Mode as integer
        :return: Mode as string
        """
        if mode == 0:
            return 'AUTO'
        elif mode == 1:
            return 'MANUAL'
        elif mode == 2:
            return 'HOME'
        elif mode == 3:
            return 'DEMO'
        else:
            return None

    def get_status_as_text(self, status):
        """
        Returns the status as short english string.

        :param status: Status as integer
        :return: Status as string
        """
        if status == 0:
            return 'DETECTING_STATUS'
        elif status == 1:
            return 'PARKING'
        elif status == 2:
            return 'MOWING'
        elif status == 3:
            return 'SEARCH_CHARGING_STATION'
        elif status == 4:
            return 'CHARGING'
        elif status == 5:
            return 'SEARCHING'
        elif status == 6:
            return 'UNKNOWN_6'
        elif status == 7:
            return 'ERROR_STATUS'
        elif status == 8:
            return 'LOST_SIGNAL'
        elif status == 16:
            return 'OFF'
        elif status == 17:
            return 'SLEEPING'
        else:
            return None

    def get_battery_data_from_api(self):
        """
        Requests battery data from the api and assigns it to items (if available).

        :return: JSON object with battery data
        """
        try:
            self.logger.debug("Plugin '{}': Requesting battery data".format(
                self.get_fullname()))
            response = self._session.get(self._base_url + 'battery', auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_battery_data: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()
        self.set_mower_online()

        if 'battery_id' in self._battery_items and 'batteries' in json_obj:
            for item in self._battery_items['battery_id']:
                item(json_obj['batteries'][int(self.get_iattr_value(item.conf, 'robonect_battery_index'))]['id'],
                     self.get_shortname())
        if 'battery_charge' in self._battery_items and 'batteries' in json_obj:
            for item in self._battery_items['battery_charge']:
                item(json_obj['batteries'][int(self.get_iattr_value(item.conf, 'robonect_battery_index'))]['charge'],
                     self.get_shortname())
        if 'battery_voltage' in self._battery_items and 'batteries' in json_obj:
            for item in self._battery_items['battery_voltage']:
                item(json_obj['batteries'][int(self.get_iattr_value(item.conf, 'robonect_battery_index'))]['voltage'],
                     self.get_shortname())
        if 'battery_current' in self._battery_items and 'batteries' in json_obj:
            for item in self._battery_items['battery_current']:
                item(json_obj['batteries'][int(self.get_iattr_value(item.conf, 'robonect_battery_index'))]['current'],
                     self.get_shortname())
        if 'battery_temperature' in self._battery_items and 'batteries' in json_obj:
            for item in self._battery_items['battery_temperature']:
                item(json_obj['batteries'][int(self.get_iattr_value(item.conf, 'robonect_battery_index'))][
                         'temperature'], self.get_shortname())
        if 'battery_capacity_full' in self._battery_items and 'batteries' in json_obj:
            for item in self._battery_items['battery_capacity_full']:
                item(json_obj['batteries'][int(self.get_iattr_value(item.conf, 'robonect_battery_index'))]['capacity'][
                         'full'], self.get_shortname())
        if 'battery_capacity_remaining' in self._battery_items and 'batteries' in json_obj:
            for item in self._battery_items['battery_capacity_remaining']:
                item(json_obj['batteries'][int(self.get_iattr_value(item.conf, 'robonect_battery_index'))]['capacity'][
                         'remaining'], self.get_shortname())
        return json_obj

    def set_mower_online(self):
        if self._mower_offline:
            self.logger.debug(
                "Plugin '{}': Mower reachable again.".format(
                    self.get_fullname()))
            self._mower_offline = False

    def get_full_error_list(self):
        """
        Requests the full list of possible errors of the automower.

        :return: JSON object with the overall error list
        """
        try:
            self.logger.debug("Plugin '{}': Requesting battery data".format(
                self.get_fullname()))
            response = self._session.get(self._base_url + 'error&list', auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_battery_data: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()
        self.set_mower_online()

        if self._mower_offline:
            self.logger.debug(
                "Plugin '{}': Mower reachable again.".format(
                    self.get_fullname()))
            self._mower_offline = False

        if 'errors' in json_obj:
            return json_obj['errors']

    def start_mower(self):
        """
        Starts the automower.
        :return json response
        """
        try:
            self.logger.debug("Plugin '{}': Starting mower".format(
                self.get_fullname()))
            response = self._session.get(self._base_url + 'start',
                                         auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_battery_data: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()

        self.set_mower_online()

        return json_obj

    def stop_mower(self):
        """
        Stops the automower.
        :return json response
        """
        try:
            self.logger.debug("Plugin '{}': Stopping mower.".format(
                self.get_fullname()))
            response = self._session.get(self._base_url + 'stop',
                                         auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_battery_data: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()
        self.set_mower_online()

        return json_obj

    def set_mode(self, mode, remotestart=None, after=None):
        """
        Sets data for the remote start location.

        :param mode: mode to set ('home','eod','man','auto','job')
        :param remotestart: remote start location, either 0 (standard), 1 (remote start  1), or 2 (remote start 2), only used when mode=job
        :param after: mode to activate after the automower has finished mowing (if not set, return to recent mode). Possible values 1,2,3,4 (needed before V1.0 Beta 8) or 'home','eod','man','auto','job'
        :param start: time, as string in the format 'HH:MM', when the mower should start (if not set: 0)
        :param end: time, as string in the format 'HH:MM', when the mower should start (if not set: +1h)
        :param duration: duration, as minutes (integer), of the mowing order (in combination with either the start or end parameter)
        :return:
        """
        param = ''
        if mode not in self.MODE_TYPES:
            self.logger.error(
                "Plugin '{}': set_mode - invalid mode supplied: '{}' must be one of 'home','eod','man','auto','job'.".
                    format(self.get_fullname(), mode))
            return
        else:
            param += '&mode=%s' % mode
            if mode == 'job':
                if remotestart is not None:
                    if 0 <= remotestart <= 2:
                        param += '&remotestart=%s' % remotestart
                    else:
                        self.logger.error(
                            "Plugin '{}': set_mode - invalid remotestart value supplied: '{}' must be 1, 2, or 3.".
                                format(self.get_fullname(), remotestart))
                if after is not None:
                    if (0 <= after <= 4) or (after in self.MODE_TYPES):
                        param += '&after=%s' % after
                    else:
                        self.logger.error(
                            "Plugin '{}': set_mode - invalid after value supplied: '{}' must be 1, 2, 3, or 4 or "
                            "one of the values 'home','eod','man','auto','job'.".
                                format(self.get_fullname(), after))
                if start is not None:
                    if self.is_time_format(start):
                        param += '&start=%s' % start
                    else:
                        self.logger.error(
                            "Plugin '{}': set_mode - invalid start value supplied: '{}' must be 'HH:MM'.".
                                format(self.get_fullname(), start))
                if end is not None:
                    if self.is_time_format(end):
                        param += '&end=%s' % end
                    else:
                        self.logger.error(
                            "Plugin '{}': set_mode - invalid end value supplied: '{}' must be 'HH:MM'.".
                                format(self.get_fullname(), end))
                if (start is not None and duration is not None) or (end is not None and duration is not None):
                    param += '&duration=%s' % duration


        try:
            self.logger.debug("Plugin '{}': Requesting battery data".format(
                self.get_fullname()))
            response = self._session.get(self._base_url + 'mode' + param,
                                         auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_battery_data: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()
        self.set_mower_online()

        if not json_obj['successful']:
            self.logger.error("Plugin '{}': Error when trying to set mode {} - {}: '{}'.".format(
                self.get_fullname(), mode, str(json_obj['error_code']), json_obj['error_message']))
        else:
            return #self.get_remote()

    def set_remote(self, index, name=None, distance=None, visible=None, proportion=None):
        """
        Sets data for the remote start location.

        :param index: Index of the location as integer (starting with 1)
        :param name: Name of the location as string (leave out if not needed to change)
        :param distance: Distance to keep to the wire as integer (leave out if not needed to change)
        :param visible: Shall location be visible (boolean)?
        :param proportion: Proportion in percent as integer (leave out if not needed to change)
        :return: Newly set remote location data as json (items are also auto-updated
        """
        param = ''
        if name is not None:
            param += '&name%s=%s' % (index, name)
        if distance is not None:
            param += '&distance%s=%s' % (index, distance)
        if visible is not None:
            param += '&visible%s=%s' % (index, int(visible))
        if proportion is not None:
            param += '&proportion%s=%s' % (index, proportion)
        if param == '':
            self.logger.error("Plugin '{}': set_remote did not have any parameters.".format(
                self.get_fullname()))
        try:
            self.logger.debug("Plugin '{}': Requesting battery data".format(
                self.get_fullname()))
            response = self._session.get(self._base_url + 'remote' + param,
                                         auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_battery_data: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()
        self.set_mower_online()

        if not json_obj['successful']:
            self.logger.error("Plugin '{}': Error when trying to set remote data.".format(
                self.get_fullname()))
        else:
            return self.get_remote()

    def get_remote_from_api(self):
        """
        Requests remote starting point data from the api and assigns it to items (if available).

        :return: JSON object with remote starting point data
        """
        try:
            self.logger.debug("Plugin '{}': get_remote.")
            response = self._session.get(self._base_url + 'remote', auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_mower_information: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()
        self.logger.debug(json_obj)
        self.set_mower_online()

        for item in self._remote_items['remotestart_name']:
            key = 'remotestart_%s' % self.get_iattr_value(item.conf, 'robonect_remote_index')
            if key in json_obj:
                item(json_obj[key]['name'], self.get_shortname())

        for item in self._remote_items['remotestart_visible']:
            key = 'remotestart_%s' % self.get_iattr_value(item.conf, 'robonect_remote_index')
            if key in json_obj:
                item(json_obj[key]['visible'], self.get_shortname())

        for item in self._remote_items['remotestart_path']:
            key = 'remotestart_%s' % self.get_iattr_value(item.conf, 'robonect_remote_index')
            if key in json_obj:
                item(json_obj[key]['path'], self.get_shortname())

        for item in self._remote_items['remotestart_proportion']:
            key = 'remotestart_%s' % self.get_iattr_value(item.conf, 'robonect_remote_index')
            if key in json_obj:
                item(json_obj[key]['proportion'], self.get_shortname())

        for item in self._remote_items['remotestart_distance']:
            key = 'remotestart_%s' % self.get_iattr_value(item.conf, 'robonect_remote_index')
            if key in json_obj:
                item(json_obj[key]['distance'], self.get_shortname())

        return json_obj

    def get_mower_information_from_api(self):
        try:
            self.logger.debug("Plugin '{}': get_mower_information.".format(
                self.get_fullname()))
            response = self._session.get(self._base_url + 'version', auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_mower_information: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()
        self.set_mower_online()

        if 'mower' in json_obj:
            if 'hardware_serial' in self._items:
                self._items['hardware_serial'](str(json_obj['mower']['hardware']['serial']), self.get_shortname())

            if 'production_date' in self._items:
                self._items['production_date'](json_obj['mower']['hardware']['production'], self.get_shortname())

            if 'msw_title' in self._items:
                self._items['msw_title'](json_obj['mower']['msw']['title'], self.get_shortname())
            if 'msw_version' in self._items:
                self._items['msw_version'](json_obj['mower']['msw']['version'], self.get_shortname())
            if 'msw_compiled' in self._items:
                self._items['msw_compiled'](json_obj['mower']['msw']['compiled'], self.get_shortname())

        if 'serial' in self._items:
            self._items['serial'](json_obj['serial'], self.get_shortname())

        if 'wlan_sdk-version' in self._items and 'wlan' in json_obj:
            self._items['wlan_sdk-version'](json_obj['wlan']['sdk-version'], self.get_shortname())
        if 'wlan_at-version' in self._items and 'wlan' in json_obj:
            self._items['wlan_at-version'](json_obj['wlan']['at-version'], self.get_shortname())

        if 'robonect_version' in self._items and 'application' in json_obj:
            self._items['robonect_version'](json_obj['application']['version'], self.get_shortname())
        if 'robonect_version_comment' in self._items and 'application' in json_obj:
            self._items['robonect_version_comment'](json_obj['application']['comment'], self.get_shortname())
        if 'robonect_version_compiled' in self._items and 'application' in json_obj:
            self._items['robonect_version_compiled'](json_obj['application']['compiled'], self.get_shortname())
        return

    def get_status_from_api(self):
        try:
            self.logger.debug("Plugin '{}': get_status.".format(
                self.get_fullname()))
            response = self._session.get(self._base_url + 'status', auth=HTTPBasicAuth(self._user, self._password))
        except Exception as e:
            if not self._mower_offline:
                self.logger.error(
                    "Plugin '{}': Exception when sending GET request for get_status: {}".format(
                        self.get_fullname(), str(e)))
            self._mower_offline = True
            return

        json_obj = response.json()
        self.set_mower_online()

        if 'device/name' in self._items:
            self._items['device/name'](json_obj['name'], self.get_shortname())
        if 'robonect_id' in self._items:
            self._items['robonect_id'](json_obj['id'], self.get_shortname())

        if 'status' in json_obj:
            self._status = int(json_obj['status']['status'])
            if 'mower/status' in self._status_items:
                self._status_items['mower/status'](json_obj['status']['status'], self.get_shortname())
                if 'mower/status/text' in self._status_items:
                    self._status_items['mower/status/text'](self.get_status_as_text(self._status_items['mower/status']()))
            if 'mower/distance' in self._status_items:
                self._status_items['mower/distance'](json_obj['status']['distance'], self.get_shortname())
            if 'mower/stopped' in self._status_items:
                self._status_items['mower/stopped'](self.to_bool(json_obj['status']['stopped'], self.get_shortname()))
            if 'mower/status/duration' in self._status_items:
                # round to minutes, as mqtt is also returning minutes instead of seconds
                self._status_items['mower/status/duration'](math.floor(json_obj['status']['duration'] / 60),
                                                            self.get_shortname())
            if 'mower/mode' in self._status_items:
                self._status_items['mower/mode'](json_obj['status']['mode'], self.get_shortname())
                if 'mower/mode/text' in self._status_items:
                    self._status_items['mower/mode/text'](self.get_mode_as_text(self._status_items['mower/mode']()))
            if 'status_battery' in self._status_items:
                self._status_items['status_battery'](json_obj['status']['battery'], self.get_shortname())
            if 'mower/statistic/hours' in self._status_items:
                self._status_items['mower/statistic/hours'](json_obj['status']['hours'], self.get_shortname())

        if 'wlan/rssi' in self._items:
            self._items['wlan/rssi'](json_obj['wlan']['signal'], self.get_shortname())
        if 'health/climate/temperature' in self._items:
            self._items['health/climate/temperature'](json_obj['health']['temperature'], self.get_shortname())
        if 'health/climate/humidity' in self._items:
            self._items['health/climate/humidity'](json_obj['health']['humidity'], self.get_shortname())
        if 'date' in self._items:
            self._items['date'](json_obj['clock']['date'], self.get_shortname())
        if 'time' in self._items:
            self._items['time'](json_obj['clock']['time'], self.get_shortname())
        if 'unix' in self._items:
            self._items['unix'](json_obj['clock']['unix'], self.get_shortname())

        if 'blades' in json_obj:
            if 'blades_quality' in self._status_items:
                self._status_items['blades_quality'](json_obj['blades']['quality'], self.get_shortname())
            if 'blades_days' in self._status_items:
                self._status_items['blades_days'](json_obj['blades']['days'], self.get_shortname())
            if 'blades_hours' in self._status_items:
                self._status_items['blades_hours'](json_obj['blades']['hours'], self.get_shortname())

        if 'mower/error/code' in self._status_items:
            if 'error' in json_obj:
                self._status_items['mower/error/code'](json_obj['error']['error_code'])
            else:
                self._status_items['mower/error/code'](0)
        if 'mower/error/message' in self._status_items:
            if 'error' in json_obj:
                self._status_items['mower/error/message'](json_obj['error']['error_message'])
            else:
                self._status_items['mower/error/message']('')
        if 'error_date' in self._status_items:
            if 'error' in json_obj:
                self._status_items['error_date'](json_obj['error']['date'])
            else:
                self._status_items['error_date']('')
        if 'error_time' in self._status_items:
            if 'error' in json_obj:
                self._status_items['error_time'](json_obj['error']['time'])
            else:
                self._status_items['error_time']('')
        if 'error_unix' in self._status_items:
            if 'error' in json_obj:
                self._status_items['error_unix'](json_obj['error']['unix'])
            else:
                self._status_items['error_unix']('')
        return

    def get_status(self):
        return self._status

    def get_ip(self):
        return self._ip

    def get_user(self):
        return self._user

    def get_password(self):
        return self._password

    def get_items(self):
        return self._items

    def get_status_items(self):
        return self._status_items

    def get_battery_items(self):
        return self._battery_items

    def get_remote_items(self):
        return self._remote_items

    def is_mower_offline(self):
        return self._mower_offline

    def get_cycle(self):
        return self._cycle

    def is_time_format(input):
        try:
            time.strptime(input, '%H:%M')
            return True
        except ValueError:
            return False