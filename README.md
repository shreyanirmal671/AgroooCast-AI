# 🛡️ RansomWatch — Real-Time Ransomware Detection System

RansomWatch is a **real-time ransomware detection and response system** that monitors file system activity, identifies suspicious behavior patterns, classifies potential ransomware threats, and automatically takes defensive actions to reduce security risks.

---

## 🚀 Features

### 🔍 Real-Time File Monitoring

* Tracks file creation, modification, deletion, and renaming
* Continuously monitors system activity for unusual behavior

### 🧠 Behavior-Based Detection

* Detects ransomware using behavioral patterns instead of static signatures
* Identifies suspicious actions such as mass file changes and abnormal extensions

### 🚨 Smart Alerting System

* Generates instant alerts on suspicious activity
* Uses cooldown mechanisms to prevent alert spamming
* Supports both CLI and desktop notifications

### 🧬 Ransomware Classification

* Classifies detected threats into known ransomware families
* Supports detection of:

  * WannaCry
  * LockBit
  * Ryuk
  * Conti
  * REvil / Sodinokibi
  * And more

### 📊 Live Monitoring Dashboard

* Displays real-time alerts and file activity
* Provides a clear and interactive view of system status

### 📋 Incident Reporting

* Generates structured reports of events, detections, and actions
* Useful for analysis, auditing, and security improvements

### 🧯 Automated Response & Containment

* Automatically responds to threats by:

  * Restricting file access
  * Pausing monitoring
  * Stopping suspicious processes
* Helps minimize damage during an attack

### 🧪 Safe Simulation Mode

* Simulates ransomware-like behavior in a controlled environment
* Allows safe testing without real malware

---

## 🏗️ Project Structure

```
RansomWatch/
│
├── monitor.py            # File system monitoring
├── analyzer.py           # Behavior analysis engine
├── rules.py              # Detection rules & thresholds
├── classifier.py         # Ransomware classification
├── alerting.py           # Alert system
├── notifier.py           # Desktop notifications
├── response.py           # Containment & response actions
├── report.py             # Incident report generator
├── logger_module.py      # Logging system
│
├── dashboard_server.py   # Backend (Flask + SocketIO)
├── dashboard.html        # Web dashboard UI
│
├── simulator.py          # Safe ransomware simulation
├── cli_menu.py           # Main entry point
│
├── logs/                 # Log files
└── reports/              # Generated reports
```

---

## ⚙️ Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/ransomwatch.git
cd ransomwatch
```

### 2. Install dependencies

```bash
pip install watchdog flask flask-socketio plyer
```

### Optional (Windows notifications)

```bash
pip install win10toast
```

---

## ▶️ Usage

Run the system:

```bash
python cli_menu.py
```

Then open the dashboard:

👉 http://localhost:5000

---

## 📌 CLI Options

```
[1] Start Monitoring (30 seconds)
[2] Start Monitoring (custom duration)
[3] Run Safe Simulation
[4] View Logs
[5] Generate Report
[6] View Summary
[7] Open Dashboard
[0] Exit
```

---

## 🔎 Detection Logic

RansomWatch detects potential ransomware based on:

* Suspicious file extensions (e.g., `.locked`, `.enc`)
* High volume of file changes in a short time
* Mass file renaming events
* Rapid activity within the same directory
* Behavioral patterns indicating abnormal activity

---

## 📊 Dashboard Features

* 📈 Real-time activity visualization
* ⚠️ Live alert notifications
* 🔴 Ransomware detection insights
* 📁 File activity tracking
* 📋 Incident report viewing

---

## 🧯 Response Actions

* Pause monitoring
* Restrict file write access
* Stop suspicious processes
* Trigger automated containment

---

## 🧪 Simulation Mode

* Simulates ransomware-like activities
* Includes:

  * Mass file modifications
  * Mass file renaming
  * Encryption-like behavior patterns
* Enables safe testing of detection system

---

## 📝 Logging

* All events and alerts are automatically recorded
* Logs are stored in:

```
/logs/ransomwatch_*.log
```

---

## ⚠️ Disclaimer

This project is intended for **educational and defensive security purposes only**.
Do **NOT** use it in unauthorized environments.

---

## 👨‍💻 Author

**Your Name**
GitHub: https://github.com/your-username

---

## ⭐ Future Improvements

* Machine learning-based detection
* Cloud-based alerting system
* Multi-device monitoring
* Integration with SIEM/security tools

---

## 🛡️ Stay Safe. Detect Early. Respond Faster.
