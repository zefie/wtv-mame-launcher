import sys, os, re, subprocess, ctypes, shutil, random
import winreg, win32gui, win32process, win32con, win32pipe, win32file, pywintypes
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import socket, time
import threading


# Mapping of machine codes to human-readable names
MACHINE_NAMES = {
    "wtv1bf0": "WebTV Classic (2MB)",
    "wtv1bfe": "WebTV Classic (Prototype)",
    "wtv1dev": "WebTV Classic Dev Box (4MB)",
    "wtv1dv2": "WebTV Classic Dev Box (2MB)",
    "wtv1pal": "WebTV Classic (PAL)",

    "wtv2drb": "WebTV Plus (Derby)",
    "wtv2lc2": "WebTV Plus (LC2)",
    "wtv2esr": "WebTV Echostar",
    "wtv2jpc": "WebTV Classic (Japan)",
    "wtv2jpp": "WebTV Plus (Japan)",
    "wtv2ncl": "WebTV New Classic (BPS, 8MB)",
    "wtv2npl": "WebTV New Plus (16MB)",
    "wtv2utv": "Ultimate TV",
    "wtv2uvd": "Ultimate TV Dev Box (Fake)",
    "wtv2wld": "WebTV Italian Prototype"
}

class MameWorker(QThread):
    window_found = pyqtSignal(int)  # Signal to send back the HWND

    def __init__(self, command, parent=None):
        super().__init__(parent)
        self.command = command
        self.mame_hwnd = None
        self.process = None
        self._should_stop = False

    def run(self):
        # Launch MAME process
        self.process = subprocess.Popen(self.command)
        pid = self.process.pid

        # Try to find the MAME window
        for _ in range(30):  # Try for ~3 seconds
            hwnd = self._find_window_by_pid(pid)
            if hwnd:
                self.mame_hwnd = hwnd
                self.window_found.emit(hwnd)
                break
            time.sleep(0.1)

        self.process.wait()

    def stop(self):
        self._should_stop = True
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _find_window_by_pid(self, target_pid):
        def callback(hwnd, pid_list):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == target_pid:
                    pid_list.append(hwnd)
        hwnds = []
        win32gui.EnumWindows(callback, hwnds)
        return hwnds[0] if hwnds else None

    def send_key(self, key):
        try:
            pipe = win32pipe.CreateNamedPipe(
                r'\\.\pipe\mame_input',
                win32pipe.PIPE_ACCESS_OUTBOUND,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_WAIT,
                1, 65536, 65536,
                0,
                None
            )
            win32pipe.ConnectNamedPipe(pipe, None)
            win32file.WriteFile(pipe, (key + "\n").encode())
            win32pipe.DisconnectNamedPipe(pipe)
        except pywintypes.error as e:
            print("Pipe closed or failed:", e)
            win32file.CloseHandle(pipe)

