#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#     ||          ____  _ __
#  +------+      / __ )(_) /_______________ _____  ___
#  | 0xBC |     / __  / / __/ ___/ ___/ __ `/_  / / _ \
#  +------+    / /_/ / / /_/ /__/ /  / /_/ / / /_/  __/
#   ||  ||    /_____/_/\__/\___/_/   \__,_/ /___/\___/
#
#  Copyright (C) 2021 Bitcraze AB
#
#  Crazyflie Nano Quadcopter Client
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
#  02110-1301, USA.
from collections import namedtuple

__author__ = 'Bitcraze AB'
__all__ = ['ConnectivityManager']


class ConnectivityManager:
    UiElementsContainer = namedtuple('UiElementContainer', [
        'interface_combo',
        'address_spinner',
        'connect_button',
        'scan_button'])

    def __init__(self):
        self._ui_elements = []
        self._connect_button_clicked_cb = None
        self._scan_button_clicked_cb = None
        self._interface_combo_current_index_changed_cb = None

    def register_ui_elements(self, ui_elements):
        self._ui_elements.append(ui_elements)

        ui_elements.connect_button.clicked.connect(self._connect_button_click_handler)
        ui_elements.scan_button.clicked.connect(self._scan_button_click_handler)

        ui_elements.address_spinner.valueChanged.connect(self._address_changed_handler)
        ui_elements.address_spinner.editingFinished.connect(self._address_edited_handler)

        ui_elements.interface_combo.currentIndexChanged['QString'].connect(
            self._interface_combo_current_index_changed_handler)

    def set_state_disconnected(self, can_connect):
        for ui_elements in self._ui_elements:
            ui_elements.connect_button.setText("Connect")
            ui_elements.connect_button.setToolTip("Connect to the Crazyflie on the selected interface (Ctrl+I)")
            ui_elements.connect_button.setEnabled(can_connect)
            ui_elements.scan_button.setText("Scan")
            ui_elements.scan_button.setEnabled(True)
            ui_elements.address_spinner.setEnabled(True)
            ui_elements.interface_combo.setEnabled(True)

    def set_state_connected(self):
        for ui_elements in self._ui_elements:
            ui_elements.connect_button.setText("Disconnect")
            ui_elements.connect_button.setToolTip("Disconnect from the Crazyflie (Ctrl+I)")
            ui_elements.scan_button.setEnabled(False)
            ui_elements.address_spinner.setEnabled(False)
            ui_elements.interface_combo.setEnabled(False)

    def set_state_connecting(self):
        for ui_elements in self._ui_elements:
            ui_elements.connect_button.setText("Cancel")
            ui_elements.connect_button.setToolTip("Cancel connecting to the Crazyflie")
            ui_elements.scan_button.setEnabled(False)
            ui_elements.address_spinner.setEnabled(False)
            ui_elements.interface_combo.setEnabled(False)

    def set_state_scanning(self):
        for ui_elements in self._ui_elements:
            ui_elements.connect_button.setText("Connect")
            ui_elements.connect_button.setEnabled(False)
            ui_elements.scan_button.setText("Scanning...")
            ui_elements.scan_button.setEnabled(False)
            ui_elements.address_spinner.setEnabled(False)
            ui_elements.interface_combo.setEnabled(False)

    def set_address(self, address):
        for ui_elements in self._ui_elements:
            ui_elements.address_spinner.setValue(address)

    def get_address(self):
        if len(self._ui_elements) > 0:
            return self._ui_elements[0].address_spinner.value()
        else:
            return 0

    def set_interfaces(self, interface_items, index):
        for ui_elements in self._ui_elements:
            combo = ui_elements.interface_combo

            combo.clear()
            combo.addItems(interface_items)
            combo.setCurrentIndex(index)

    def connect_button_clicked_connect(self, clicked_cb):
        self._connect_button_clicked_cb = clicked_cb

    def scan_button_clicked_connect(self, clicked_cb):
        self._scan_button_clicked_cb = clicked_cb

    def interface_combo_current_index_changed_connect(self, changed_cb):
        self._interface_combo_current_index_changed_cb = changed_cb

    def _connect_button_click_handler(self):
        if self._connect_button_clicked_cb is not None:
            self._connect_button_clicked_cb()

    def _scan_button_click_handler(self):
        if self._scan_button_clicked_cb is not None:
            self._scan_button_clicked_cb(self.get_address())

    def _address_changed_handler(self, value):
        for ui_elements in self._ui_elements:
            if value != ui_elements.address_spinner.value():
                ui_elements.address_spinner.setValue(value)

    def _address_edited_handler(self):
        # Find out if one of the addresses has changed and what the new value is
        value = 0
        is_changed = False
        for ui_elements in self._ui_elements:
            if ui_elements.address_spinner.is_text_different_from_value():
                value = ui_elements.address_spinner.value()
                is_changed = True
                break

        # Set the new value
        if is_changed:
            for ui_elements in self._ui_elements:
                if value != ui_elements.address_spinner.value():
                    ui_elements.address_spinner.setValue(value)

    def _interface_combo_current_index_changed_handler(self, interface):
        for ui_elements in self._ui_elements:
            combo = ui_elements.interface_combo
            if combo.currentText != interface:
                combo.setCurrentText(interface)

        if self._interface_combo_current_index_changed_cb is not None:
            self._interface_combo_current_index_changed_cb(interface)