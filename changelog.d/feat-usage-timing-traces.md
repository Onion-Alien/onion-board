- The anonymous usage count's problem reports are easier to fix from: each error now has
  its whole stack (library code as module and function names only, never a file or
  folder), the thread it happened on and the errors that led to it, and each event says
  how far into the run it happened and in what order, plus how long the start, downloads
  and the mic effect's set-up took. Still no messages, paths, names or devices, and times
  of day stay rounded to 10 minutes (SECURITY.md lists every field).
