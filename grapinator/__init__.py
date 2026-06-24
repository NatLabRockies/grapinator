import sys
import os
from os import path
import logging.config
from importlib.metadata import version, PackageNotFoundError
from grapinator.settings import Settings, SchemaSettings

try:
    __version__ = version('grapinator')
except PackageNotFoundError:
    # Running from source tree without installation
    __version__ = 'unknown'

# Resolve the ini file.  GRAPINATOR_CONFIG may point to any absolute path;
# the default is the ini file bundled with the installed package.  All other
# resource files (logging.conf, schema file) are expected to live in the same
# directory as the ini file.
_config_file = os.environ.get(
    'GRAPINATOR_CONFIG',
    path.join(path.abspath(path.dirname(__file__)), 'resources', 'grapinator.ini'),
)
_resources_dir = path.dirname(path.abspath(_config_file))

# Setup logging before any sub-module imports so the hierarchy is in place
# immediately.  disable_existing_loggers=False preserves child loggers
# (grapinator.settings, grapinator.model, etc.) created during imports.
_logging_conf_path = path.join(_resources_dir, 'logging.conf')
logging.config.fileConfig(_logging_conf_path, disable_existing_loggers=False)
log = logging.getLogger(__name__)

# get application settings, exit if something missing.
log.info('Loading configuration: %s', _config_file)
try:
    settings = Settings(config_file=_config_file)
except RuntimeError as err:
    log.critical('Failed to load configuration: %s', err)
    sys.exit(1)
log.info(
    'Configuration loaded: endpoint=%s db_type=%s auth_mode=%s',
    settings.FLASK_API_ENDPOINT, settings.DB_TYPE, settings.AUTH_MODE,
)

# GQL_SCHEMA may be an absolute path or a path relative to the resources
# directory.  Resolve it now so the rest of the app always sees an absolute path.
if settings.GQL_SCHEMA and not path.isabs(settings.GQL_SCHEMA):
    settings.GQL_SCHEMA = path.join(_resources_dir, settings.GQL_SCHEMA)

# get app schema settings for dynamic class creation, exit if something missing
log.info('Loading schema: %s', settings.GQL_SCHEMA)
try:
    schema_settings = SchemaSettings(schema_file=settings.GQL_SCHEMA)
except (TypeError, FileNotFoundError) as err:
    log.critical('Failed to load schema: %s', err)
    sys.exit(1)
log.info('Schema loaded: %d entities', len(schema_settings.get_gql_classes()))