class MainWindow(QMainWindow):
    append_text_signal = pyqtSignal(str)

    def closeEvent(self, event):
        if self.worker:
            self.stop_mame()
        super().closeEvent(event)  # Ensure default cleanup continues

    def __init__(self):
        super().__init__()
        self.diskpath = os.path.join(os.getcwd(), "disks")
        self.setWindowTitle("WebTV MAME Launcher")
        self.setGeometry(100, 100, 400, 100)
 
        self.apply_dark_mode()

        # Create the Menu Bar
        self.create_menu_bar()

        main_widget = QWidget()
        self.settings = QSettings("zefie", "WebTVLauncher")
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        possible_executables = [
            "webtv.exe",
            "webtv",
            "webtv2.exe",
            "webtv2",
            "webtv1.exe",
            "webtv1",
        ]
        self.executable = None
        for prog in possible_executables:
            path = shutil.which(prog)
            if path:
                self.executable = path
                break
        if not self.executable:
            print("Could not find mame executable (webtv, webtv1, webtv2)(.exe)")
            exit(1)
            
        # Dropdown
        self.dropdown = QComboBox()
        pattern = r'\((wtv[^)]+)\)'
        data = subprocess.run([self.executable, '-listbios'], capture_output=True, text=True)
        matches = re.findall(pattern, data.stdout)
        # For each match, check MACHINE_NAMES for a friendly description
        items = []
        for m in matches:
            desc = MACHINE_NAMES.get(m, "")
            if desc:
                items.append(f"{m} - {desc}")
            else:
                items.append(m)
        self.dropdown.addItems(items)
        top_layout = QHBoxLayout()
        top_layout.setSizeConstraint(QLayout.SetFixedSize)
        sel_opt = QLabel("Select Machine:")
        top_layout.addWidget(sel_opt)
        ssid_static = QLabel("SSID:")
        ssid_static.setAlignment(Qt.AlignRight)
        top_layout.addWidget(ssid_static)
        self.ssid_label = QLabel("No SSID")
        top_layout.addWidget(self.ssid_label)
        layout.addLayout(top_layout)
        layout.addWidget(self.dropdown)

        # Checkboxes
        checkboxes_layout = QHBoxLayout()
        self.verbose = QCheckBox("Verbose")
        self.mamedebug = QCheckBox("MAME Debugger")
        self.serialdbg = QCheckBox("Serial Debug")
        self.diskboot = QCheckBox("Disk Boot")
        self.modem = QCheckBox("Modem")
        self.verbose.setChecked(True)
        self.modem.setChecked(True)
        self.mamedebug.setChecked(False)
        self.serialdbg.setChecked(True)
        self.diskboot.setChecked(True)
        self.bitblab = QLabel("BITB:")
        self.bitb = QLineEdit("touchppp.lan.zef:1122");
        checkboxes_layout.addWidget(self.verbose)
        checkboxes_layout.addWidget(self.mamedebug)
        checkboxes_layout.addWidget(self.serialdbg)
        checkboxes_layout.addWidget(self.diskboot)
        checkboxes_layout.addWidget(self.modem)
        bitb_layout = QHBoxLayout()
        bitb_layout.addWidget(self.bitblab)
        bitb_layout.addWidget(self.bitb)
        disk_layout = QHBoxLayout()
        self.disklab = QLabel("Disk:")
        self.disklab.hide()
        self.disk = QComboBox()
        self.scan_disk_list()
        
        bitb_layout.addWidget(self.disklab)
        bitb_layout.addWidget(self.disk)
        
        layout.addLayout(checkboxes_layout)
        layout.addLayout(bitb_layout)
        layout.addLayout(disk_layout)
        # Button
        self.button = QPushButton("Launch MAME")
        self.dropdown.currentTextChanged.connect(self.on_dropdown_changed)
        self.button.clicked.connect(self.on_button_click)
        self.modem.clicked.connect(self.on_modem_click)
        layout.addWidget(self.button)
        self.setMinimumWidth(1280)
        self.setMinimumHeight(792)
        # Multiline Text Area
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        hbox = QHBoxLayout()
        self.mame_window = QWidget();
        self.mame_window.setFixedSize(800, 600)
        self.mame_window.setFocusPolicy(Qt.ClickFocus)
        self.mame_window.mousePressEvent = lambda event: self.mame_window.setFocus()
        self.mame_window.setStyleSheet("background-color: black; border: 1px solid #555;")
        hbox.addWidget(self.mame_window)
        hbox.addWidget(self.text_area)
        layout.addLayout(hbox)
        input_layout = QHBoxLayout()
        self.single_line_input = QLineEdit()
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(lambda: self.send_serial_data(self.single_line_input.text()))
        input_layout.addWidget(self.single_line_input)
        input_layout.addWidget(self.send_button)
        self.single_line_input.returnPressed.connect(self.send_button.click)
        layout.addLayout(input_layout)
        main_widget.setLayout(layout)
        self.text_area.setVisible(self.serialdbg.isChecked())
        self.text_area.setStyleSheet("font-family: monospace; font-size: 8pt;")
        #self.text_area.setLineWrapMode(QTextEdit.NoWrap)
        self.text_area.setPlaceholderText("Serial output will appear here...")
        self.serialdbg.toggled.connect(self.toggleSerialDebug)
        self.append_text_signal.connect(self.handle_serial_data)
        self.text_area.autoFormattingEnabled = False
        self.load_settings()
        self.on_dropdown_changed()

    def getMachine(self):
        return self.dropdown.currentText().split(' ')[0]

    def toggleSerialDebug(self, checked):
        self.text_area.setEnabled(checked)
        self.single_line_input.setEnabled(checked)
        self.send_button.setEnabled(checked)

    def send_serial_data(self, data):
        self.single_line_input.clear()
        if not data:
            return
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.sendall((data + '\n').encode('utf-8'))
            except Exception as e:
                self.append_text_signal.emit(f"Send error: {e}")
        else:
            self.append_text_signal.emit("No serial connection established.")
       
    def handle_serial_data(self, data):
        """Append data to the text area."""
        if isinstance(data, bytes):
            data = data.decode(errors='replace')
        # Handle backspace (byte 0x08): remove previous character
        cursor = self.text_area.textCursor()
        
        if data and (data[-1] == '\x08' or  data[-1] == chr(8)):
            # Remove the last character in the text area
            cursor.movePosition(cursor.End)
            cursor.deletePreviousChar()
            data = data[:-1]
        # Read the last 10 bytes of the text area and compare to "Disk Boot?"
        last_text = self.text_area.toPlainText()
        # Get the last line from the text area (after the last newline)
        if '\n' in last_text:
            last_line = last_text.rsplit('\n', 1)[-1]
        else:
            last_line = last_text
        if "Disk Boot?" in last_text:
            diskboot = "y\n" if self.diskboot.isChecked() else "n\n"
            self.conn.sendall(diskboot.encode())
        # Handle carriage return (byte 0x0D): move to the start of the line
        if data and (data[-1] == '\r' or data[-1] == chr(13)):
            # Remove the carriage return character
            data = data[:-1]
        # Insert the data at the end of the text area
        if not data:
            return
        cursor = self.text_area.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(data)
        self.text_area.setTextCursor(cursor)

    def get_ssid_crc(self, ssid):
        """
        Compute a 2-digit hexadecimal CRC for the SSID.
        Only the first 14 characters of the ssid are used.
        """
        ssid = ssid[:14]
        crc = 0
        # Process every two characters of the SSID as a byte.
        for i in range(0, len(ssid), 2):
            inbyte = int(ssid[i:i+2], 16)
            for _ in range(8, 0, -1):
                mix = (crc ^ inbyte) & 0x01
                crc >>= 1
                if mix != 0:
                    crc ^= 0x8C
                inbyte >>= 1
        out = format(crc, 'x')
        if len(out) == 1:
            out = "0" + out
        return out

    def generate_ssid(self, manufacturer_id_checked):
        """
        Generate an SSID based on a template.
        The template "71xxxxxy00b002" has:
          - 'x' replaced by random hex digits (0-F)
          - 'y' replaced by "1" if manufacturer_id_checked is True; otherwise "0"
        The final SSID is the template plus a computed 2-digit CRC.
        """
        ssid_template = "71xxxxxy00b002"
        ssid = ssid_template
        
        # Replace each occurrence of "x" with a random hex digit
        while "x" in ssid:
            random_hex = format(random.randint(0, 15), 'x')
            ssid = ssid.replace("x", random_hex, 1)
        
        # Replace "y" based on the manufacturer_id_checked flag.
        if manufacturer_id_checked:
            ssid = ssid.replace("y", "1")
        else:
            ssid = ssid.replace("y", "0")
        
        # Append the CRC computed from the first 14 characters.
        ssid_full = ssid + self.get_ssid_crc(ssid)
        return ssid_full
        

    def apply_dark_mode(self):
        """Detects Windows dark mode and applies a dark stylesheet."""
        if self.is_windows_dark_mode():
            self.setStyleSheet(self.dark_stylesheet())

    def is_windows_dark_mode(self):
        """Checks if Windows is in dark mode by reading the registry."""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0  # 0 means dark mode is enabled, 1 means light mode
        except Exception:
            return False  # Default to light mode if registry read fails

    def dark_stylesheet(self):
        """Returns a dark mode stylesheet for PyQt5."""
        return """
            QWidget { background-color: #2b2b2b; color: #ffffff; }
            QComboBox, QLineEdit, QTextEdit, QPlainTextEdit { background-color: #3c3f41; color: #ffffff; border: 1px solid #555; }
            QPushButton { background-color: #555; color: white; border-radius: 4px; padding: 5px; }
            QPushButton:hover { background-color: #777; }
            QPushButton:pressed { background-color: #333; }
            QMenuBar { background-color: #2b2b2b; color: white; }
            QMenuBar::item { background: transparent; padding: 5px; }
            QMenuBar::item:selected { background: #444; }
            QMenu { background-color: #2b2b2b; color: white; }
            QMenu::item:selected { background: #444; }
            QLabel { color: white; }
            QCheckBox { color: white; }
        """
        
    def getMachineSSID(self, machine):
        try:
            filename = "roms/" + machine + "/ds2401.bin"
            with open(filename, "rb") as file:
                data = file.read()
                hex_str = data.hex()
                return hex_str
        except FileNotFoundError:
            return "No SSID"

    def setMachineSSID(self, machine, ssid):
        filepath = "roms/" + machine
        filename = filepath + "/ds2401.bin"
        os.makedirs(filepath, exist_ok=True)
        with open(filename, "wb") as file:
            data = bytes.fromhex(ssid)
            file.write(data)   

    def createSSID(self):
        machine = self.getMachine()
        self.setMachineSSID(machine, self.generate_ssid(True))
        self.readSSID()
        
    def readSSID(self):
        machine = self.getMachine()
        try:
            self.ssid_label.setText(self.getMachineSSID(machine))
        except:
            self.ssid_label.setText("No SSID")           
        

    def scan_disk_list(self):
        img_files = [file for file in os.listdir(self.diskpath) if file.lower().endswith('.img')]            
        self.disk.clear()
        self.disk.addItems(img_files)

    def create_menu_bar(self):
        """Creates the top menu bar"""
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Settings Menu
        tools_menu = menubar.addMenu("Tools")
        create_image = QAction("Create 1GB Disk Image", self)
        create_image.triggered.connect(self.create_disk_image)
        create_ssid = QAction("Generate New SSID", self)
        create_ssid.triggered.connect(self.createSSID)
        tools_menu.addAction(create_image)
        tools_menu.addAction(create_ssid)
       

        # Settings Menu
        settings_menu = menubar.addMenu("Settings")
        save_action = QAction("Save Settings", self)
        save_action.triggered.connect(self.save_settings)
        settings_menu.addAction(save_action)

        # PO Codes Menu
        po_menu = menubar.addMenu("PO Codes")
        po_action = QAction("411 - Technical Info", self)
        po_menu.addAction(po_action)
        po_action.triggered.connect(self.send_po_411)
        po_action = QAction("93288 - Connect Setup", self)
        po_action.triggered.connect(self.send_po_93288)
        po_menu.addAction(po_action)
        po_action = QAction("8675309 - Minibrowser", self)
        po_action.triggered.connect(self.send_po_8675309)
        po_menu.addAction(po_action)

        # Help Menu
        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)


    def isMAMERunning(self):
        """Check if MAME is currently running"""
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            return True
        return False


    def send_po_preamble(self):
        if self.isMAMERunning():
            self.worker.send_key('{F11}')
            self.worker.send_key('{F11}')

    def send_po_411(self):
        if self.isMAMERunning():
            self.send_po_preamble()
            self.worker.send_key("4")
            self.worker.send_key("1")
            self.worker.send_key("1")
        else:
            QMessageBox.warning(self, "Warning", "MAME is not running. Please launch MAME first.")

    def send_po_8675309(self):
        if self.isMAMERunning():
            self.send_po_preamble()
            self.worker.send_key("8")
            self.worker.send_key("6")
            self.worker.send_key("7")
            self.worker.send_key("5")
            self.worker.send_key("3")
            self.worker.send_key("0")
            self.worker.send_key("9")
        else:
            QMessageBox.warning(self, "Warning", "MAME is not running. Please launch MAME first.")

    def send_po_93288(self):
        if self.isMAMERunning():
            self.send_po_preamble()
            self.worker.send_key("9")
            self.worker.send_key("3")
            self.worker.send_key("2")
            self.worker.send_key("8")
            self.worker.send_key("8")
        else:
            QMessageBox.warning(self, "Warning", "MAME is not running. Please launch MAME first.")


    def create_disk_image(self):
        """Opens a save dialog and creates a 1GB empty disk image"""
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getSaveFileName(self, "Create Disk Image", "", "Disk Image (*.img);;All Files (*)", options=options)

        if file_name:
            try:
                with open(file_name, "wb") as f:
                    f.seek((1024 * 1024 * 1024) - 1)  # Seek to 1GB - 1 byte
                    f.write(b'\0')  # Write a single null byte to allocate space

                QMessageBox.information(self, "Success", f"Disk image created:\n{file_name}")

                # Refresh disk list
                self.scan_disk_list()

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create disk image:\n{str(e)}")



    def show_about_dialog(self):
        """Displays an About dialog"""
        QMessageBox.information(self, "About", "WebTV MAME Launcher\nVersion 1.1\nCreated by zefie with PyQt5")

    def save_settings(self):
        """Save settings before closing"""
        self.settings.setValue("dropdownIndex", self.dropdown.currentIndex())
        self.settings.setValue("verbose", self.verbose.isChecked())
        self.settings.setValue("modem", self.modem.isChecked())
        self.settings.setValue("mamedebug", self.mamedebug.isChecked())
        self.settings.setValue("serialdbg", self.serialdbg.isChecked())
        self.settings.setValue("diskboot", self.diskboot.isChecked())
        self.settings.setValue("bitb", self.bitb.text())
        self.settings.setValue("disk", self.disk.currentText())

    def load_settings(self):
        """Load settings on startup"""
        self.dropdown.setCurrentIndex(self.settings.value("dropdownIndex", 0, type=int))
        self.verbose.setChecked(self.settings.value("verbose", True, type=bool))
        self.modem.setChecked(self.settings.value("modem", True, type=bool))
        self.mamedebug.setChecked(self.settings.value("mamedebug", False, type=bool))
        self.serialdbg.setChecked(self.settings.value("serialdbg", True, type=bool))
        self.bitb.setText(self.settings.value("bitb", "touchppp.lan.zef:1122"))
        self.diskboot.setChecked(self.settings.value("diskboot", True, type=bool))
        self.disk.setCurrentText(self.settings.value("disk", ""))       

    def on_dropdown_changed(self):
        self.readSSID()
        if self.getMachine()[3] == "1":
            self.diskboot.hide()
            self.disklab.hide()
            self.disk.hide()
        elif (self.getMachine()[3] == "2" and (self.getMachine()[4] == "n" or self.getMachine()[4] == "w")):
            self.diskboot.show()
            self.disklab.hide()
            self.disk.hide()
        elif self.getMachine()[3] == "2" and (self.getMachine()[4] != "n" and self.getMachine()[4] != "w"):
            self.diskboot.show()
            self.disklab.show()
            self.disk.show()
            
    def on_modem_click(self):
        if self.modem.isChecked():
            self.bitblab.show()
            self.bitb.show()
        else:
            self.bitblab.hide()
            self.bitb.hide()

    def stop_mame(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        self.button.setText("Launch MAME")
        self.button.clicked.disconnect()
        self.button.clicked.connect(self.on_button_click)

    def embed_window(self, hwnd):
        """
        Reparent the MAME window to self.mame_window directly using Win32 APIs.
        """
        parent_hwnd = int(self.mame_window.winId())

        # Reparent MAME window to our QWidget
        win32gui.SetParent(hwnd, parent_hwnd)

        # Optional: remove window border/style
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style = style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)

        # Resize MAME window to fill self.mame_window
        rect = self.mame_window.rect()
        win32gui.SetWindowPos(
            hwnd, None,
            0, 0, rect.width(), rect.height(),
            win32con.SWP_NOZORDER | win32con.SWP_SHOWWINDOW
        )

        # Ensure MAME gets input
        ctypes.windll.user32.SetForegroundWindow(hwnd)

    def on_button_click(self):
        self.text_area.clear()
        selected = self.getMachine()
        command = [self.executable, selected]
        command += ["-nomouse", "-nomax", "-window"]        
        if self.verbose.isChecked():
            command += ["-verbose"]
        if self.mamedebug.isChecked():
            command += ["-debug"]
        if self.modem.isChecked():
            if selected[3] == "1":
                command += ["-spot:modem"]
            elif selected[3] == "2":
                command += ["-solo:modem"]
            command += ["null_modem"]
            command += ["-bitb1", "socket."+self.bitb.text()]
        if selected[3] == "2" and selected[4] != "n" and selected[4] != "w":
            command += ["-hard1", os.path.join(self.diskpath, self.disk.currentText())]
        if self.serialdbg.isChecked():
            command += ["-bitb2", "socket.127.0.0.1:3344"]
            self.start_socket_server()
        command += ["-skip_gameinfo"]
        command += ["-video", "sdl"]
        command += ["-keyboardprovider", "win32"]
        command += ["-autoboot_script", "mame_input_pipe.lua"]
        self.save_settings()
        print(f"{command}")
        # Run the command in another thread to avoid blocking the UI
        self.worker = MameWorker(command)
        self.worker.window_found.connect(self.embed_window)
        self.worker.start()
        # Soft loop: process events while the worker thread is running
        self.button.setText("Stop MAME")
        self.button.clicked.disconnect()
        self.button.clicked.connect(self.stop_mame)
        while self.worker.isRunning():
            QApplication.processEvents(QEventLoop.AllEvents, 100)
        self.button.setText("Launch MAME")
        self.button.clicked.disconnect()
        self.button.clicked.connect(self.on_button_click)
        self.mame_window.repaint()
                                    
    def start_socket_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', 3344))
        server.listen(1)
        # Accept one connection and keep it open
        def handle_client():
            try:
                self.conn, _ = server.accept()
                while True:
                    data = self.conn.recv(1024)
                    if not data:
                        break
                    # Optionally, display data in the text area using signal
                    self.append_text_signal.emit(data.decode(errors='replace'))
            except Exception as e:
                if "forcibly closed" in str(e):
                    # this is expected if the client disconnects
                    return
                print(f"Socket error: {e}")
            finally:
                server.close()
        threading.Thread(target=handle_client, daemon=True).start()

        
if __name__ == "__main__":
    os.environ['PATH'] += ":" + os.path.dirname(os.path.abspath(__file__))
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
    #sys.exit(app.exec_())  
