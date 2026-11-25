- Windows text-to-speech shuts down and cleans up its helper process cleanly so it no
  longer logs handle errors when closed or restarted.
- Saving settings now retries briefly when an antivirus or backup tool locks the temporary
  file, instead of failing the save.
- Preloading Settings pages in the background now polishes only the newly built page
  instead of re-polishing the whole dialog on every step.
