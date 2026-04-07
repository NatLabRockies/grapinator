import sys
import os
from os import path
import logging.config
from grapinator.settings import Settings, SchemaSettings

# Setup logging before any sub-module imports so the hierarchy is in place
# immediately.  disable_existing_loggers=False preserves child loggers
# (grapinator.settings, grapinator.model, etc.) created during imports.
_logging_conf_path = path.abspath(path.dirname(__file__)) + '/resources/logging.conf'
logging.config.fileConfig(_logging_conf_path, disable_existing_loggers=False)
log = logging.getLogger(__name__)

# get application settings, exit if something missing.
_config_file = os.environ.get('GRAPINATOR_CONFIG', '/resources/grapinator.ini')
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

# get app schema settings for dynamic class creation, exit if something missing
log.info('Loading schema: %s', settings.GQL_SCHEMA)
try:
    schema_settings = SchemaSettings(schema_file=settings.GQL_SCHEMA)
except (TypeError, FileNotFoundError) as err:
    log.critical('Failed to load schema: %s', err)
    sys.exit(1)
log.info('Schema loaded: %d entities', len(schema_settings.get_gql_classes()))
