# Free sound packs

Ready-made boards anyone can add to Onion Board in one click: **Sounds tab → Free packs**
(or the *Or get a free sound pack* button on an empty board). The list the app shows is
[catalog.json](catalog.json).

## Share your own pack

1. In Onion Board, put the sounds in a category of their own. Give them names, and
   pictures and hotkeys if you like.
2. **Backup → Export this category…** saves it as a zip.
3. Open the [Share a sound pack](https://github.com/Onion-Alien/onion-board/issues/new?template=sound-pack.yml)
   form (Free packs → *Share a pack* opens it too), drag the zip in, and say where each
   sound comes from.

Once it's checked, it shows up in everyone's Free packs window. No app update needed.

## The rules

- **Every sound and picture is CC0** (public domain): anyone can use it anywhere, in
  streams, videos and games, without credit. Either you made it and release it as CC0,
  or whoever made it published it as CC0 (Freesound, OpenGameArt, Wikimedia Commons and
  others mark it on each file). "Free to download" isn't the same thing.
- Nothing ripped from games, films, shows, songs or meme videos.
- Nothing hateful, sexual or meant to scare people into thinking something real is
  happening (fake alarms, sirens over a call…).
- Up to 300 MB, any sound format Onion Board plays. Levels roughly matched, please:
  a sound that blasts people's ears gets sent back.

## Checking a pack (maintainers)

```
python scripts/check_pack.py pack.zip --id short-name --name "Pack name" --tag pack-short-name --about "..." --author "..."
gh release create pack-short-name pack.zip --prerelease --title "Pack name (free sound pack)"
```

Listen to it, check each sound's source and licence, then add the printed entry to
`catalog.json` in a pull request. The app only downloads packs from this project's own
releases and checks every one against the SHA-256 in the list, so a pack can't change
after it was checked.
