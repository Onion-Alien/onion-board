- A rare crash while the app was starting is less likely: memory clean-up now runs only on
  the app's own window thread from the very start, not only once the window is up.
- A crash report now names the Windows module the crash happened in, as well as the last
  line of the app's own code that was running.
