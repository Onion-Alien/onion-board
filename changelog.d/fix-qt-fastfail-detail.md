- When Qt itself ends the app (a "fast-fail" in Qt6Core.dll), the next start's crash
  report now says what Qt said and which part of the app was running, and whether the
  app was closing at the time, so these crashes can be found and fixed.
