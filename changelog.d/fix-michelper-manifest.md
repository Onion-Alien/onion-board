- Mic helper: its build lists every file with a checksum, and the admin step only sets up
  a build that matches; a damaged installed helper is noticed at once and replaced at the
  next Windows prompt, instead of every mic step waiting on a helper that can't start.
