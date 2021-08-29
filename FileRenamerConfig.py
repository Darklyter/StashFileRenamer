use_https = False # Set to False for HTTP
server_ip = "192.168.1.151"  #Don't include the '<' or '>'
server_port = "9999" #Don't include the '<' or '>'
username = "<USERNAME>" #Don't include the '<' or '>'
password = "<PASSWORD>" #Don't include the '<' or '>'
ignore_ssl_warnings = True # Set to True if your Stash uses SSL w/ a self-signed cert
ignore_tags = ['1','2','3318','6279'] # The ID numbers of tags to not write to NFO
# name_format is the resulting formatting of the filename for rename
# available options are:
# <STUDIO>      =   The name of the scene 'Studio'
# <PARENT>      =   The name of the 'Parent' studio.  If there is no parent,
#                   it will be replaced by scene studio
# <TITLE>       =   Title of the scene, as stored in Stash
# <DATE>        =   Date of the scenne, as stoed in Stash (will be YYY-MM-DD format)
# <ID>          =   Internal Stash ID of scene
# <TAGS>        =   The associated tag names, will be separated by ", "
# <PERFORMERS>  =   Names of associated performers, separated by ", "
# ~ name_format = "<STUDIO> - <DATE> - <TITLE> (<PERFORMERS>)"
name_format = "<STUDIO> - <DATE> - <TITLE> (<PERFORMERS>)"
create_parental_path = True # If true, a directory structure will be created that includes
                            # subdirectories for all parental studios.  File will be 
                            # moved to lowest level.
                            # If False, the file will not be moved from current directory
                            
create_collection_tags = True # this one is strange, admittedly.  Stash 'Tags' are stored in the 
                              # NFO 'Genres' instead.  However Plex allows you to use smart
                              # collections based on tags, so by default this will create tags
                              # based on the site and parent studio, such as "Site: SiteName" 
                              # and "Studio: StudioName".  Set this to False to disable creation
                              # of these tags.
headers = ""
api_key = ""

file_query = """
    query {
      findScenes(
        scene_filter: { path: { value: 
          "\\"<FILENAME>\\"", 
          modifier: INCLUDES } }
      ) {
        scenes {
          path
          id
          title
          details
          url
          date
          rating
          paths{
            screenshot
            stream
          }
          studio{
            id
            name
            image_path
            parent_studio{
              id
              name
              details
            }                
          }
          tags{
            id
            name
          }
          performers{
            name
            image_path
          }
          movies{
            movie{
              name
            }
          }
        }
      }
    }
"""
