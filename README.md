# StashFileRenamer

This is a simple (and ugly) python script to process a directory of files into something useable by systems that use sidecar files such as Kodi or Plex.

WithoutPants has a Stash plugin to do the same sort of thing (https://github.com/stashapp/CommunityScripts/tree/main/scripts/kodi-helper), but it doesn't do file renaming

There is also a file renamer (https://github.com/stashapp/CommunityScripts/tree/main/scripts/Sqlite_Renamer), but for my personal uses I wanted something to handle full pathing.  I also preferred something that didn't require direct access to the database

So essentially what this script will do is to parse a directory of files, compare the file basename against the Stash database, then rename the file based on metadata and create the sidecar files.

By default it will create a directory structure based on the studio tree, following the studio parent nodes as far as they go, then move the file and sidecar files into the lowest level of that tree.

Essentially I like having my files organized, and "\network\site\filename" is how I like to do it.  :-)

Also a lot of the functionality in Stash connection is untested, since I run mine with http/unsecured.  I stole the connection logic from the TPDB Stash scraper (https://github.com/ThePornDatabase/stash_theporndb_scraper), but I'll test it one of these days