# A simple python script to iterate through files in the directory, then
# rename and create Kodi style sidecar files from Stash queries
# It will create an NFO and background jpg from Stash metadata
# Files will be moved to a subdirectory tree based on Studio parents
# as defined in Stash
# The query is based on filename, so if the file has not been scraped /
# tagged in Stash then it will be skipped.  It uses the Studio attribute
# to determine whether to parse or not
# Most code 'borrowed' heavily from WithoutPants' Kodi Helper (https://github.com/stashapp/CommunityScripts/tree/main/scripts/kodi-helper)
# and the TPDB Stash scraper (https://github.com/ThePornDatabase/stash_theporndb_scraper)
import argparse
import os
import re
import argparse
import json
import glob
import requests
import shutil
import logging

import FileRenamerConfig as config

def parseArgs():
    parser = argparse.ArgumentParser(description="Rename files from Stash metadata and create accompanying NFO files")
    parser.add_argument("--indir", metavar="<input directory>", help="Directory containing files to process (Default to '.')",default="./")
    parser.add_argument("--outdir", metavar="<output directory>", help="Generate files in <outdir> (Default to '.')",default="./")
    parser.add_argument("--mask", metavar="<filemask>", help="File mask to process.  Defaults to '*'", default="*")
    return parser.parse_args()

def main():
    args = parseArgs()

    if config.use_https:
        server = 'https://' + str(config.server_ip) + ':' + str(config.server_port)
    else:
        server = 'http://' + str(config.server_ip) + ':' + str(config.server_port)
    config.server = server
    config.auth = setAuth(server)

    # Iterate through current directory
    # ~ filelist = [f for f in os.listdir('.') if os.path.isfile(f)]
    filelist = glob.glob(args.mask.strip())
    if filelist:
        filelist = [f for f in filelist if os.path.isfile(f)]
        for file in filelist:
            basename = os.path.splitext(file)[0]
            jsonresult = callGraphQL(config.file_query.replace("<FILENAME>", basename), config.server, config.auth)
            # We only want to process files that have a Studio defined
            try:
                if jsonresult and not jsonresult['data']['findScenes']['scenes'][0]['studio'] is None:
                    filedata = {}
                    filedata['jsondata'] = jsonresult['data']['findScenes']['scenes'][0]
                    filedata['studiolist'] = get_parental_path(filedata['jsondata']['studio']['id'])
                    filedata['filename'] = file
                    filedata['basename'] = os.path.splitext(file)[0]
                    filedata['fullpathname'] = renamefile(filedata, args)
                    getimage(filedata)
                    nfodata = generateNFO(filedata['jsondata'],args)
                    writeFile(filedata['fullpathname'] + ".nfo", nfodata, True)
                else:
                    print(f' *** Scene data not found for {basename}')
            except Exception as e:
                print(f' Skipping file: {basename} due to {e}')


def callGraphQL(query, server, http_auth_type, retry = True):
    graphql_server = server+"/graphql"
    json = {}
    json['query'] = query

    try:
        if http_auth_type == "basic":
            response = requests.post(graphql_server, json=json, headers=config.headers, auth=(username, password), verify= not config.ignore_ssl_warnings)
        elif http_auth_type == "jwt":
            response = requests.post(graphql_server, json=json, headers=config.headers, cookies={'session':auth_token}, verify= not config.ignore_ssl_warnings)
        else:
            response = requests.post(graphql_server, json=json, headers=config.headers, verify= not config.ignore_ssl_warnings)

        if response.status_code == 200:
            result = response.json()
            if result.get("error", None):
                for error in result["error"]["errors"]:
                    logging.error("GraphQL error:  {}".format(error), exc_info=debug_mode)
            if result.get("data", None):
                return result
        elif retry and response.status_code == 401 and http_auth_type == "jwt":
            jwtAuth()
            return callGraphQL(query, variables, False)
        else:
            logging.error("GraphQL query failed to run by returning code of {}. Query: {}.".format(response.status_code, query))
            raise Exception("GraphQL error")
    except requests.exceptions.SSLError:
        proceed = input("Caught certificate error trying to talk to Stash. Add ignore_ssl_warnings=True to your configuration.py to ignore permanently. Ignore for now? (yes/no):")
        if proceed == 'y' or proceed == 'Y' or proceed =='Yes' or proceed =='yes':
            ignore_ssl_warnings =True
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            return callGraphQL(query, variables)
        else:
            print("Exiting.")
            sys.exit()

