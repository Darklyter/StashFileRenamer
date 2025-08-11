import argparse
import os
import re
import string
import json
import glob
import requests
import shutil
import logging
import sys

import FileRenamerConfig as config


class SkipDryRunFilter(logging.Filter):
    def filter(self, record):
        return not getattr(record, 'dryrun', False)


class Summary:
    def __init__(self):
        self.total_files = 0
        self.renamed = 0
        self.skipped = 0
        self.errors = 0

    def report(self):
        logging.info("=== Summary Report ===")
        logging.info(f"Total files processed: {self.total_files}")
        logging.info(f"Files renamed:         {self.renamed}")
        logging.info(f"Files skipped:         {self.skipped}")
        logging.info(f"Errors encountered:    {self.errors}")


def parse_args():
    parser = argparse.ArgumentParser(description="Rename files from Stash metadata and create accompanying NFO files")
    parser.add_argument("--indir", default="./", help="Directory containing files to process")
    parser.add_argument("--outdir", default="./", help="Base output directory for renamed files")  # ✅ Add this line
    parser.add_argument("--mask", default="*", help="File mask to process")
    parser.add_argument("--extra", action="store_true", help="Also write JPG and NFO files")
    parser.add_argument("--dryrun", action="store_true", help="Preview changes without moving files")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--sceneroot", default=config.scene_root, help="Root directory for scene files")
    parser.add_argument("--galleryroot", default=config.gallery_root, help="Root directory for gallery files")
    return parser.parse_args()


def ensure_directories(args):
    for path in [args.sceneroot, args.galleryroot]:
        if not os.path.exists(path):
            try:
                os.makedirs(path)
                logging.info(f"Created missing directory: {path}")
            except Exception as e:
                logging.error(f"Failed to create directory {path}: {e}")


def setup_logging(verbose):
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler(sys.stdout)]

    if config.logfile_path:
        try:
            file_handler = logging.FileHandler(config.logfile_path, mode='a', encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s: %(message)s'))

            # ⛔️ Skip dryrun entries in the file log
            file_handler.addFilter(SkipDryRunFilter())

            handlers.append(file_handler)
        except Exception as e:
            print(f"⚠️ Failed to set up file logging: {e}")

    logging.basicConfig(level=level, format='%(levelname)s: %(message)s', handlers=handlers)


def validate_config():
    required = [config.server_ip, config.server_port]
    if not all(required):
        logging.error("Missing required config values: server_ip or server_port")
        sys.exit(1)

    config.server = build_server_url()


def build_server_url():
    protocol = "https" if config.use_https else "http"
    return f"{protocol}://{config.server_ip}:{config.server_port}"


def set_auth(server):
    try:
        r = requests.get(f"{server}/playground", verify=not config.ignore_ssl_warnings)
        if r.history and r.history[-1].status_code == 302:
            config.auth = "jwt"
            jwt_auth(server)
        elif r.status_code == 200:
            config.auth = "none"
        else:
            config.auth = "basic"
    except requests.RequestException as e:
        logging.error(f"Failed to connect to server: {e}")
        sys.exit(1)


def jwt_auth(server):
    try:
        response = requests.post(f"{server}/login", data={'username': config.username, 'password': config.password}, verify=not config.ignore_ssl_warnings)
        token = response.cookies.get('session')
        if not token:
            logging.error("JWT authentication failed")
            sys.exit(1)
        config.headers['Authorization'] = f"Bearer {token}"
    except requests.RequestException as e:
        logging.error(f"JWT auth error: {e}")
        sys.exit(1)


def get_file_list(indir, mask):
    pattern = os.path.join(indir, mask)
    return [f for f in glob.glob(pattern) if os.path.isfile(f)]


def call_graphql(query):
    try:
        response = requests.post(f"{config.server}/graphql", json={'query': query}, headers=config.headers, verify=not config.ignore_ssl_warnings)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"GraphQL query failed: {e}")
        return {}


def fetch_metadata(basename):
    query = config.file_query.replace("<FILENAME>", basename)
    result = call_graphql(query)
    if not result or not isinstance(result, dict):
        logging.error(f"No result returned for query: {basename}")
        return {}

    logging.debug(f"GraphQL response for {basename}:\n{json.dumps(result, indent=2)}")
    return result


def should_process(scene_data):
    return scene_data and scene_data.get("studio")


def get_parental_path(studioid):
    basequery = """
        query {
          findStudio(id: "<STUDIONUM>") {
            id
            name
            parent_studio {
              id
            }
          }
        }
    """
    studiolist = {}
    counter = 0

    while studioid:
        query = basequery.replace("<STUDIONUM>", studioid)
        result = call_graphql(query)

        if not isinstance(result, dict):
            logging.error(f"Invalid response type for studio ID {studioid}: {type(result)}")
            break

        data = result.get('data')
        if not isinstance(data, dict):
            logging.error(f"No 'data' field in response for studio ID {studioid}")
            break

        studio = data.get('findStudio')
        if not isinstance(studio, dict):
            logging.warning(f"Studio ID {studioid} not found or returned null.")
            break

        name = studio.get('name', f"UnknownStudio_{studioid}")
        studiolist[counter] = name

        parent = studio.get('parent_studio', None)
        if parent is None:
            logging.debug(f"Studio ID {studioid} has no parent. Ending path trace.")
            break

        if not isinstance(parent, dict):
            logging.warning(f"Unexpected parent_studio format for studio ID {studioid}: {type(parent)}")
            break

        studioid = parent.get('id')
        if not studioid:
            logging.debug("Parent studio has no ID. Ending path trace.")
            break

        counter += 1

    if not studiolist:
        studiolist[0] = "Uncategorized"

    return studiolist


