from gi.repository import Gtk, GLib, Gdk, GdkPixbuf, Gio

from eovpn_base import Base, SettingsManager
from settings_window import SettingsWindow
from log_window import LogWindow
from about_dialog import AboutWindow
from openvpn import OpenVPN
import requests
import typing
import json
import re
import subprocess
import logging
import io
import zipfile
import threading
import time
import datetime

logger = logging.getLogger(__name__)

class MainWindow(Base):
    def __init__(self, app):
        super(MainWindow, self).__init__()
        self.app = app
        self.builder = self.get_builder("main.glade")
        self.builder.connect_signals(MainWindowSignalHandler(self.builder))
        self.window = self.builder.get_object("mainwindow")

        self.window.set_title("eOVPN")
        self.window.set_icon_name(self.APP_ID)

        self.app.add_window(self.window)


    def show(self):
        self.window.show_all()




class MainWindowSignalHandler(SettingsManager):
    def __init__(self, builder):
        super(MainWindowSignalHandler, self).__init__()
        
        self.builder = builder
        self.statusbar = self.builder.get_object("statusbar")
        self.spinner = self.builder.get_object("main_spinner")
        self.last_updated = builder.get_object("last_updated_lbl")
        self.config_storage = builder.get_object("config_storage")
        self.statusbar_icon = builder.get_object("statusbar_icon")

        self.config_selected = None
        self.is_connected = False
        self.connect_btn = self.builder.get_object("connect_btn")

        #reset session.log
        open(self.EOVPN_CONFIG_DIR + "/session.log", 'w').close()

        #GLib.idle_add(self.update_status_ip_loc_flag)
        

        self.ovpn = OpenVPN(self.statusbar, self.spinner, self.statusbar_icon, self.update_status_ip_loc_flag)
        self.ovpn.get_version()
        self.ovpn.load_configs_to_tree(self.config_storage, self.get_setting("remote_savepath"))

        if (ts := self.get_setting("last_update_timestamp")) is not None:
            self.last_updated.set_text("Last Updated: {}".format(ts))

        self.update_status_ip_loc_flag()    




    def on_settings_btn_clicked(self, button):
        settings_window = SettingsWindow()
        settings_window.show()

    def on_log_btn_clicked(self, button):
        log_window = LogWindow()
        log_window.show()


    def on_about_btn_clicked(self, button):
        about_window = AboutWindow()
        about_window.show()


    def on_config_treeview_cursor_changed(self, tree):
        model, path = tree.get_selection().get_selected_rows()
        try:
            model_iter = model.get_iter(path)
            self.config_selected = model.get_value(model_iter, 0)
        except Exception as e:
            logger.error(str(e))    


    def update_status_ip_loc_flag(self) -> None:
        try:
            ip = requests.get("http://ip-api.com/json/")
            logger.debug(ip.content)
            
        except Exception as e:
            logging.warning(e)
            return False

        if ip.status_code != 200:
            return None
        else:
            ip = json.loads(ip.content)    
        
        builder = self.get_builder("main.glade")

        status_label = builder.get_object("status_lbl")
        ctx = status_label.get_style_context()

        if self.ovpn.get_connection_status():
            status_label.set_text("Connected")

            #set css class
            ctx.remove_class("vpn_disconnected")
            ctx.add_class("vpn_connected")
            logger.info("connection status = True")

            #change btn text
            self.connect_btn.set_label("Disconnect!")
            self.is_connected = True

        else:
            
            logger.info("connection status = False")

            status_label.set_text("Disconnected")
            ctx.remove_class("vpn_connected")
            ctx.add_class("vpn_disconnected")
            self.connect_btn.set_label("Connect!")

            self.is_connected = False
                


        ip_label = builder.get_object("ip_lbl")
        ip_label.set_text(ip['query'])

        location_label = builder.get_object("location_lbl")
        location_label.set_text(ip['country'])
        logger.info("location={}".format(ip['country']))

        country_image = builder.get_object("country_image")

        country_id = ip['country'].replace(" ","-").lower()
        pic = self.get_country_image(country_id)
        country_image.set_from_pixbuf(pic)

    def on_copy_btn_clicked(self, ip):
        ip = ip.get_text()
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(ip, -1)
        logger.info("{} copied to clipboard.".format(ip))

    def on_update_btn_clicked(self, button):
        self.ovpn.download_config(self.get_setting("remote"), self.get_setting("remote_savepath"))
        timestamp = str(datetime.datetime.fromtimestamp(time.time()))
        self.last_updated.set_text("Last Updated: {}".format(
            timestamp
        ))

        self.set_setting("last_update_timestamp", timestamp)

        #TODO: figure this out
        self.ovpn.load_configs_to_tree(self.config_storage, self.get_setting("remote_savepath"))

    def on_connect_btn_clicked(self, button):

        log_file = self.EOVPN_CONFIG_DIR + "/session.log"

        if self.is_connected:
            disconnect = threading.Thread(target=self.ovpn.disconnect, args=(log_file,))
            disconnect.start()
            return True
        
        try:
            config_file = self.get_setting("remote_savepath") + "/" + self.config_selected
        except TypeError:
            self.statusbar.push(1, "No config selected.")
            self.statusbar_icon.set_from_icon_name("dialog-warning", 1)
            return False

        auth_file = self.EOVPN_CONFIG_DIR + "/auth.txt"
        crt = self.get_setting("crt")

        x = threading.Thread(target=self.ovpn.connect, args=(config_file, auth_file, crt, log_file))
        x.start()
