BehaviorShield Windows Bundle
============================

Files
- BehaviorShield.exe : Frontend application (standalone)
- logger.exe : Background logger binary (single logger executable)
- install_bundle.bat : Full installer (run as Administrator)
- uninstall_bundle.bat : Full uninstaller (run as Administrator)
- register_logger_service.bat : Registers background startup task
- unregister_logger_service.bat : Removes background startup task

Install
1) Right-click install_bundle.bat
2) Run as Administrator

Uninstall
1) Right-click uninstall_bundle.bat
2) Run as Administrator

Notes
- Logger uses one executable (logger.exe).
- Background auto-start and auto-restart are handled by a SYSTEM startup task.
