import subprocess
import zipfile
import io
import re
import requests
import io
import os
import time
import logging
from gi.repository import Gtk,GLib
import platform
import psutil

from eovpn_base import Base, ThreadManager, SettingsManager

logger = logging.getLogger(__name__)


class OpenVPN:

    def __init__(self, timeout=120):
        self.timeout = timeout    

    def get_connection_status(self) -> bool:

        nif = psutil.net_if_stats()

        for nif_a in nif.keys():
            if "tun" in nif_a:
                if nif[nif_a].isup:
                    return True

        return False


    def connect(self, *args):
        
        openvpn_exe_cmd = []

        openvpn_exe_cmd.append("pkexec")
        openvpn_exe_cmd.append("openvpn")

        for arg in args:
            openvpn_exe_cmd.append(arg)    
        
        logger.info("args = {}".format(args))
        out = subprocess.run(openvpn_exe_cmd, stdout=subprocess.PIPE)
        start_time = time.time()

        while True and ((time.time() - start_time) <= self.timeout):
            connection_status = self.get_connection_status()
            logger.debug("status = {}".format(connection_status))

            if connection_status:
                return True
            else:
                time.sleep(1)
        return False

    def disconnect(self):

        subprocess.call(["pkexec", "killall", "openvpn"])
        start_time = time.time()

        while True and ((time.time() - start_time) <= self.timeout):
            connection_status = self.get_connection_status()

            if not connection_status:
                return True

        return False

    def get_version(self):

        opvpn_ver = re.compile("OpenVPN [0-9]*.[0-9]*.[0-9]")
        
        try:
            out = subprocess.run(["openvpn", "--version"], stdout=subprocess.PIPE)
        except Exception as e:
            logger.critical(str(e))
            not_found()
  
        out = out.stdout.decode('utf-8')
        ver = opvpn_ver.findall(out)

        if len(ver) > 0:
            return ver[0]

        return False

class OpenVPN_eOVPN(SettingsManager):

    def __init__(self, statusbar=None, spinner=None, statusbar_icon=None):

        super(OpenVPN_eOVPN, self).__init__()
        self.openvpn = OpenVPN(120)

        self.spinner = spinner
        self.statusbar = statusbar
        self.statusbar_icon = statusbar_icon

        self.ovpn = re.compile('.ovpn')
        self.crt = re.compile(r'.crt|cert')
    
    def __set_statusbar_icon(self, result: bool, connected: bool = False):
        if self.statusbar_icon is not None:
            if result and connected:
                self.statusbar_icon.set_from_icon_name("network-vpn-symbolic", 1)
            elif result is None:
                self.statusbar_icon.set_from_icon_name("emblem-important-symbolic", 1)
            elif result:
                self.statusbar_icon.set_from_icon_name("emblem-ok-symbolic", 1)
            else:
                self.statusbar_icon.set_from_icon_name("dialog-error-symbolic", 1)


    def connect_eovpn(self, openvpn_config, auth_file, ca=None, logfile=None, callback=None) -> bool:

        self.spinner.start()
        self.statusbar.push(1, "Connecting..")

        connection_result = self.openvpn.connect("--config", openvpn_config, "--auth-user-pass", auth_file, "--ca", ca,
                     "--log", logfile, "--daemon")

        if connection_result:
            self.statusbar.push(1, "Connected to {}.".format(openvpn_config.split('/')[-1]))
            self.__set_statusbar_icon(True, connected=True)
        else:
            self.__set_statusbar_icon(False)

        callback(connection_result)
        self.spinner.stop()
        return connection_result  
        

    def disconnect_eovpn(self, callback=None):

        self.spinner.start()
        self.statusbar.push(1, "Disconnecting..")
        self.__set_statusbar_icon(None)

        disconnect_result = self.openvpn.disconnect()
  
        self.spinner.stop()
        if disconnect_result:
            self.statusbar.push(1, "Disconnected.")

        callback(disconnect_result)
        return disconnect_result
        
    def get_connection_status_eovpn(self) -> bool:
        return self.openvpn.get_connection_status()


    def get_version_eovpn(self):
        self.spinner.stop()
        version = self.openvpn.get_version()
        print(version)

        def not_found():
            self.statusbar.push(1, "OpenVPN not found.")
            self.__set_statusbar_icon(False)

        if version is False:
            not_found()
            return False
        else:
            self.statusbar.push(1, version)
            return True    

        return False    
    
    def load_configs_to_tree(self, storage, config_folder):
        try:
            config_list = os.listdir(config_folder)
            config_list.sort()
        except Exception as e:
            logger.error(str(e))
            return False

        try:
            try:
                storage.clear()
            except AttributeError:
                pass

            if len(config_list) <= 0:
                return False

        except Exception as e:
            logger.error(str(e))    

        for f in config_list:
            if f.endswith(".ovpn"):
                storage.append([f])
    
    def download_config_to_dest_plain(self, remote, destination):

        try:
            test_remote = requests.get(remote, timeout=360)
        except Exception as e:
            logger.error(str(e))

        if test_remote.status_code == 200:

            x_zip = zipfile.ZipFile(io.BytesIO(test_remote.content), "r")
            files_in_zip = x_zip.namelist()

            configs = list( filter(self.ovpn.findall, files_in_zip) )
            certs = list( filter(self.crt.findall, files_in_zip ) )
            all_files = configs + certs
            if len(configs) > 0:

                for file_name in all_files:
                            
                    file = x_zip.getinfo(file_name)
                    file.filename = os.path.basename(file.filename) #remove nested dir
                    logger.info(file.filename)
                    x_zip.extract(file, destination)
                return True
            return False  


    def download_config(self, remote, destination, storage):

        def download():

            self.spinner.start()

            if self.download_config_to_dest_plain(remote, destination):

                self.statusbar.push(1, "Config(s) updated!")
                self.__set_statusbar_icon(True)
                GLib.idle_add(self.load_configs_to_tree,
                              storage,
                              self.get_setting("remote_savepath"))
            else:
                self.statusbar.push(1, "No config(s) found!")
                self.__set_statusbar_icon(False)

            self.spinner.stop()
        
        if not os.path.exists(destination):
            os.mkdir(destination)

        ThreadManager().create(download, None, True)



    def validate_remote(self, remote):

        def validate():
            self.spinner.start()

            try:
                test_remote = requests.get(remote, timeout=360)
                if test_remote.status_code == 200:
                    x_zip = zipfile.ZipFile(io.BytesIO(test_remote.content), "r")
                    configs = list( filter(self.ovpn.findall, x_zip.namelist() ) )
                    if len(configs) > 0:
                        GLib.idle_add(self.message_dialog, "Success", "Valid Remote", "{} OpenVPN configuration's found.".format(len(configs)))
                    else:
                        raise Exception("No configs found!")
            except Exception as e:
                GLib.idle_add(self.message_dialog, "Validate Error", "Error", str(e))
            self.spinner.stop()
            

        ThreadManager().create(validate, None, True)