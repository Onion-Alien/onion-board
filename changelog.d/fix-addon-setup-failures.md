- Add-on installs: a step that failed on a connection problem, or on a file an antivirus was still
  scanning, is tried again by itself, and a failed install now says why (which site it couldn't
  reach, an antivirus, a secure connection that failed, a full disk) instead of "exit code 1".
- Add-on and other downloads no longer fail with "leads to your home network" behind a VPN app in
  fake IP mode.
