import sys
import os
from os import path
import logging.config
from grapinator.settings import Settings, SchemaSettings

# get application settings, exit if something missing.
try:
    settings = Settings(config_file='/resources/grapinator.ini')
except RuntimeError as err:
    print(f"Runtime error: {err}")
    sys.exit(1)

# get app schema settings for dynamic class creation, exit if somthing missing
try:
    schema_settings = SchemaSettings(schema_file=settings.GQL_SCHEMA)
except (TypeError, FileNotFoundError) as err: 
    print(f"Schema settings runtime error: {err}")
    sys.exit(1)

# setup logging
logging_conf_path = path.abspath(path.dirname(__file__)) + '/resources/logging.conf'
logging.config.fileConfig(logging_conf_path)
log = logging.getLogger(__name__)
