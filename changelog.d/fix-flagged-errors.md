- The checks on Windows' default output and on Discord's settings each keep one thread
  of their own instead of starting a new one every few seconds, which could hold up the
  window (*Not Responding*) while Windows started it.
- An AI voices download that fails (offline, the connection dropped) no longer saves a
  crash report: the tab says what happened.