def truncate_string(s, max_length=50):
    if len(s) <= max_length:
        return s
    for sep in ['-', '_']:
        pos = s[:max_length].rfind(sep)
        if pos != -1:
            return s[:pos]
    return s[:max_length]


def build_output_path(filedata, args):
    path = args.outdir
    if ".zip" in filedata['extension'].lower():
        path = args.galleryroot
    else:
        path = args.sceneroot

    studiolist = filedata.get('studiolist')
    if not isinstance(studiolist, dict) or not studiolist:
        logging.warning(f"No valid studio path found for {filedata['filename']}. Using fallback.")
        studiolist = {0: "Uncategorized"}

    for i in reversed(sorted(studiolist.keys())):
        studiopath = re.sub(r'[^-a-zA-Z0-9_.() ]+', '', studiolist[i]).strip()
        path = os.path.join(path, studiopath.title())

    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        logging.error(f"Failed to create directory {path}: {e}")
        path = args.outdir  # fallback to base output

    return path


def normalize_string(s):
    return re.sub(r'[^a-zA-Z0-9]+', '', s).lower()


def format_filename(filedata, args):
    data = filedata['jsondata']

    # Performers
    performers = ", ".join([p['name'] for p in data.get('performers', [])[:3]])
    performer_str = f"({performers})" if performers else ""

    # Tags
    tags = ", ".join([t['name'] for t in data.get('tags', [])])

    # Dimensions
    file_info = data.get('files', [{}])[0]
    width = file_info.get('width')
    height = file_info.get('height')
    dimensions = f"[{width}x{height}]" if width and height else ""

    # Title and Code
    title = re.sub(r'[^-a-zA-Z0-9_.()\[\]\' ,]+', ' ', data.get('title', 'Untitled')).title()
    title = truncate_string(title, 100)
    code = truncate_string(data.get('code', ''), 50)

    normalized_title = normalize_string(title)
    normalized_code = normalize_string(code)

    if normalized_title == normalized_code:
        if args.dryrun:
            logging.info(f"[DRY-RUN] STUDIOID removed from filename due to equality with TITLE in Stash data for: {filedata['filename']}", extra={'dryrun': True})
        else:
            logging.info(f"STUDIOID removed from filename due to equality with TITLE in Stash data for: {filedata['filename']}")
        name = config.name_format.replace(" [<STUDIOID>]", "")
        name = name.replace("<STUDIOID>", "")
    else:
        name = config.name_format

    # Studio and Parent Studio
    studio = data.get('studio')
    studio_name = studio.get('name', 'UnknownStudio') if studio else 'UnknownStudio'

    parent = studio.get('parent_studio') if studio else None
    if isinstance(parent, dict):
        parent_name = parent.get('name', studio_name)
    else:
        parent_name = studio_name

    # Build filename
    name = name.replace("<STUDIO>", studio_name.title())
    name = name.replace("<PARENT>", parent_name.title())
    name = name.replace("<TITLE>", string.capwords(title))
    name = name.replace("<ID>", data.get('id', ''))
    name = name.replace("<DATE>", data.get('date', ''))
    name = name.replace("<STUDIOID>", code)
    name = name.replace("<PERFORMERS>", performer_str)
    name = name.replace("<TAGS>", tags)
    name = name.replace("<DIMENSIONS>", dimensions)

    # Final cleanup
    return re.sub(r'[^-a-zA-Z0-9_\.()\[\]\' ,]+', '', name)


def move_file(filedata, targetname, dry_run):
    fullpath = filedata['output_path']
    extension = filedata['extension']
    target = os.path.join(fullpath, targetname + extension)

    if dry_run:
        logging.info(f"[DRY-RUN] Would move: {filedata['filename']} → {target}", extra={'dryrun': True})
    else:
        if os.path.exists(target):
            logging.warning(f"Target file already exists: {target}. Skipping move.")
            return None  # or return original path if you prefer

        logging.info(f"Moving: {filedata['filename']} → {target}")
        shutil.move(filedata['filename'], target)

    return os.path.join(fullpath, targetname)


def get_image(filedata):
    url = filedata['jsondata'].get('paths', {}).get('screenshot')
    if url:
        try:
            response = requests.get(url)
            response.raise_for_status()
            with open(filedata['fullpathname'] + ".jpg", "wb") as f:
                f.write(response.content)
        except requests.RequestException as e:
            logging.warning(f"Image download failed: {e}")
    else:
        logging.info(f"No screenshot for {filedata['filename']}")


