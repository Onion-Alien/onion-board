- The installer is about 11 MB smaller: files the app carries twice (the mic helper's own
  copy of Python) are stored in it once, and the mic helper and the app no longer carry
  parts they never run (the rest of the app in the helper, test tools, PortAudio builds
  for other systems). Everything installs and works as before.
