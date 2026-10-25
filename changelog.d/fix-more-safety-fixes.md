- Saved clips survive a damaged clip list (a power cut mid-save): they're found again
  from their files instead of being deleted at the next start.
- Restarting the app (a language change, a reset) no longer hands the browser and the
  update installer the old copy's dead connection as your proxy.
- A sound pack that's too big to import is no longer kept in *My sound packs*.
- Resetting *Settings* keeps how the app goes online: Tor, a proxy, Offline mode and the
  features you switched off stay as they are.
- Restore points no longer keep your API key, Twitch login or proxy, and restoring one
  never brings back a key you have since changed.
- The usage count no longer saves up what happened while *Count me in* was off to send
  once it's back on, and nothing goes out in the moment after you switch it off.
- A link download that names no size is stopped once it passes the size limit, instead
  of filling the disk.
- A very long title or page from a site can no longer freeze the app while it's read.
- The app log names the proxy's kind only, never its address.
- Twitch: a sign-in renewed while the link restarted is kept (you were signed out), and
  Disconnect clears the older copies of your settings too.
- Auto push-to-talk lets go of the key when the app stops answering, so a frozen app
  never leaves your game's mic open.
- The local relay and the control API drop connections that are too slow to send their
  request, and the control API answers "busy" instead of dropping requests when many
  local tools call it at once. A web page can no longer lock a phone out of Onion Pocket,
  and a request that sends the same value twice is refused.
- Removing an add-on removes its old copies too, so one can't come back by itself.
- First start no longer moves in another program's `%APPDATA%\Soundboard` folder.
- Discord set-up keeps a copy of only the file it changes, for two weeks, not of all of
  Discord's stored data.
- Installing a Windows voice no longer runs a script file from your temp folder as admin.