def generate_nfo(scene):
    tags = ""
    if config.create_collection_tags:
        parent = scene['studio'].get('parent_studio', {}).get('name', scene['studio']['name'])
        tags += f"<tag>Site: {scene['studio']['name']}</tag>\n"
        tags += f"<tag>Studio: {parent}</tag>\n"

    genres = "\n".join([
        f"<genre>{t['name']}</genre>"
        for t in scene['tags']
        if t['id'] not in config.ignore_tags and "ambiguous" not in t['name'].lower()
    ])

    performers = "\n".join([
        f"""    <actor>
        <name>{p['name']}</name>
        <role></role>
        <order>{i}</order>
        <thumb>{p['image_path']}</thumb>
    </actor>""" for i, p in enumerate(scene['performers'])
    ])

    thumbs = f"<thumb aspect='poster'>{scene['paths']['screenshot']}</thumb>"
    fanart = f"<fanart><thumb>{scene['paths']['screenshot']}</thumb></fanart>"

    rating = str(int(scene['rating']) * 2) if scene.get('rating') else ""
    date = scene.get('date', "")
    studio = scene['studio']['name']
    title = scene.get('title', "Untitled")
    plot = scene.get('details', "")
    scene_id = scene['id']

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<movie>
    <title>{title}</title>
    <userrating>{rating}</userrating>
    <plot>{plot}</plot>
    <uniqueid type="stash">{scene_id}</uniqueid>
    {tags}
    <premiered>{date}</premiered>
    <studio>{studio}</studio>
    {performers}
    {thumbs}
    {fanart}
    {genres}
</movie>
"""


def write_file(filename, content, use_utf=True):
    encoding = "utf-8-sig" if use_utf else None
    try:
        with open(filename, "w", encoding=encoding) as f:
            f.write(content)
        logging.info(f"Wrote file: {filename}")
    except Exception as e:
        logging.error(f"Failed to write file {filename}: {e}")


def process_file(file, args):
    basename = os.path.splitext(os.path.basename(file))[0].strip().rstrip(string.punctuation)
    part_match = re.search(r'(.*)-\d+$', basename)
    if part_match and ".zip" in file:
        basename = part_match.group(1)

    logging.debug(f"Querying for: {basename}")
    metadata = fetch_metadata(basename)

    if not isinstance(metadata, dict):
        logging.error(f"Metadata is not a dictionary for {basename}")
        return "error"

    data = metadata.get('data')
    if not isinstance(data, dict):
        logging.error(f"No 'data' field in GraphQL response for {basename}")
        return "error"

    find_scenes = data.get('findScenes')
    if not isinstance(find_scenes, dict):
        logging.error(f"'findScenes' field missing or invalid for {basename}")
        return "error"

    scenes = find_scenes.get('scenes')
    if not isinstance(scenes, list) or not scenes:
        logging.warning(f"No scenes found for {basename}")
        return "skipped"

    scene = scenes[0]

    if not should_process(scene):
        logging.warning(f"Scene data missing studio info: {basename}")
        return "skipped"

    if not isinstance(scene.get('files'), list) or len(scene['files']) != 1:
        logging.warning(f"Multiple or missing files in Stash for {file}. Skipping.")
        return "skipped"

    studio = scene.get('studio')
    studio_id = studio.get('id') if isinstance(studio, dict) else None
    if not studio_id:
        logging.warning(f"No studio ID found for {basename}. Skipping.")
        return "skipped"

    try:
        filedata = {
            'jsondata': scene,
            'filename': file,
            'basename': basename,
            'extension': os.path.splitext(file)[-1],
            'studiolist': get_parental_path(studio_id)
        }

        filedata['output_path'] = build_output_path(filedata, args)
        targetname = format_filename(filedata, args)
        filedata['fullpathname'] = move_file(filedata, targetname, args.dryrun)
        if not filedata['fullpathname']:

            if args.dryrun:
                logging.info(f"[DRY-RUN] File \'{filedata['filename']}\' not moved due to existing target: {targetname}", extra={'dryrun': True})
            else:
                logging.warning(f"File \'{filedata['filename']}\' not moved due to existing target: {targetname}")
            return "skipped"

        if args.extra:
            get_image(filedata)
            nfo = generate_nfo(scene)
            write_file(filedata['fullpathname'] + ".nfo", nfo, use_utf=True)

        return "renamed"

    except Exception as e:
        logging.error(f"Unhandled error processing {file}: {e}")
        logging.debug(f"Scene data: {json.dumps(scene, indent=2)}")
        return "error"


def main():
    args = parse_args()
    setup_logging(args.verbose)

    validate_config()  # ✅ This must be called before anything uses config.server
    ensure_directories(args)

    summary = Summary()
    files = get_file_list(args.indir, args.mask)

    if not files:
        logging.warning("No files found to process.")
        return

    for file in files:
        summary.total_files += 1
        try:
            result = process_file(file, args)
            if result == "renamed":
                summary.renamed += 1
            elif result == "skipped":
                summary.skipped += 1
            else:
                summary.errors += 1
        except Exception as e:
            logging.error(f"Unhandled error processing {file}: {e}")
            summary.errors += 1

    summary.report()


if __name__ == "__main__":
    main()
