#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#     ||          ____  _ __
#  +------+      / __ )(_) /_______________ _____  ___
#  | 0xBC |     / __  / / __/ ___/ ___/ __ `/_  / / _ \
#  +------+    / /_/ / / /_/ /__/ /  / /_/ / / /_/  __/
#   ||  ||    /_____/_/\__/\___/_/   \__,_/ /___/\___/
#
#  Copyright (C) 2011-2013 Bitcraze AB
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

#  You should have received a copy of the GNU General Public License along with
#  this program; if not, write to the Free Software Foundation, Inc.,
#  51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""
The bootloader dialog is used to update the Crazyflie firmware and to
read/write the configuration block in the Crazyflie flash.
"""
from cflib.bootloader import Bootloader
from cfclient.ui.connectivity_manager import ConnectivityManager

import tempfile
import logging
import json
import os
import threading
from urllib.request import urlopen
from urllib.error import URLError
import zipfile

from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import pyqtSlot, pyqtSignal, QThread

import cfclient
import cflib.crazyflie

__author__ = 'Bitcraze AB'
__all__ = ['BootloaderDialog']

logger = logging.getLogger(__name__)

service_dialog_class = uic.loadUiType(cfclient.module_path +
                                      "/ui/dialogs/bootloader.ui")[0]

# This url is used to fetch all the releases from the FirmwareDownloader
RELEASE_URL = 'https://api.github.com/repos/bitcraze/'\
              'crazyflie-release/releases'


class BootloaderDialog(QtWidgets.QWidget, service_dialog_class):
    """Tab for update the Crazyflie firmware and for reading/writing the config
    block in flash"""

    class UIState:
        DISCONNECTED = 0
        COLD_CONNECTING = 1
        COLD_CONNECTED = 2
        FW_CONNECTING = 3
        FW_CONNECTED = 4
        FW_SCANNING = 5
        FLASHING = 6
        RESET = 7

    _release_firmwares_found = pyqtSignal(object)
    _release_downloaded = pyqtSignal(str, object)

    def __init__(self, helper, *args):
        super(BootloaderDialog, self).__init__(*args)
        self.setupUi(self)

        self.tabName = "Service"
        self.menuName = "Service"

        # self.tabWidget = tabWidget
        self.helper = helper

        # self.cf = crazyflie
        self.clt = CrazyloadThread(self.helper.cf)

        # Connecting GUI signals (a pity to do that manually...)
        self.imagePathBrowseButton.clicked.connect(self.pathBrowse)
        self.programButton.clicked.connect(self.programAction)
        self.coldBootButton.clicked.connect(self.initiateColdboot)
        self.resetButton.clicked.connect(self.resetCopter)
        self._cancel_bootloading.clicked.connect(self.close)
        self.sourceTab.currentChanged.connect(
            lambda _: self.updateChipSelectRadio())

        self.helper.connectivity_manager.register_ui_elements(
            ConnectivityManager.UiElementsContainer(
                interface_combo=self.comboBox,
                address_spinner=self.address,
                connect_button=self.connectButton,
                scan_button=self.scanButton))
        self.helper.connectivity_manager.connection_state_changed.connect(self._fw_connection_state_changed)

        # connecting other signals
        self.clt.programmed.connect(self.programDone)
        self.clt.statusChanged.connect(self.statusUpdate)
        # self.clt.updateBootloaderStatusSignal.connect(
        #                                         self.updateBootloaderStatus)
        self.clt.connectingSignal.connect(
            lambda: self.setUiState(self.UIState.COLD_CONNECTING))
        self.clt.connectedSignal.connect(
            lambda: self.setUiState(self.UIState.COLD_CONNECTED))
        self.clt.failed_signal.connect(lambda m: self._ui_connection_fail(m))
        self.clt.disconnectedSignal.connect(
            lambda: self.setUiState(self.UIState.DISCONNECTED))

        self._cold_boot_error_message = None
        self._state = self.UIState.DISCONNECTED

        self._releases = {}
        self._release_firmwares_found.connect(self._populate_firmware_dropdown)
        self._release_downloaded.connect(self.release_zip_downloaded)
        self.firmware_downloader = FirmwareDownloader(
                                        self._release_firmwares_found,
                                        self._release_downloaded)
        self.firmware_downloader.get_firmware_releases()

        self.firmware_downloader.start()
        self.clt.start()

    def _ui_connection_fail(self, message):
        self._cold_boot_error_message = message
        self.setUiState(self.UIState.DISCONNECTED)

    def setUiState(self, state):
        self._state = state

        if (state == self.UIState.DISCONNECTED):
            self.resetButton.setEnabled(False)
            self.programButton.setEnabled(False)
            if self._cold_boot_error_message is not None:
                self.setStatusLabel(self._cold_boot_error_message)
            else:
                self.setStatusLabel("Not connected")
            self.coldBootButton.setEnabled(True)
            self.progressBar.setTextVisible(False)
            self.progressBar.setValue(0)
            self.statusLabel.setText('Status: <b>IDLE</b>')
            self.helper.connectivity_manager.set_enable(True)
        elif (state == self.UIState.COLD_CONNECTING):
            self._cold_boot_error_message = None
            self.resetButton.setEnabled(False)
            self.programButton.setEnabled(False)
            self.setStatusLabel("Trying to connect cold bootloader, restart the Crazyflie to connect")
            self.coldBootButton.setEnabled(False)
            self.helper.connectivity_manager.set_enable(False)
        elif (state == self.UIState.COLD_CONNECTED):
            self._cold_boot_error_message = None
            self.resetButton.setEnabled(True)
            self.programButton.setEnabled(True)
            self.setStatusLabel("Connected to bootloader")
            self.coldBootButton.setEnabled(False)
            self.helper.connectivity_manager.set_enable(False)
        elif (state == self.UIState.FW_CONNECTING):
            self._cold_boot_error_message = None
            self.resetButton.setEnabled(False)
            self.programButton.setEnabled(False)
            self.setStatusLabel("Trying to connect in firmware mode")
            self.coldBootButton.setEnabled(False)
            self.helper.connectivity_manager.set_enable(True)
        elif (state == self.UIState.FW_CONNECTED):
            self._cold_boot_error_message = None
            self.resetButton.setEnabled(False)
            self.programButton.setEnabled(True)
            self.setStatusLabel("Connected in firmware mode")
            self.coldBootButton.setEnabled(False)
            self.helper.connectivity_manager.set_enable(True)
        elif (state == self.UIState.FW_SCANNING):
            self._cold_boot_error_message = None
            self.resetButton.setEnabled(False)
            self.programButton.setEnabled(False)
            self.setStatusLabel("Scanning")
            self.coldBootButton.setEnabled(False)
            self.helper.connectivity_manager.set_enable(True)
        elif (state == self.UIState.RESET):
            self._cold_boot_error_message = None
            self.setStatusLabel("Resetting to firmware, disconnected")
            self.resetButton.setEnabled(False)
            self.programButton.setEnabled(False)
            self.coldBootButton.setEnabled(False)
            self.helper.connectivity_manager.set_enable(False)

    def setStatusLabel(self, text):
        self.connectionStatus.setText("Status: <b>%s</b>" % text)

    def resetCopter(self):
        self.clt.resetCopterSignal.emit()
        self.setUiState(self.UIState.RESET)

    def updateConfig(self, channel, speed, rollTrim, pitchTrim):
        self.rollTrim.setValue(rollTrim)
        self.pitchTrim.setValue(pitchTrim)
        self.radioChannel.setValue(channel)
        self.radioSpeed.setCurrentIndex(speed)

    def closeEvent(self, event):
        self.clt.terminate_flashing()
        # Remove downloaded-firmware files.
        self.firmware_downloader.bootload_complete.emit()
        self.setUiState(self.UIState.RESET)
        self.clt.resetCopterSignal.emit()

    def _populate_firmware_dropdown(self, releases):
        """ Callback from firmware-downloader that retrieves all
            the latest firmware-releases.
        """
        for release in releases:
            release_name = release[0]
            for download in release[1:]:
                download_name, download_link = download
                widget_name = '%s - %s' % (release_name, download_name)
                self._releases[widget_name] = download_link
                self.firmwareDropdown.addItem(widget_name)

    def release_zip_downloaded(self, release_name, release_path):
        """ Callback when a release is succesfully downloaded and
            save to release_path.
        """
        self.downloadStatus.setText('Downloaded')
        self.clt.program.emit(release_path, '')

    def updateChipSelectRadio(self):
        if self.sourceTab.currentWidget() == self.tabFromFile:
            if self.imagePathLine.text().endswith(".zip"):
                self.radioBoth.setEnabled(True)
                self.radioBoth.setChecked(True)
            elif self.imagePathLine.text().endswith(".bin"):
                self.radioBoth.setEnabled(False)
                self.radioStm32.setChecked(True)
        else:
            self.radioBoth.setEnabled(True)
            self.radioBoth.setChecked(True)

    def _fw_connection_state_changed(self, new_state):
        if new_state == ConnectivityManager.UIState.DISCONNECTED:
            self.setUiState(self.UIState.DISCONNECTED)
        elif new_state == ConnectivityManager.UIState.CONNECTING:
            self.setUiState(self.UIState.FW_CONNECTING)
        elif new_state == ConnectivityManager.UIState.CONNECTED:
            self.setUiState(self.UIState.FW_CONNECTED)
        elif new_state == ConnectivityManager.UIState.SCANNING:
            self.setUiState(self.UIState.FW_SCANNING)

    @pyqtSlot()
    def pathBrowse(self):
        filename = ""
        # Fix for crash in X on Ubuntu 14.04
        filename, _ = QtWidgets.QFileDialog.getOpenFileName()
        if filename != "" and filename[-4:] in (".bin", ".zip"):
            self.imagePathLine.setText(filename)
            self.updateChipSelectRadio()
        elif filename != "":
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText("Wrong file extention. Must be .bin or .zip.")
            msgBox.exec_()

        pass

    @pyqtSlot()
    def programAction(self):
        # self.setStatusLabel("Initiate programming")
        self.resetButton.setEnabled(False)
        self.programButton.setEnabled(False)
        self.imagePathBrowseButton.setEnabled(False)

        if self._state == self.UIState.COLD_CONNECTED:
            self.clt.set_boot_mode(self.clt.COLD_BOOT)
        else:
            self.clt.set_boot_mode(self.clt.WARM_BOOT)

        # call the flasher
        if self.sourceTab.currentWidget() == self.tabFromFile:
            if self.imagePathLine.text() == "":
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please choose an image file to program.")
                msgBox.exec_()

                self.resetButton.setEnabled(True)
                self.programButton.setEnabled(True)
                self.imagePathBrowseButton.setEnabled(True)
                return

            # by default, both of the mcu:s are flashed
            mcu_to_flash = None

            if self.radioStm32.isChecked():
                mcu_to_flash = 'stm32'
            elif self.radioNrf51.isChecked():
                mcu_to_flash = 'nrf51'
            self.clt.program.emit(self.imagePathLine.text(), mcu_to_flash)
        else:
            requested_release = self.firmwareDropdown.currentText()
            download_url = self._releases[requested_release]
            self.downloadStatus.setText('Fetching...')
            self.firmware_downloader.download_release(requested_release,
                                                      download_url)

    @pyqtSlot(bool)
    def programDone(self, success):
        if success:
            self.statusLabel.setText('Status: <b>Programing complete!</b>')
            self.downloadStatus.setText('')

        else:
            self.statusLabel.setText('Status: <b>Programing failed!</b>')

        self.resetButton.setEnabled(True)
        self.programButton.setEnabled(True)
        self.imagePathBrowseButton.setEnabled(True)

    @pyqtSlot(str, int)
    def statusUpdate(self, status, progress):
        logger.debug("Status: [%s] | %d", status, progress)
        self.statusLabel.setText('Status: <b>' + status + '</b>')
        if progress >= 0:
            self.progressBar.setValue(progress)

    def initiateColdboot(self):
        self.clt.initiateColdBootSignal.emit("radio://0/100")


# No run method specified here as the default run implementation is running the
# event loop which is what we want
class CrazyloadThread(QThread):
    # Input signals declaration (not sure it should be used like that...)
    program = pyqtSignal(str, str)
    initiateColdBootSignal = pyqtSignal(str)
    resetCopterSignal = pyqtSignal()
    writeConfigSignal = pyqtSignal(int, int, float, float)
    # Output signals declaration
    programmed = pyqtSignal(bool)
    verified = pyqtSignal()
    statusChanged = pyqtSignal(str, int)
    connectedSignal = pyqtSignal()
    connectingSignal = pyqtSignal()
    failed_signal = pyqtSignal(str)
    disconnectedSignal = pyqtSignal()
    updateConfigSignal = pyqtSignal(int, int, float, float)
    updateCpuIdSignal = pyqtSignal(str)

    radioSpeedPos = 2

    WARM_BOOT = 0
    COLD_BOOT = 1

    def __init__(self, crazyflie: cflib.crazyflie.Crazyflie):
        super(CrazyloadThread, self).__init__()

        self._terminate_flashing = False

        self._bl = Bootloader()
        self._bl.progress_cb = self.statusChanged.emit
        self._bl.terminate_flashing_cb = lambda: self._terminate_flashing

        self._cf = crazyflie

        self._boot_mode = self.COLD_BOOT

        # Make sure that the signals are handled by this thread event loop
        self.moveToThread(self)

        self.program.connect(self.programAction)
        self.initiateColdBootSignal.connect(self.initiateColdBoot)
        self.resetCopterSignal.connect(self.resetCopter)

    def __del__(self):
        self.quit()
        self.wait()

    def set_boot_mode(self, mode):
        self._boot_mode = mode

    def initiateColdBoot(self, linkURI):
        self.connectingSignal.emit()

        try:
            success = self._bl.start_bootloader(warm_boot=False)
            if not success:
                self.failed_signal.emit("Could not connect to bootloader")
            else:
                self.connectedSignal.emit()
        except Exception as e:
            self.failed_signal.emit("{}".format(e))

    def rebootToBootloader(self):
        self._bl.clink = self._cf.link_uri
        self._cf.close_link()

        try:
            success = self._bl.start_bootloader(warm_boot=True)
            if not success:
                self.failed_signal.emit("Could not connect to bootloader")
            else:
                self.connectedSignal.emit()
        except Exception as e:
            self.failed_signal.emit("{}".format(e))

    def programAction(self, filename, mcu_to_flash):

        if self._boot_mode == self.WARM_BOOT:
            self.rebootToBootloader()

        targets = {}
        if mcu_to_flash:
            targets[mcu_to_flash] = ("fw",)
        try:
            self._terminate_flashing = False
            self._bl.flash(str(filename), targets)
            self.programmed.emit(True)
        except Exception:
            self.programmed.emit(False)

    def terminate_flashing(self):
        self._terminate_flashing = True

    def resetCopter(self):
        try:
            self._bl.reset_to_firmware()
        except Exception:
            pass
        self._bl.close()
        self.disconnectedSignal.emit()


class FirmwareDownloader(QThread):
    """ Uses github API to retrieves firmware-releases. """

    bootload_complete = pyqtSignal()

    def __init__(self, qtsignal_get_all_firmwares, qtsignal_get_release):
        super(FirmwareDownloader, self).__init__()

        self._qtsignal_get_all_firmwares = qtsignal_get_all_firmwares
        self._qtsignal_get_release = qtsignal_get_release

        self._tempDirectory = tempfile.TemporaryDirectory()
        self._filepath = os.path.join(self._tempDirectory.name,
                                      'tmp.zip')
        self.moveToThread(self)

    def get_firmware_releases(self):
        """ Wrapper-function """
        threading.Thread(target=self._get_firmware_releases,
                         args=(self._qtsignal_get_all_firmwares, )).start()

    def download_release(self, release_name, url):
        """ Wrapper-function """
        threading.Thread(target=self._download_release,
                         args=(self._qtsignal_get_release,
                               release_name, url)).start()

    def _get_firmware_releases(self, signal):
        """ Gets the firmware releases from the github API
            and returns a list of format [rel-name, {release: download-link}].
            Returns None if the request fails.
        """
        response = {}
        try:
            with urlopen(RELEASE_URL) as resp:
                response = json.load(resp)
        except URLError:
            logger.warning(
                'Failed to make web request to get firmware-release')

        release_list = []

        for release in response:
            release_name = release['name']
            if release_name:
                releases = [release_name]
                for download in release['assets']:
                    releases.append(
                        (download['name'], download['browser_download_url']))
                release_list.append(releases)

        if release_list:
            signal.emit(release_list)
        else:
            logger.warning('Failed to parse firmware-releases in web request')

    def _download_release(self, signal, release_name, url):
        """ Downloads the given release and calls the callback signal
            if successful.
        """
        try:
            # Check if we have an old file saved and if so, ensure it's a valid
            # zipfile and then call signal
            with open(self._filepath, 'rb') as f:
                previous_release = zipfile.ZipFile(f)
                # testzip returns None if it's OK.
                if previous_release.testzip() is None:
                    logger.info('Using same firmware-release file at'
                                '%s' % self._filepath)
                    signal.emit(release_name, self._filepath)
                    return
        except FileNotFoundError:
            try:
                # Fetch the file with a new web request and save it to
                # a temporary file.
                with urlopen(url) as response:
                    with open(self._filepath, 'wb') as release_file:
                        release_file.write(response.read())
                    logger.info('Created temporary firmware-release file at'
                                '%s' % self._filepath)
                    signal.emit(release_name, self._filepath)
            except URLError:
                logger.warning('Failed to make web request to get requested'
                               ' firmware-release')