def setAuth(server):
    global http_auth_type
    r = requests.get(server+"/playground", verify= not config.ignore_ssl_warnings)
    if len(r.history)>0 and r.history[-1].status_code == 302:
        http_auth_type="jwt"
        jwtAuth()
    elif r.status_code == 200:
        http_auth_type="none"
    else:
        http_auth_type="basic"
    return http_auth_type

def jwtAuth():
    response = requests.post(server+"/login", data = {'username':config.username, 'password':config.password}, verify= not config.ignore_ssl_warnings)
    auth_token=response.cookies.get('session',None)
    if not auth_token:
        logging.error("Error authenticating with Stash.  Double check your IP, Port, Username, and Password", exc_info=debug_mode)
        sys.exit()

def renamefile(filedata, args):
    nameformat = config.name_format
    # Need to create folder structure if not there
    fullpath = args.outdir.strip()

    if config.create_parental_path:
        for item in reversed(filedata['studiolist']):
            studiopath = re.sub(r'[^-a-zA-Z0-9_.() ]+', '', filedata['studiolist'][item])
            fullpath = fullpath + studiopath.strip() + "/"
        if not os.path.exists(fullpath):
            os.makedirs(fullpath,exist_ok = True)

    # Set up filename to use
    data = filedata['jsondata']
    performers = []
    counter = 0
    for performer in data['performers']:
        if counter < 3:
            performers.append(performer['name'])
            counter += 1
    if performers:
        performerstring = ", ".join(performers)
        performerstring = f"({performerstring.strip()})"
    else:
        performerstring = ""

    tags = []
    for tag in data['tags']:
        tags.append(tag['name'])
    if tags:
        tagstring = ", ".join(tags)
    else:
        tagstring = ""

    targetname = config.name_format
    targetname = targetname.replace("<STUDIO>", data['studio']['name'].strip().title())

    if not data['studio']['parent_studio'] is None:
        parentname = data['studio']['parent_studio']['name'].strip().title()
    else:
        parentname = data['studio']['name'].strip().title()

    if not data['file']['width'] is None and not data['file']['height'] is None:
        dimensions = F"[{str(data['file']['width'])}x{str(data['file']['height'])}]"
    else:
        dimensions = ""

    if len(data['title']) > 100:
        data['title'] = data['title'].strip().title()[0:100]

    targetname = targetname.replace("<PARENT>", parentname)
    targetname = targetname.replace("<TITLE>", data['title'].strip().title())
    targetname = targetname.replace("<ID>", data['id'].strip())
    targetname = targetname.replace("<DATE>", data['date'].strip())
    targetname = targetname.replace("<PERFORMERS>", performerstring)
    targetname = targetname.replace("<TAGS>", tagstring)
    targetname = targetname.replace("<DIMENSIONS>", dimensions)
    targetname = re.sub(r'[^-a-zA-Z0-9_\.()\[\] ,]+', '', targetname)

    # Now move the file
    filepathname = fullpath + targetname
    origfile = filedata['filename']
    print(f' Moving file: {origfile} to {filepathname}')
    shutil.move(origfile, filepathname + os.path.splitext(filedata['filename'])[-1])
    # ~ shutil.copy(origfile, filepathname + os.path.splitext(filedata['filename'])[-1])

    # Return the path and bare filename to be used for NFO and JPG
    return filepathname

def getimage(filedata):
    if not filedata['jsondata']['paths'] is None:
        imagepath = filedata['jsondata']['paths']['screenshot']
        filepath = filedata['fullpathname'] + ".jpg"
        response = requests.get(imagepath)
        imagefile = open(filepath, "wb")
        imagefile.write(response.content)
        imagefile.close()
    else:
        filename = filedata['fullpathname']
        print(f'No Screenshot found for {filename}')


def addAPIKey(url):
    if config.api_key:
        return url + "&apikey=" + config.api_key
    return url


