"""
Folder Picker GUI v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 09/02/2026

This script runs a GUI for the user to select a project folder, then loads in the config.json.
"""

import sys, json
from pathlib import Path
from PyQt5.QtWidgets import ( # type: ignore
    QApplication,
    QWidget,
    QPushButton,
    QLabel,
    QFileDialog,
    QVBoxLayout
)

# Configuration file
CONFIG_FILE = r'bin\config.json'
# Global variable to store the selected folder
selected_folder = ''

def load_config():
    """Loads the existing configuration if it exists"""
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def browse_folder():
    """Browses for a folder"""
    global selected_folder
    folder = QFileDialog.getExistingDirectory(
        window,
        'Select Project Folder'
    )
    if folder:
        selected_folder = folder
        folder_label.setText(f'Selected Folder:\n{selected_folder}')

def save_config():
    """Saves user configuration"""
    if not selected_folder:
        status_label.setText('Please select a folder first.')
        return
    config = load_config()
    # Update or create values
    config['project_folder'] = selected_folder
    config['aois'] = [
        {
            'name': 'Tengiz',
            "paths": {
                "root": fr'{selected_folder}\Tengiz',
                "baseline": fr'{selected_folder}\Tengiz\baseline',
                "cache": fr'{selected_folder}\Tengiz\cache',
                "detections": fr'{selected_folder}\Tengiz\detections',
                "database": fr'{selected_folder}\Tengiz\database',
                "logs": fr'{selected_folder}\Tengiz\logs'
            },
            'coords': [45.9567, 53.2416, 46.2082, 53.5334],
        },
        {
            'name':'Kokzhide',
            "paths": {
                "root": fr'{selected_folder}\Kokzhide',
                "baseline": fr'{selected_folder}\Kokzhide\baseline',
                "cache": fr'{selected_folder}\Kokzhide\cache',
                "detections": fr'{selected_folder}\Kokzhide\detections',
                "database": fr'{selected_folder}\Kokzhide\database',
                "logs": fr'{selected_folder}\Kokzhide\logs'
            },
            'coords': [52.1234, 48.5678, 52.4567, 48.9012],
        }
    ]
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)
    status_label.setText('Configuration saved.')
    sys.exit(app.exec_())

# Create application
app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle('Project Configuration')
window.resize(500, 200)
browse_button = QPushButton('Browse for Folder')
browse_button.clicked.connect(browse_folder)
save_button = QPushButton('Save Configuration')
save_button.clicked.connect(save_config)
folder_label = QLabel('No folder selected.')
status_label = QLabel()
layout = QVBoxLayout()
layout.addWidget(browse_button)
layout.addWidget(folder_label)
layout.addWidget(save_button)
layout.addWidget(status_label)
window.setLayout(layout)
window.show()
sys.exit(app.exec_())