def getSceneTitle(scene):
    if scene["title"] != None and scene["title"] != "":
        return scene["title"]

    return basename(scene["path"])

def generateNFO(scene, args):
    ret = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<movie>
    <title>{title}</title>
    <userrating>{rating}</userrating>
    <plot>{details}</plot>
    <uniqueid type="stash">{id}</uniqueid>
    {tags}
    <premiered>{date}</premiered>
    <studio>{studio}</studio>
    {performers}
    {thumbs}
    {fanart}
    {genres}
</movie>
"""
    # ~ tags = ""
    # ~ for t in scene["tags"]:
        # ~ tags = tags + """
    # ~ <tag>{}</tag>""".format(t["name"])

    genres = ""
    for t in scene["tags"]:
        if t['id'] not in config.ignore_tags and "ambiguous" not in t['name'].lower():
            genres = genres + """
        <genre>{}</genre>""".format(t["name"])

    rating = ""
    if scene["rating"] != None:
        rating = str(int(scene["rating"])*2)

    date = ""
    if scene["date"] != None:
        date = scene["date"]

    studio = ""
    logo = ""
    if scene["studio"] != None:
        studio = scene["studio"]["name"]
        logo = scene["studio"]["image_path"]
        if not logo.endswith("?default=true"):
            logo = addAPIKey(logo)
        else:
            logo = ""

    performers = ""
    i = 0
    for p in scene["performers"]:
        thumb = addAPIKey(p["image_path"])
        performers = performers + """
    <actor>
        <name>{}</name>
        <role></role>
        <order>{}</order>
        <thumb>{}</thumb>
    </actor>""".format(p["name"], i, thumb)
        i += 1

    thumbs = [
        """<thumb aspect="poster">{}</thumb>""".format(addAPIKey(scene["paths"]["screenshot"]))
    ]
    fanart = [
        """<thumb>{}</thumb>""".format(addAPIKey(scene["paths"]["screenshot"]))
    ]
    if logo != "":
        thumbs.append("""<thumb aspect="clearlogo">{}</thumb>""".format(logo))
        fanart.append("""<thumb>{}</thumb>""".format(logo))

    fanart = """<fanart>{}</fanart>""".format("\n".join(fanart))

    if not scene['studio']['parent_studio'] is None:
        parent = scene['studio']['parent_studio']['name']
    else:
        parent = scene['studio']['name']
    if config.create_collection_tags:
        tags = '<tag>Site: {}</tag>\n'.format(scene['studio']['name'])
        tags += '<tag>Studio: {}</tag>\n'.format(parent)
    else:
        tags = ""


    # ~ genres = []
    # ~ if args.genre != None:
        # ~ for g in args.genre:
            # ~ genres.append("<genre>{}</genre>".format(g))

    ret = ret.format(title = getSceneTitle(scene), rating = rating, id = scene["id"], tags = tags, date = date, studio = studio, performers = performers, details = scene["details"] or "", thumbs = "\n".join(thumbs), fanart = fanart, genres = genres)

    return ret


def writeFile(fn, data, useUTF):
    encoding = None
    if useUTF:
        encoding = "utf-8-sig"
    f = open(fn, "w", encoding=encoding)
    f.write(data)
    f.close()


def get_parental_path(studioid):
    basequery = """
        query {
          findStudio(
            id: "<STUDIONUM>"
          ) {
            id
            name
            parent_studio{
              id
            }
          }
        }
    """
    query = basequery.replace("<STUDIONUM>", studioid)
    jsonresult = callGraphQL(query, config.server, config.auth)
    counter = 0
    studiolist = {}
    studioid = jsonresult['data']['findStudio']['id']
    while True:
        query = basequery.replace("<STUDIONUM>", studioid)
        jsonresult = callGraphQL(query, config.server, config.auth)
        studiolist[counter] = jsonresult['data']['findStudio']['name']
        if not jsonresult['data']['findStudio']['parent_studio'] is None:
            studioid = jsonresult['data']['findStudio']['parent_studio']['id']
            jsonresult = {}
            counter += 1
        else:
            break
    return studiolist


if __name__ == "__main__":
    main()
